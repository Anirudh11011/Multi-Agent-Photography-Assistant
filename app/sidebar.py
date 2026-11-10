"""Sidebar: new conversation + recent chats. Uploads live in the input bar (composer.py)."""

import streamlit as st

from app import sessions
from app.settings import RECENT_CHAT_LIMIT


def render() -> None:
    """Draw the sidebar."""
    with st.sidebar:
        if st.button("New conversation", type="primary", icon=":material/edit_square:",
                     use_container_width=True):
            sessions.new_chat()
            st.rerun()

        st.markdown("### Conversations")
        recent = sorted(st.session_state.chats.items(),
                        key=lambda kv: kv[1]["created"], reverse=True)[:RECENT_CHAT_LIMIT]
        with st.container(key="chat-list"):
            for cid, chat in recent:
                # The open conversation is the "secondary" row; the theme lights it.
                is_open = cid == st.session_state.current
                if st.button(chat["title"][:40], key=f"chat-{cid}",
                             type="secondary" if is_open else "tertiary",
                             use_container_width=True):
                    st.session_state.current = cid
                    st.rerun()
