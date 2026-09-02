"""Streamlit console for the multi-agent assistant.

Run with:
    streamlit run streamlit_app.py

Flow — an escalation ladder. Every source is graded by the supervisor before it
is used, and a failed grade falls through to the next source:

    attached files  →  supervisor  ─approved→  agent_1 → agent_2 → editor
          ↓ rejected
    archive search  →  supervisor  ─approved→  agent_1 → agent_2 → editor
          ↓ rejected
    web search      →  supervisor  ─approved→  agent_1 → agent_2 → editor
          ↓ rejected
    "I don't have relevant information"

Design lives in vintage_theme.py.
"""

import os
import tempfile
import time
import uuid
import warnings
from typing import TypedDict

import numpy as np
import streamlit as st
from dotenv import load_dotenv

from langchain_core.messages import HumanMessage
from langchain_chroma import Chroma
from langchain_groq import ChatGroq
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.graph import StateGraph, START, END

from ingest_documents import (
    load_file, COLLECTION, PERSIST_DIR, CHUNK_SIZE, CHUNK_OVERLAP,
)
import conversation_store as store
import observability as obs
import vintage_theme as ui

load_dotenv()

# Tracing has to be configured before the first chain is constructed, and the
# transcript store before the first turn is answered.
obs.configure_langsmith()
ENVIRONMENT = obs.environment()
store.get_engine()

ui.configure_page()
ui.inject_css()

# ── Fixed settings (previously sidebar controls) ─────────────
MODEL_NAME = "openai/gpt-oss-120b"
TEMPERATURE = 0.7
TOP_K = 4
RELEVANCE_FLOOR = 0.25      # below this, retrieval is treated as a miss
MAX_CONTEXT_CHARS = 12000   # budget for attached-file context
MAX_ATTACHED_CHUNKS = 12
RECENT_CHAT_LIMIT = 12
WEB_RESULTS = 5             # DuckDuckGo hits pulled on the final fallback
REFUSAL = ("I couldn't find a reliable source for this in your attached manual, the "
           "built-in guides, or a web search. Rather than guess at settings you'd act "
           "on, I'll say so. Try attaching your camera's manual.")


# ── Pipeline ─────────────────────────────────────────────────
class AgentState(TypedDict):
    user_input: str
    attached_context: str
    context: str
    source: str          # "attached" | "retrieved" | "web" | "none"
    stages: list         # sources still to try, in order
    stage: int           # index of the next source to try
    approved: bool
    verdict: str
    attempts: list       # [(source, verdict), …] across the whole ladder
    analysis_1: str
    analysis_2: str
    final_response: str


def web_search(query: str) -> str:
    """DuckDuckGo via ddgs — no API key, no account."""
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=WEB_RESULTS)
    except Exception as exc:                       # offline, rate-limited, blocked
        return f"__SEARCH_FAILED__ {exc}"
    blocks = []
    for r in results:
        title = (r.get("title") or "").strip()[:120]
        blocks.append(f"[web] {title}\n{r.get('href', '')}\n{(r.get('body') or '').strip()}")
    return "\n\n".join(blocks)


@st.cache_resource(show_spinner="Loading the embedding model")
def get_embeddings():
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


@st.cache_resource(show_spinner=False)
def get_vector_store():
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=PERSIST_DIR,
    )


