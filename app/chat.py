"""The conversation pane: past turns, and answering a new one."""

import time

import streamlit as st

from app import theme as ui
from app import conversation_store as store
from app import observability as obs
from app import prompts as P
from app.attachments import build_attached_context
from app.pipeline import initial_state
from app.resources import get_graph
from app.sessions import format_history, session_user_id
from app.settings import MODEL_NAME, TEMPERATURE

SOURCE_BADGE = {
    "attached": "Your attached manual",
    "retrieved": "Built-in guides",
    "web": "Web search",
    "none": "No reliable source",
    "outside": "Outside photography",
    "smalltalk": "No sources needed",
}

SOURCE_STEP = {
    "attached": "your attached manual",
    "retrieved": "the built-in guides",
    "web": "a web search",
    "none": "the remaining sources",
    "outside": "nothing — not a photography question",
    "smalltalk": "nothing — no question asked",
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
    with st.container(key=f"feedback-{message_id}-{index}", horizontal=True):
        for label, icon, rating, score in (
                ("Helpful", ":material/thumb_up:", "up", 1.0),
                ("Not helpful", ":material/thumb_down:", "down", 0.0)):
            if st.button(label, key=f"fb-{rating}-{message_id}-{index}", icon=icon,
                         type="tertiary"):
                store.record_feedback(message_id, rating)
                if turn.get("run_id"):
                    obs.record_feedback(turn["run_id"], "user_rating", score)
                st.session_state[key] = rating
                st.rerun()


def render_history(chat: dict) -> None:
    for index, turn in enumerate(chat["history"]):
        with ui.user_message():
            st.markdown(turn["question"])
        with ui.assistant_message():
            ui.badge(SOURCE_BADGE.get(turn["source"], turn["source"]))
            if turn.get("steps"):
                ui.render_trace(turn["steps"])
            st.markdown(turn["answer"])
            # caption() renders raw HTML, so the trace link has to be an anchor tag.
            trace_link = (f' · <a href="{turn["run_url"]}" target="_blank">view trace</a>'
                          if turn.get("run_url") else "")
            ui.caption(f"Answered in {turn['elapsed']:.1f}s{trace_link}")
            feedback_controls(turn, index)


def _step_body(node: str, payload: dict, source: str, status) -> str:
    """Update the status line for one graph step and return its trace entry."""
    if node == "triage":
        status.update(label=ui.step_status_label(node))
        return (f"**Request:** {payload.get('kind', '')}\n\n"
                f"**Standalone question:** {payload.get('question', '')}")
    if node == "gather_context":
        status.update(label=f"Looking in {SOURCE_STEP.get(source, source)}")
        return (f"**Source:** {SOURCE_BADGE.get(source, source)}\n\n"
                + (payload.get("context") or "_No material found._"))
    if node == "supervisor":
        ok = payload.get("approved")
        status.update(
            label=f"Checking {SOURCE_STEP.get(source, source)}: "
                  + ("usable" if ok else "not enough, trying the next source")
        )
        return (f"**Verdict:** {payload.get('verdict', '')}\n\n"
                f"**Approved:** {ok}")
    if node == "validate":
        checks = payload.get("validation") or []
        status.update(label=ui.step_status_label(node))
        return ("**Checks:**\n\n"
                + ("\n".join(f"- {c}" for c in checks) if checks
                   else "- Format, links and credentials all clean."))
    status.update(label=ui.step_status_label(node))
    return payload.get("final_response") or payload.get("analysis_1") or ""


def answer_turn(chat: dict, prompt: str, attachments, shown_cameras: list) -> None:
    """Run the pipeline for one question, render it live, and record the turn."""
    environment = obs.environment()

    with ui.user_message():
        st.markdown(prompt)

    with ui.assistant_message():
        started = time.time()
        with st.spinner("Reading your manual"):
            attached_context = build_attached_context(attachments, prompt) if attachments else ""

        state = initial_state(prompt, format_history(chat["history"]), attached_context)
        stages = state["stages"]

        steps, answer, source, kind = [], "", "", ""
        badge_box = st.container()
        trace_box = st.container()
        turn_index = len(chat["history"])
        config = obs.run_config(
            conversation_id=st.session_state.current,
            turn_index=turn_index,
            user_id=session_user_id(),
            extra_metadata={"model": MODEL_NAME, "attached_files": len(attachments or []),
                            "stages": stages, "prompt_version": P.PROMPT_VERSION},
        )
        with st.status("Finding a reliable source", expanded=False) as status, \
                obs.traced_run() as run:
            for update in get_graph().stream(state, stream_mode="updates", config=config):
                for node, payload in update.items():
                    if node == "triage":
                        kind = payload.get("kind", "")
                    elif node == "gather_context":
                        source = payload.get("source", "")
                    steps.append((node, _step_body(node, payload, source, status)))
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
        environment=environment,
        title=chat["title"],
        app="streamlit",
        user_id=session_user_id(),
        meta={"attached_files": [f.name for f in (attachments or [])],
              "stages": stages, "temperature": TEMPERATURE,
              "prompt_version": P.PROMPT_VERSION, "request_kind": kind},
        **run.as_dict(),
    )

    chat["history"].append({"question": prompt, "answer": answer, "steps": steps,
                            "source": source, "elapsed": elapsed,
                            "message_id": message_id, "run_id": run.run_id,
                            "run_url": run.run_url, "cameras": shown_cameras})
