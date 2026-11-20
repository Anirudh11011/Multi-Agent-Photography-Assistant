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

A conversation with a photo attached skips the ladder entirely. The router
decides whether the user is asking about the photo or wants it edited:

    image_router ─ask→  image_agent (vision model answers about the photo) → validate
                 └edit→ image_analyst (Agent 1, vision: writes the edit plan)
                           → image_editor (Agent 2: calls the MCP editing tools)
                           → validate

The Auto-improve button enters the edit branch directly (mode "auto_edit"), and
the analyst then decides every edit itself.

Nothing here touches Streamlit; resources.py holds the cached, compiled graph.
"""

import os
import warnings
from typing import TypedDict

from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END

from app import image_editing as editing
from app import prompts as P
from app.guardrails import check_format, redact_secrets, strip_invented_urls
from app.settings import (
    MODEL_NAME, SUPERVISOR_MODEL, TEMPERATURE, TOP_K, RELEVANCE_FLOOR,
    WEB_RESULTS, REFUSAL, VISION_MODEL, VISION_TEMPERATURE,
    EDITOR_MODEL, EDIT_MAX_STEPS, IMAGE_MAX_EDGE, IMAGE_JPEG_QUALITY,
)

VISION_NOT_CONFIGURED = (
    "Image analysis isn't set up yet: no vision model is configured. Set "
    "`VISION_MODEL` in `app/settings.py` to a model that accepts images."
)


class AgentState(TypedDict):
    user_input: str      # the message exactly as typed
    history: str         # recent turns, formatted by format_history()
    kind: str            # "settings" | "question" | "smalltalk" | "outside"
    question: str        # user_input made standalone by triage; used for search
    attached_context: str
    image_url: str       # data: URL of the attached photo; "" when there is none
    image_exif: str      # shooting settings read from the photo's EXIF, or ""
    context: str
    source: str          # "attached" | "retrieved" | "web" | "image" | "none"
    stages: list         # sources still to try, in order
    stage: int           # index of the next source to try
    approved: bool
    verdict: str
    attempts: list       # [(source, verdict), …] across the whole ladder
    analysis_1: str
    final_response: str
    validation: list      # findings from the validate node, shown in the trace
    # Photo editing. edit_dir/edit_source_id name the working image the next edit
    # starts from (the latest edited version); both "" when editing is unavailable.
    mode: str             # "" (typed message) | "auto_edit" (Auto-improve button)
    edit_dir: str
    edit_source_id: str
    image_intent: str     # "ask" | "edit", set by image_router
    edit_plan: str        # Agent 1's plan, handed to Agent 2
    edited_image_id: str  # the result; "" when nothing was changed
    edit_log: list        # Agent 2's tool calls, for the trace


def initial_state(user_input: str, history: str, attached_context: str,
                  image_url: str = "", image_exif: str = "", *, mode: str = "",
                  edit_dir: str = "", edit_source_id: str = "") -> AgentState:
    """A fresh state for one turn, with the ladder this turn will climb."""
    # The ladder: attached files first (when present), then archive, then web.
    # An image turn never climbs it; the stages are kept for the trace metadata.
    stages = (["image"] if image_url else
              (["attached"] if attached_context else []) + ["retrieved", "web"])
    return {"user_input": user_input, "history": history,
            "kind": "", "question": user_input,
            "attached_context": attached_context,
            "image_url": image_url, "image_exif": image_exif,
            "context": "", "source": "", "stages": stages, "stage": 0,
            "approved": False, "verdict": "", "attempts": [],
            "analysis_1": "", "final_response": "", "validation": [],
            "mode": mode, "edit_dir": edit_dir, "edit_source_id": edit_source_id,
            "image_intent": "", "edit_plan": "", "edited_image_id": "",
            "edit_log": []}


def edit_answer(plan: dict, result: "editing.EditResult | None") -> str:
    """What the user reads after an edit, built from what was actually applied."""
    if result is not None and result.error:
        return ("I couldn't edit the photo this time: the editing tools failed "
                f"(`{result.error[:200]}`). Your photo is unchanged.")
    parts = []
    if plan.get("summary"):
        parts.append(plan["summary"])
    edits = result.edits if result else []
    if edits:
        parts.append("**Edits applied**\n" + "\n".join(f"- {e}" for e in edits))
    else:
        parts.append("No edits were applied, so your photo is unchanged.")
    if plan.get("cannot"):
        parts.append(f"**Not possible with the editing tools:** {plan['cannot']}")
    if result and result.notes:
        parts.append(f"_Editor note: {result.notes}_")
    return "\n\n".join(parts)


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

    # Built only when the placeholder has been replaced, so a missing model name
    # shows up as a clear message on an image turn instead of an API error.
    vision_llm = (None if VISION_MODEL.startswith("REPLACE_") else
                  ChatGroq(model=VISION_MODEL, api_key=os.getenv("GROQ_API_KEY"),
                           temperature=VISION_TEMPERATURE))
    # Agent 2 only maps a written plan onto tool calls: temperature 0.
    editor_llm = ChatGroq(model=EDITOR_MODEL, api_key=os.getenv("GROQ_API_KEY"),
                          temperature=0)

    def image_router(state: AgentState) -> AgentState:
        """Ask about the photo, or edit it? The Auto-improve button is always an edit."""
        if state.get("mode") == "auto_edit":
            state["image_intent"] = "edit"
        elif not state.get("edit_source_id"):
            state["image_intent"] = "ask"            # no working copy: cannot edit
        else:
            reply = grader_llm.invoke(P.image_router_messages(
                state["user_input"], state.get("history") or "")).content
            state["image_intent"] = P.parse_image_route(reply)
        return state

    def image_analyst(state: AgentState) -> AgentState:
        """Agent 1: look at the current version of the photo and write the edit plan."""
        state["kind"], state["source"] = "edit", "edit"
        if vision_llm is None:
            state["final_response"] = VISION_NOT_CONFIGURED
            return state
        folder, image_id = state["edit_dir"], state["edit_source_id"]
        try:
            tools = editing.tool_catalog()
        except Exception as exc:
            state["final_response"] = edit_answer({}, editing.EditResult(
                image_id=image_id, error=f"{type(exc).__name__}: {exc}"))
            return state
        state["edit_plan"] = vision_llm.invoke(P.edit_plan_messages(
            mode="auto" if state.get("mode") == "auto_edit" else "requested",
            message=state["user_input"], history=state.get("history") or "",
            image_url=editing.data_url(folder, image_id, IMAGE_MAX_EDGE,
                                       IMAGE_JPEG_QUALITY),
            exif=state.get("image_exif") or "",
            stats=editing.measure(folder, image_id), tools=tools,
        )).content
        plan = P.parse_edit_plan(state["edit_plan"])
        if not plan["has_edits"]:
            # Nothing to do (or nothing possible): answer now, skip the editor.
            state["final_response"] = edit_answer(plan, None)
        return state

    def image_editor(state: AgentState) -> AgentState:
        """Agent 2: carry out the plan with the MCP editing tools."""
        result = editing.run_editor(editor_llm, state["edit_plan"], state["edit_dir"],
                                    state["edit_source_id"], EDIT_MAX_STEPS)
        if result.image_id != state["edit_source_id"]:
            state["edited_image_id"] = result.image_id
        state["edit_log"] = result.calls or ([result.error] if result.error else [])
        state["final_response"] = edit_answer(P.parse_edit_plan(state["edit_plan"]),
                                              result)
        return state

    def image_agent(state: AgentState) -> AgentState:
        """The vision model looks at the attached photo and writes the answer."""
        state["kind"], state["source"] = "image", "image"
        # The user's documents, if any, ground camera-specific control names, and
        # validate() checks links in the answer against them.
        state["context"] = (state.get("attached_context") or "").strip()
        if vision_llm is None:
            state["final_response"] = VISION_NOT_CONFIGURED
            return state
        state["final_response"] = vision_llm.invoke(P.image_messages(
            message=state["user_input"], history=state.get("history") or "",
            image_url=state["image_url"], exif=state.get("image_exif") or "",
            context=state["context"],
        )).content
        return state

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

    def route_start(state: AgentState) -> str:
        """Only a turn with a photo attached goes down the image branch."""
        return "image_router" if state.get("image_url") else "triage"

    def route_after_image_router(state: AgentState) -> str:
        return "image_analyst" if state["image_intent"] == "edit" else "image_agent"

    def route_after_analyst(state: AgentState) -> str:
        """A plan with edits goes to the editor; no plan (or an error) is answered now."""
        return "validate" if state.get("final_response") else "image_editor"

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
    builder.add_node("image_agent", image_agent)
    builder.add_node("image_router", image_router)
    builder.add_node("image_analyst", image_analyst)
    builder.add_node("image_editor", image_editor)

    builder.add_conditional_edges(START, route_start,
                                  {"image_router": "image_router", "triage": "triage"})
    builder.add_conditional_edges("image_router", route_after_image_router,
                                  {"image_analyst": "image_analyst",
                                   "image_agent": "image_agent"})
    builder.add_conditional_edges("image_analyst", route_after_analyst,
                                  {"image_editor": "image_editor",
                                   "validate": "validate"})
    builder.add_edge("image_editor", "validate")
    builder.add_edge("image_agent", "validate")
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