@st.cache_resource(show_spinner=False)
def get_graph():
    store = get_vector_store()
    llm = ChatGroq(model=MODEL_NAME, api_key=os.getenv("GROQ_API_KEY"),
                   temperature=TEMPERATURE)

    def gather_context(state: AgentState) -> AgentState:
        """Load the next source on the ladder: attached → archive → web."""
        stages, idx = state["stages"], state["stage"]
        if idx >= len(stages):
            state["source"], state["context"] = "none", ""
            return state

        src = stages[idx]
        state["stage"] = idx + 1
        state["source"] = src

        if src == "attached":
            state["context"] = (state.get("attached_context") or "").strip()

        elif src == "retrieved":
            # Chroma's relevance score can fall below 0 for unrelated text, which
            # is exactly the signal we want — silence its range warning.
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Relevance scores must be")
                hits = store.similarity_search_with_relevance_scores(
                    state["user_input"], k=TOP_K, filter={"type": "ingested_document"}
                )
            kept = [(d, s) for d, s in hits if s is not None and s >= RELEVANCE_FLOOR]
            state["context"] = "\n\n".join(
                f"[relevance {s:.2f}]\n{d.page_content}" for d, s in kept
            )

        else:  # web
            state["context"] = web_search(state["user_input"])

        return state

    def supervisor(state: AgentState) -> AgentState:
        """Grade the current source. Every source is graded, attachments included."""
        context, src = state["context"], state["source"]
        attempts = list(state.get("attempts") or [])

        if not context.strip():
            state["approved"] = False
            state["verdict"] = {
                "attached": "The attached files yielded no usable text.",
                "retrieved": "Nothing in the archive scored above the relevance floor.",
                "web": "The web search returned nothing.",
                "none": "No sources left to try.",
            }.get(src, "No context available.")
        elif context.startswith("__SEARCH_FAILED__"):
            state["approved"] = False
            state["verdict"] = f"Web search unavailable: {context[18:].strip()}"
        else:
            prompt = (
                "You are a strict retrieval supervisor. Decide whether the passages "
                "below contain enough information to answer the question. Partial but "
                "genuinely on-topic material counts as sufficient; material that is "
                "merely on a related subject does not.\n\n"
                f"Question: {state['user_input']}\n\n"
                f"Passages:\n{context}\n\n"
                "Reply with exactly one line: 'YES - <reason>' or 'NO - <reason>'."
            )
            verdict = llm.invoke([HumanMessage(content=prompt)]).content.strip()
            state["verdict"] = verdict
            state["approved"] = verdict.upper().lstrip("*# ").startswith("YES")

        attempts.append((src, state["verdict"]))
        state["attempts"] = attempts
        return state

    def refuse(state: AgentState) -> AgentState:
        state["final_response"] = REFUSAL
        state["source"] = "none"
        return state

    def agent_1(state: AgentState) -> AgentState:
        prompt = (
            "You are a helpful Cameramen assistant. When asked to analyze something, "
            "analyze scenic nature so that another agent could write a proper camera "
            "settings for it. Do not give the settings yourself, just analyze the scene and give the details of that scene like lighting, time of day, weather, and any other relevant information that would help another agent to write the proper camera settings for it."
            f"settings for it.\n\nReference documents:\n{state['context']}\n\n"
            f"Analyze this: {state['user_input']}"
        )
        state["analysis_1"] = llm.invoke([HumanMessage(content=prompt)]).content
        return state

    def agent_2(state: AgentState) -> AgentState:
        prompt = (
            "You are a helpful assistant. Analyze the scenic information you got from agent 1 and provide detailed camera settings for that "
            "camera brand/model.\n\n"
            f"Reference documents:\n{state['context']}\n\n"
            f"Agent 1 analysis:\n{state['analysis_1']}\n\n"
            f"Give the settings for: {state['user_input']}"
        )
        state["analysis_2"] = llm.invoke([HumanMessage(content=prompt)]).content
        return state

    def response_generator(state: AgentState) -> AgentState:
        note = {
            "attached": "The material came from files the user attached.",
            "retrieved": "The material came from the user's own ingested documents.",
            "web": ("The material came from a live web search because neither the "
                    "attached files nor the archive covered this. Say so in one short "
                    "line at the end, and cite the source URLs you relied on."),
        }.get(state["source"], "")
        prompt = (
            "You are writing for a photographer standing in front of the scene, who "
            "may only have a few seconds to read. Lead with the numbers; explain "
            "after.\n\n"
            "Format the answer in exactly this order:\n\n"
            "1. A markdown table titled '**Start here**' with two columns, Setting "
            "and Value, and one row each for: Mode, Aperture, Shutter, ISO, White "
            "balance, Focus, Metering, Drive. Give a single concrete value per row "
            "(a narrow range only where the light genuinely varies). No prose in the "
            "table.\n"
            "2. '**Then adjust**' — at most four one-line bullets, each naming the "
            "condition and the change to make, e.g. 'Darker than expected: raise ISO "
            "to 800.'\n"
            "3. '**Why these settings**' — a short paragraph, no more than four "
            "sentences, on the reasoning for this scene.\n"
            "4. '**On your camera**' — only if the reference material describes where "
            "these controls live on this specific body; two or three bullets. Omit "
            "the section entirely otherwise.\n\n"
            "Never put a caveat or a preamble before the table. Do not repeat a value "
            "in prose that already appears in the table.\n\n"
            f"Scene analysis: {state['analysis_1']}\n\n"
            f"Settings analysis: {state['analysis_2']}\n\n"
            f"{note}\n\nWrite the final answer now."
        )
        state["final_response"] = llm.invoke([HumanMessage(content=prompt)]).content
        return state

    def route_after_supervisor(state: AgentState) -> str:
        """Approved → answer. Rejected → next source. Out of sources → refuse."""
        if state["approved"]:
            return "agent_1"
        return "gather_context" if state["stage"] < len(state["stages"]) else "refuse"

    builder = StateGraph(AgentState)
    builder.add_node("gather_context", gather_context)
    builder.add_node("supervisor", supervisor)
    builder.add_node("refuse", refuse)
    builder.add_node("agent_1", agent_1)
    builder.add_node("agent_2", agent_2)
    builder.add_node("response_generator", response_generator)

    builder.add_edge(START, "gather_context")
    builder.add_edge("gather_context", "supervisor")
    builder.add_conditional_edges("supervisor", route_after_supervisor,
                                  {"agent_1": "agent_1", "refuse": "refuse",
                                   "gather_context": "gather_context"})
    builder.add_edge("refuse", END)
    builder.add_edge("agent_1", "agent_2")
    builder.add_edge("agent_2", "response_generator")
    builder.add_edge("response_generator", END)
    return builder.compile()


