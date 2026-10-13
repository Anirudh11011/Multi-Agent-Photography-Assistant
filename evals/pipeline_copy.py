"""A copy of the pipeline in app/, with the UI left out, for testing.

Everything below is copied from the app (settings.py, guardrails.py, pipeline.py, sessions.py): the fixed settings, the output
checks, the graph and format_history. The only changes are that the Streamlit
caching decorators are gone and the graph takes the vector store as an argument.
Prompts are NOT copied; they are imported from app/prompts.py, so prompt edits reach
the tests on their own.

This is a copy, so it does not follow the app. If you change the graph, a setting
or a check in app/, make the same change here, or the tests will be
measuring an older pipeline than the one users get.

Copied on 2026-10-04, at PROMPT_VERSION 2026-09-28.1.
"""

import os
import re
import warnings
from typing import TypedDict

from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END

from app import prompts as P

# ── Fixed settings ───────────────────────────────────────────
MODEL_NAME = "openai/gpt-oss-120b"
# The supervisor only emits one line of YES/NO, so it runs on a smaller model at
# temperature 0 — a routing gate should not be a sampled generation.
SUPERVISOR_MODEL = "openai/gpt-oss-20b"
# Low: the answer is numbers someone acts on, not creative writing. Prompts are
# calibrated to model + temperature — re-check answers if you change either.
TEMPERATURE = 0.3
TOP_K = 4
RELEVANCE_FLOOR = 0.25      # below this, retrieval is treated as a miss
WEB_RESULTS = 5             # DuckDuckGo hits pulled on the final fallback
HISTORY_TURNS = 3           # earlier turns shown to intake and the answer writer
HISTORY_ANSWER_CHARS = 700  # each earlier answer is trimmed to this
REFUSAL = ("I couldn't find a reliable source for this in your attached manual, the "
           "built-in guides, or a web search. Rather than guess at settings you'd act "
           "on, I'll say so. Try attaching your camera's manual.")


# ── Output checks ────────────────────────────────────────────
# All three are deterministic: regex and set membership, no model call, so the
# validate node adds no measurable latency and cannot itself hallucinate.

REQUIRED_SECTIONS = ("**Start here**", "**Then adjust**", "**Why these settings**")
REQUIRED_ROWS = ("Mode", "Aperture", "Shutter", "ISO", "White balance",
                 "Focus", "Metering", "Drive")

URL_RE = re.compile(r'https?://[^\s\)\]>"\',]+')

# Each entry redacts group 1 where the pattern isolates the value, else the whole
# match. Known key shapes only — this is a safety net, not a guarantee.
SECRET_PATTERNS = (
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), "AWS access key id"),
    (re.compile(r'\bgsk_[A-Za-z0-9]{20,}\b'), "Groq API key"),
    (re.compile(r'\bsk-[A-Za-z0-9_\-]{20,}\b'), "OpenAI-style secret key"),
    (re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b'), "GitHub token"),
    (re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{10,}\b'), "Slack token"),
    (re.compile(r'\bey[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b'), "JWT"),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'), "private key block"),
    (re.compile(r'(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*'
                r'["\']?([A-Za-z0-9_\-/+]{16,})'), "credential assignment"),
)

# A key with no recognisable prefix can only be judged on shape: a long opaque
# run mixing case and digits. Measured against every answer and context block in
# conversations.db, this matches nothing legitimate — prose and setting values
# never look like this. URLs are exempt; their path segments often do.
OPAQUE_TOKEN_RE = re.compile(
    r'(?<![/\w])(?=[A-Za-z0-9_\-]{24,}(?![A-Za-z0-9_\-]))'
    r'(?=[A-Za-z0-9_\-]*[a-z])(?=[A-Za-z0-9_\-]*[A-Z])'
    r'(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{24,}'
)


def _normalise_url(url: str) -> str:
    """Strip what varies between a link in prose and the same link in a source."""
    url = url.rstrip('.,;:)]}>"\'').rstrip('/').lower()
    return re.sub(r'^https?://(www\.)?', '', url)


def check_format(answer: str) -> list[str]:
    """The four-section contract. 'On your camera' is optional by design."""
    issues = []
    missing = [s.strip("*") for s in REQUIRED_SECTIONS if s not in answer]
    if missing:
        issues.append("missing section(s): " + ", ".join(missing))
    absent = [r for r in REQUIRED_ROWS
              if not re.search(rf'^\|\s*{re.escape(r)}\s*\|', answer, re.M | re.I)]
    if absent:
        issues.append("missing table row(s): " + ", ".join(absent))
    return issues


def strip_invented_urls(answer: str, context: str) -> tuple[str, list[str]]:
    """Remove links that never appeared in the retrieved material.

    The model is asked to cite only what it was given; anything else was
    invented, so it is cut rather than shown to someone who might click it.
    """
    allowed = {_normalise_url(u) for u in URL_RE.findall(context)}
    invented = [u for u in URL_RE.findall(answer)
                if _normalise_url(u) not in allowed]
    for url in invented:
        answer = answer.replace(url, "[source link removed — not in the retrieved material]")
    return answer, invented


def redact_secrets(answer: str) -> tuple[str, list[str]]:
    """Mask anything shaped like a credential that reached the answer."""
    found: list[str] = []

    def _mask(match: re.Match, label: str) -> str:
        found.append(label)
        if match.groups() and match.group(1):
            return match.group(0).replace(match.group(1), "[redacted]")
        return "[redacted]"

    for pattern, label in SECRET_PATTERNS:
        answer = pattern.sub(lambda m, _l=label: _mask(m, _l), answer)

    # Anything left that merely looks like a key. Match offsets are positions in
    # the string handed to sub(), so the URL spans stay valid throughout.
    url_spans = [m.span() for m in URL_RE.finditer(answer)]

    def _mask_opaque(match: re.Match) -> str:
        if any(start <= match.start() < end for start, end in url_spans):
            return match.group(0)
        found.append("opaque high-entropy token")
        return "[redacted]"

    answer = OPAQUE_TOKEN_RE.sub(_mask_opaque, answer)
    return answer, sorted(set(found))


# ── Pipeline ─────────────────────────────────────────────────
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


def build_graph(store):
    """The app's get_graph(), taking the Chroma vector store as an argument."""
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
                hits = store.similarity_search_with_relevance_scores(
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


def format_history(turns: list) -> str:
    """The last few turns as plain text, for follow-ups like "what about at night?"."""
    lines = []
    for turn in turns[-HISTORY_TURNS:]:
        answer = turn["answer"]
        if len(answer) > HISTORY_ANSWER_CHARS:
            answer = answer[:HISTORY_ANSWER_CHARS].rstrip() + " …"
        lines.append(f"User: {turn['question']}\nShutterAide: {answer}")
    return "\n\n".join(lines)
