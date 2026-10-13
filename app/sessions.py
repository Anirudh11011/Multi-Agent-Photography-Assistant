"""Chat sessions, held in st.session_state and mirrored to the transcript store."""

import time
import uuid

import streamlit as st

from app import conversation_store as store
from app import observability as obs
from app.settings import HISTORY_TURNS, HISTORY_ANSWER_CHARS


def init() -> None:
    """Open a first conversation for a new browser session. A no-op on reruns."""
    if "chats" not in st.session_state:
        st.session_state.chats = {}
        st.session_state.current = None
        new_chat()


def new_chat() -> str:
    cid = uuid.uuid4().hex[:8]
    st.session_state.chats[cid] = {"title": "New conversation", "history": [],
                                   "created": time.time()}
    st.session_state.current = cid
    store.ensure_conversation(cid, title="New conversation", app="streamlit",
                              environment=obs.environment(), user_id=session_user_id())
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


def format_history(turns: list) -> str:
    """The last few turns as plain text, for follow-ups like "what about at night?"."""
    lines = []
    for turn in turns[-HISTORY_TURNS:]:
        answer = turn["answer"]
        if len(answer) > HISTORY_ANSWER_CHARS:
            answer = answer[:HISTORY_ANSWER_CHARS].rstrip() + " …"
        lines.append(f"User: {turn['question']}\nShutterAide: {answer}")
    return "\n\n".join(lines)