# ── Attached files → session context ─────────────────────────
@st.cache_data(show_spinner=False)
def extract_chunks(file_bytes: bytes, filename: str) -> list[str]:
    """Parse an uploaded file into text chunks. Cached on content + name."""
    suffix = os.path.splitext(filename)[1] or ".txt"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        path = tmp.name
    try:
        docs = load_file(path)
    finally:
        os.unlink(path)
    if not docs:
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    return [c.page_content for c in splitter.split_documents(docs)]


def build_attached_context(files, question: str) -> str:
    """Rank the attached files' chunks against the question, within a budget.

    Session-scoped: nothing here is written to the persistent vector store.
    """
    chunks, labels = [], []
    for up in files:
        for text in extract_chunks(up.getvalue(), up.name):
            chunks.append(text)
            labels.append(up.name)
    if not chunks:
        return ""

    joined = "\n\n".join(f"[{lab}]\n{c}" for lab, c in zip(labels, chunks))
    if len(joined) <= MAX_CONTEXT_CHARS:
        return joined

    emb = get_embeddings()
    doc_vecs = np.array(emb.embed_documents(chunks), dtype=np.float32)
    q_vec = np.array(emb.embed_query(question), dtype=np.float32)
    doc_vecs /= np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-9
    q_vec /= np.linalg.norm(q_vec) + 1e-9
    order = np.argsort(-(doc_vecs @ q_vec))[:MAX_ATTACHED_CHUNKS]

    picked, used = [], 0
    for i in order:
        block = f"[{labels[i]}]\n{chunks[i]}"
        if used + len(block) > MAX_CONTEXT_CHARS:
            break
        picked.append(block)
        used += len(block)
    return "\n\n".join(picked)


# ── Chat sessions ────────────────────────────────────────────
def new_chat() -> str:
    cid = uuid.uuid4().hex[:8]
    st.session_state.chats[cid] = {"title": "New conversation", "history": [],
                                   "created": time.time()}
    st.session_state.current = cid
    store.ensure_conversation(cid, title="New conversation", app="streamlit",
                              environment=ENVIRONMENT, user_id=session_user_id())
    return cid


