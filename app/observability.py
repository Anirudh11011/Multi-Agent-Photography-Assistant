"""LangSmith tracing for the multi-agent assistant.

Every LLM call, graph node and retrieval already runs through LangChain, so
tracing is a matter of setting the right environment variables before the first
chain is built. This module does that from either `.env` or Streamlit secrets,
and hands back the small helpers the app needs on top:

    configure_langsmith()   once, at import time of the app
    run_config(...)         per turn — tags, metadata and the thread id that
                            groups a conversation into one LangSmith thread
    traced_run()            context manager that captures the run id/url so the
                            trace can be linked from the conversation database

Tracing is optional: with no API key the helpers turn into no-ops and the app
behaves exactly as it did before.
"""

from __future__ import annotations

import os
import contextlib
import logging
from typing import Any, Iterator

log = logging.getLogger(__name__)

DEFAULT_PROJECT = "multi-agent-photography-assistant"
DEFAULT_ENDPOINT = "https://api.smith.langchain.com"

_state: dict[str, Any] = {"configured": False, "enabled": False, "project": DEFAULT_PROJECT}


def _secret(name: str) -> str | None:
    """Read a setting from the environment, falling back to Streamlit secrets.

    Streamlit Cloud has no `.env`; secrets are the deploy-mode equivalent.
    """
    value = os.getenv(name)
    if value:
        return value.strip().strip('"').strip("'")
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:  # not running under Streamlit, or no secrets file
        pass
    return None


def configure_langsmith() -> bool:
    """Set up LangSmith tracing. Idempotent; returns True when tracing is on."""
    if _state["configured"]:
        return _state["enabled"]
    _state["configured"] = True

    # LANGCHAIN_* are the older names for the same settings; accept both.
    api_key = _secret("LANGSMITH_API_KEY") or _secret("LANGCHAIN_API_KEY")
    if not api_key:
        log.info("LANGSMITH_API_KEY not set — tracing disabled.")
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return False

    project = _secret("LANGSMITH_PROJECT") or _secret("LANGCHAIN_PROJECT") or DEFAULT_PROJECT
    endpoint = _secret("LANGSMITH_ENDPOINT") or _secret("LANGCHAIN_ENDPOINT") or DEFAULT_ENDPOINT

    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = project
    os.environ["LANGSMITH_ENDPOINT"] = endpoint
    os.environ["LANGSMITH_TRACING"] = "true"
    # Mirror onto the legacy names so any library still reading them agrees.
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = project
    os.environ["LANGCHAIN_ENDPOINT"] = endpoint
    os.environ["LANGCHAIN_TRACING_V2"] = "true"

    _state["enabled"] = True
    _state["project"] = project
    log.info("LangSmith tracing enabled (project=%s).", project)
    return True


def is_enabled() -> bool:
    return bool(_state["enabled"])


def project_name() -> str:
    return str(_state["project"])


def environment() -> str:
    """Deployment label attached to every trace and every stored conversation."""
    env = _secret("APP_ENV")
    if env:
        return env
    # Streamlit Community Cloud sets this on every deployed app.
    if os.getenv("STREAMLIT_RUNTIME_ENV") or os.getenv("HOSTNAME", "").startswith("streamlit"):
        return "deploy"
    return "local"


def run_config(
    *,
    conversation_id: str,
    turn_index: int,
    run_name: str = "photography_assistant_turn",
    user_id: str | None = None,
    extra_metadata: dict | None = None,
    extra_tags: list[str] | None = None,
) -> dict:
    """Config for `graph.invoke`/`graph.stream`.

    `thread_id` is what LangSmith uses to group runs into a conversation, so it
    carries the same id the database uses for the conversation row. The config
    is returned whether or not tracing is on — LangGraph accepts it either way.
    """
    metadata = {
        "conversation_id": conversation_id,
        # LangSmith reads any of these three as the thread key.
        "thread_id": conversation_id,
        "session_id": conversation_id,
        "conversation_turn": turn_index,
        "environment": environment(),
        "app": "photography-assistant",
    }
    if user_id:
        metadata["user_id"] = user_id
    if extra_metadata:
        metadata.update(extra_metadata)

    tags = ["photography-assistant", environment()]
    if extra_tags:
        tags.extend(extra_tags)

    return {
        "run_name": run_name,
        "metadata": metadata,
        "tags": tags,
        "configurable": {"thread_id": conversation_id},
    }


class RunHandle:
    """Filled in with the LangSmith run id/url once the traced block exits."""

    def __init__(self) -> None:
        self.run_id: str | None = None
        self.run_url: str | None = None

    def as_dict(self) -> dict:
        return {"langsmith_run_id": self.run_id, "langsmith_run_url": self.run_url}


@contextlib.contextmanager
def traced_run() -> Iterator[RunHandle]:
    """Run a block and capture the root LangSmith run it produced.

    A no-op passthrough when tracing is off, so callers need no branching.
    """
    handle = RunHandle()
    if not is_enabled():
        yield handle
        return

    try:
        from langchain_core.tracers.context import collect_runs
    except Exception:  # pragma: no cover - very old langchain-core
        yield handle
        return

    with collect_runs() as cb:
        yield handle

    try:
        root = cb.traced_runs[0] if cb.traced_runs else None
        if root is not None:
            handle.run_id = str(root.id)
            handle.run_url = _run_url(root)
    except Exception as exc:  # tracing must never break a reply
        log.warning("Could not capture LangSmith run: %s", exc)


def _run_url(run) -> str | None:
    try:
        from langsmith import Client

        return Client().get_run_url(run=run, project_name=project_name())
    except Exception:
        return None


def record_feedback(run_id: str, key: str, score: float, comment: str | None = None) -> bool:
    """Attach user feedback (thumbs up/down) to a traced run. Best effort."""
    if not is_enabled() or not run_id:
        return False
    try:
        from langsmith import Client

        Client().create_feedback(run_id, key=key, score=score, comment=comment)
        return True
    except Exception as exc:
        log.warning("Could not send LangSmith feedback: %s", exc)
        return False
