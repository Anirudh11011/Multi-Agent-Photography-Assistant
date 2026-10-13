"""Sidebar: context files + recent chats."""

import streamlit as st

from app import sessions
from app.attachments import FILE_TYPES
from app.settings import RECENT_CHAT_LIMIT


def render() -> list:
    """Draw the sidebar and return the files attached for this session."""
    with st.sidebar:
        if st.button("New conversation", type="primary", icon=":material/edit_square:",
                     use_container_width=True):
            sessions.new_chat()
            st.rerun()

        st.markdown("### Camera manual")
        attachments = st.file_uploader(
            "Attach your camera manual",
            type=FILE_TYPES,
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if attachments:
            st.caption(f"{len(attachments)} attached. Answered from these first.")
        else:
            st.caption("Optional. Used for this session only, never stored.")

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
    return attachments