def session_user_id() -> str:
    """A stable anonymous id per browser session, to group one user's chats."""
    if "user_id" not in st.session_state:
        st.session_state.user_id = f"anon-{uuid.uuid4().hex[:12]}"
    return st.session_state.user_id


def current_chat() -> dict:
    if not st.session_state.chats or st.session_state.current not in st.session_state.chats:
        new_chat()
    return st.session_state.chats[st.session_state.current]


if "chats" not in st.session_state:
    st.session_state.chats = {}
    st.session_state.current = None
    new_chat()


# ── Sidebar: context files + recent chats ────────────────────
with st.sidebar:
    st.markdown("### Camera manual")
    st.caption("Used for this session only. Never stored.")
    attachments = st.file_uploader(
        "Attach your camera manual",
        type=["pdf", "docx", "doc", "csv", "html", "htm", "txt", "md", "json", "py"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    if attachments:
        st.caption(f"{len(attachments)} attached. Answered from these first.")
    else:
        st.caption("Using built-in guides and the web.")

    st.divider()
    st.markdown("### Conversations")
    if st.button("New conversation", use_container_width=True):
        new_chat()
        st.rerun()

    recent = sorted(st.session_state.chats.items(),
                    key=lambda kv: kv[1]["created"], reverse=True)[:RECENT_CHAT_LIMIT]
    for cid, chat in recent:
        marker = "›" if cid == st.session_state.current else " "
        if st.button(f"{marker} {chat['title'][:34]}", key=f"chat-{cid}",
                     type="tertiary", use_container_width=True):
            st.session_state.current = cid
            st.rerun()

    st.divider()
    st.markdown("### Recording")
    counts = store.stats()
    st.caption(f"{counts['turns']} turns across {counts['conversations']} "
               f"conversations · env `{ENVIRONMENT}`")
    st.caption(store.storage_notice())
    if not store.is_durable() and ENVIRONMENT != "local":
        st.warning("Transcripts are on ephemeral storage. Set DATABASE_URL to keep them.",
                   icon="⚠️")
    st.caption("LangSmith tracing: "
               + (f"on → project `{obs.project_name()}`" if obs.is_enabled() else "off"))


# ── Main ─────────────────────────────────────────────────────
ui.masthead()

if not os.getenv("GROQ_API_KEY"):
    st.error("No GROQ_API_KEY found. Add it to your `.env` before asking anything.")
    st.stop()

chat = current_chat()

if not chat["history"]:
    ui.example_card()

SOURCE_BADGE = {
    "attached": "Your attached manual",
    "retrieved": "Built-in guides",
    "web": "Web search",
    "none": "No reliable source",
}

SOURCE_STEP = {
    "attached": "your attached manual",
    "retrieved": "the built-in guides",
    "web": "a web search",
    "none": "the remaining sources",
}


def feedback_controls(turn: dict, index: int) -> None:
    """Thumbs up/down — stored with the transcript and sent to LangSmith."""
    message_id = turn.get("message_id")
    if not message_id:
        return
    key = f"rated-{message_id}"
    if st.session_state.get(key):
        ui.caption(f"Thanks — logged as {st.session_state[key]}.")
        return
    up, down, _ = st.columns([1, 1, 8])
    for col, label, rating, score in ((up, "Helpful", "up", 1.0),
                                      (down, "Not helpful", "down", 0.0)):
        if col.button(label, key=f"fb-{rating}-{message_id}-{index}", type="tertiary"):
            store.record_feedback(message_id, rating)
            if turn.get("run_id"):
                obs.record_feedback(turn["run_id"], "user_rating", score)
            st.session_state[key] = rating
            st.rerun()


for index, turn in enumerate(chat["history"]):
    with st.chat_message("user", avatar=ui.USER_AVATAR):
        st.markdown(turn["question"])
    with st.chat_message("assistant", avatar=ui.BOT_AVATAR):
        ui.badge(SOURCE_BADGE.get(turn["source"], turn["source"]))
        if turn.get("steps"):
            ui.render_trace(turn["steps"])
        st.markdown(turn["answer"])
        # caption() renders raw HTML, so the trace link has to be an anchor tag.
        trace_link = (f' · <a href="{turn["run_url"]}" target="_blank">view trace</a>'
                      if turn.get("run_url") else "")
        ui.caption(f"Answered in {turn['elapsed']:.1f}s{trace_link}")
        feedback_controls(turn, index)

prompt = st.chat_input("Describe your scene and camera")
if prompt:
    with st.chat_message("user", avatar=ui.USER_AVATAR):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar=ui.BOT_AVATAR):
        started = time.time()
        with st.spinner("Reading your manual"):
            attached_context = build_attached_context(attachments, prompt) if attachments else ""

        # The ladder: attached files first (when present), then archive, then web.
        stages = (["attached"] if attached_context else []) + ["retrieved", "web"]
        state = {"user_input": prompt, "attached_context": attached_context,
                 "context": "", "source": "", "stages": stages, "stage": 0,
                 "approved": False, "verdict": "", "attempts": [],
                 "analysis_1": "", "analysis_2": "", "final_response": ""}

        steps, answer, source = [], "", ""
        badge_box = st.container()
        trace_box = st.container()
        turn_index = len(chat["history"])
        config = obs.run_config(
            conversation_id=st.session_state.current,
            turn_index=turn_index,
            user_id=session_user_id(),
            extra_metadata={"model": MODEL_NAME, "attached_files": len(attachments or []),
                            "stages": stages},
        )
        with st.status("Finding a reliable source", expanded=False) as status, \
                obs.traced_run() as run:
            for update in get_graph().stream(state, stream_mode="updates", config=config):
                for node, payload in update.items():
                    if node == "gather_context":
                        source = payload.get("source", "")
                        status.update(label=f"Looking in {SOURCE_STEP.get(source, source)}")
                        body = (f"**Source:** {SOURCE_BADGE.get(source, source)}\n\n"
                                + (payload.get("context") or "_No material found._"))
                    elif node == "supervisor":
                        ok = payload.get("approved")
                        status.update(
                            label=f"Checking {SOURCE_STEP.get(source, source)}: "
                                  + ("usable" if ok else "not enough, trying the next source")
                        )
                        body = (f"**Verdict:** {payload.get('verdict', '')}\n\n"
                                f"**Approved:** {ok}")
                    else:
                        status.update(label=ui.step_status_label(node))
                        body = (payload.get("final_response")
                                or payload.get("analysis_2")
                                or payload.get("analysis_1") or "")
                    steps.append((node, body))
                    if payload.get("final_response"):
                        answer = payload["final_response"]
                        source = payload.get("source", source)
            status.update(label="Done.", state="complete")
        elapsed = time.time() - started

        with badge_box:
            ui.badge(SOURCE_BADGE.get(source, source))
        with trace_box:
            ui.render_trace(steps)
        st.markdown(answer)
        ui.caption(f"Answered in {elapsed:.1f}s")

    if chat["title"] == "New conversation":
        chat["title"] = prompt[:40]

    # Recorded on every turn, in every environment — this is the training corpus.
    message_id = store.record_turn(
        st.session_state.current,
        turn_index=turn_index,
        question=prompt,
        answer=answer,
        source=source,
        model=MODEL_NAME,
        elapsed_seconds=elapsed,
        steps=steps,
        environment=ENVIRONMENT,
        title=chat["title"],
        app="streamlit",
        user_id=session_user_id(),
        meta={"attached_files": [f.name for f in (attachments or [])],
              "stages": stages, "temperature": TEMPERATURE},
        **run.as_dict(),
    )

    chat["history"].append({"question": prompt, "answer": answer, "steps": steps,
                            "source": source, "elapsed": elapsed,
                            "message_id": message_id, "run_id": run.run_id,
                            "run_url": run.run_url})
    st.rerun()
