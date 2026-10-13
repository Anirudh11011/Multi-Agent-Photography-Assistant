"""The agent pipeline — an escalation ladder, built as a LangGraph graph.

Every source is graded by the supervisor before it is used, and a failed grade
falls through to the next source:

    triage ─smalltalk | outside→ direct reply, no search
      ↓ settings | question
    attached files  →  supervisor  ─approved→  agent_1 → agent_2 → validate
          ↓ rejected
    archive search  →  supervisor  ─approved→  agent_1 → agent_2 → validate
          ↓ rejected
    web search      →  supervisor  ─approved→  agent_1 → agent_2 → validate
          ↓ rejected
    "I don't have relevant information"

Nothing here touches Streamlit; resources.py holds the cached, compiled graph.
"""

import os
import warnings
from typing import TypedDict

from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END

from app import prompts as P
from app.guardrails import check_format, redact_secrets, strip_invented_urls
from app.settings import (
    MODEL_NAME, SUPERVISOR_MODEL, TEMPERATURE, TOP_K, RELEVANCE_FLOOR,
    WEB_RESULTS, REFUSAL,
)


class AgentState(TypedDict):
    user_input: str      # the message exactly as typed
    history: str         # recent turns, formatted by format_history()
    kind: str            # "settings" | "question" | "smalltalk" | "outside"
    question: str        # user_input made standalone by triage; used for search
    attached_context: str
    context: str
    source: str          # "attached" | "retrieved" | "web" | "none"
    stages: list         # sources still to try, in order
    stage: int           # index of the next source to try
    approved: bool
    verdict: str
    attempts: list       # [(source, verdict), …] across the whole ladder
    analysis_1: str
    final_response: str
    validation: list      # findings from the validate node, shown in the trace


def initial_state(user_input: str, history: str, attached_context: str) -> AgentState:
    """A fresh state for one turn, with the ladder this turn will climb."""
    # The ladder: attached files first (when present), then archive, then web.
    stages = (["attached"] if attached_context else []) + ["retrieved", "web"]
    return {"user_input": user_input, "history": history,
            "kind": "", "question": user_input,
            "attached_context": attached_context,
            "context": "", "source": "", "stages": stages, "stage": 0,
            "approved": False, "verdict": "", "attempts": [],
            "analysis_1": "", "final_response": "", "validation": []}


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
        blocks.append(f"[web result: {title}]\n{r.get('href', '')}\n"
                      f"{(r.get('body') or '').strip()}")
    return "\n\n".join(blocks)


def build_graph(vector_store):
    """Compile the ladder over the given vector store."""
    llm = ChatGroq(model=MODEL_NAME, api_key=os.getenv("GROQ_API_KEY"),
                   temperature=TEMPERATURE)
    # No max_tokens: the cap counts this model's reasoning tokens, and a verdict
    # truncated to an empty string reads as a rejection. The prompt bounds the
    # visible output to one line, which is bound enough.
    grader_llm = ChatGroq(model=SUPERVISOR_MODEL, api_key=os.getenv("GROQ_API_KEY"),
                          temperature=0)

    def triage(state: AgentState) -> AgentState:
        """Classify the request and make it standalone, before any source is searched."""
        reply = grader_llm.invoke(
            P.triage_messages(state["user_input"], state.get("history") or "")
        ).content.strip()
        state["kind"], state["question"] = P.parse_triage(reply, state["user_input"])
        return state

    def redirect(state: AgentState) -> AgentState:
        """Small talk or clearly not photography — reply directly, search nothing."""
        if state["kind"] == "smalltalk":
            state["final_response"], state["source"] = P.SMALLTALK_REPLY, "smalltalk"
        else:
            state["final_response"], state["source"] = P.OUTSIDE_SCOPE_REPLY, "outside"
        return state

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
                hits = vector_store.similarity_search_with_relevance_scores(
                    state["question"], k=TOP_K, filter={"type": "ingested_document"}
                )
            kept = [(d, s) for d, s in hits if s is not None and s >= RELEVANCE_FLOOR]
            state["context"] = "\n\n".join(
                f"[built-in guide · relevance {s:.2f}]\n{d.page_content}" for d, s in kept
            )

        else:  # web
            state["context"] = web_search(state["question"])

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
            verdict = grader_llm.invoke(
                P.supervisor_messages(state["question"], context)
            ).content.strip()
            # Only the first word routes; the rest is shown in the trace panel. An
            # empty reply means the token cap swallowed the line, so fall through
            # to the next source rather than silently reading it as a rejection.
            if not verdict:
                state["verdict"] = "The grader returned nothing; trying the next source."
                state["approved"] = False
            else:
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
        """Scene brief for the answer writer. Never shown to the user."""
        state["analysis_1"] = llm.invoke(
            P.scene_messages(state["question"], state["context"])
        ).content
        return state

    def agent_2(state: AgentState) -> AgentState:
        """The answer the reader sees, in the format for this kind of request."""
        state["final_response"] = llm.invoke(P.answer_messages(
            kind=state["kind"], source=state["source"], context=state["context"],
            brief=state["analysis_1"], history=state.get("history") or "",
            message=state["user_input"], question=state["question"],
        )).content
        return state

    def validate(state: AgentState) -> AgentState:
        """Deterministic guardrail on the answer — no model, no added latency.

        Credentials and invented links are repaired in place, because both are
        things the reader must never see. A format lapse is only reported: it
        cannot be fixed without another generation, and the answer is still
        useful without the missing heading.
        """
        answer = state["final_response"]
        findings: list[str] = []

        answer, secrets = redact_secrets(answer)
        if secrets:
            findings.append("redacted " + ", ".join(secrets))

        answer, invented = strip_invented_urls(answer, state.get("context") or "")
        if invented:
            findings.append(f"removed {len(invented)} fabricated link(s): "
                            + ", ".join(invented))

        # Only settings answers have a fixed template; questions are free-form.
        if state.get("kind") == "settings":
            findings.extend(check_format(answer))

        state["final_response"] = answer
        state["validation"] = findings
        return state

    def route_after_triage(state: AgentState) -> str:
        return "redirect" if state["kind"] in ("smalltalk", "outside") else "gather_context"

    def route_after_supervisor(state: AgentState) -> str:
        """Approved → answer. Rejected → next source. Out of sources → refuse."""
        if state["approved"]:
            return "agent_1"
        return "gather_context" if state["stage"] < len(state["stages"]) else "refuse"

    builder = StateGraph(AgentState)
    builder.add_node("triage", triage)
    builder.add_node("redirect", redirect)
    builder.add_node("gather_context", gather_context)
    builder.add_node("supervisor", supervisor)
    builder.add_node("refuse", refuse)
    builder.add_node("agent_1", agent_1)
    builder.add_node("agent_2", agent_2)
    builder.add_node("validate", validate)

    builder.add_edge(START, "triage")
    builder.add_conditional_edges("triage", route_after_triage,
                                  {"redirect": "redirect",
                                   "gather_context": "gather_context"})
    builder.add_edge("redirect", END)
    builder.add_edge("gather_context", "supervisor")
    builder.add_conditional_edges("supervisor", route_after_supervisor,
                                  {"agent_1": "agent_1", "refuse": "refuse",
                                   "gather_context": "gather_context"})
    builder.add_edge("refuse", END)
    builder.add_edge("agent_1", "agent_2")
    builder.add_edge("agent_2", "validate")
    builder.add_edge("validate", END)
    return builder.compile()
