"""Streamlit console for the multi-agent assistant.

Run with:
    streamlit run streamlit_app.py

This file only wires the page together; the work lives in the app/ package:

    app/settings.py            fixed model, retrieval and history settings
    app/prompts.py             every prompt (see Documentation/PROMPTS.md)
    app/pipeline.py            the LangGraph escalation ladder
    app/guardrails.py          deterministic checks on a finished answer
    app/loaders.py             document loaders shared with the ingestion CLI
    app/resources.py           cached embeddings, vector store and compiled graph
    app/attachments.py         uploaded files → session-only context
    app/conversation_store.py  durable transcript store
    app/observability.py       LangSmith tracing
    app/sessions.py            chat sessions held in st.session_state
    app/theme.py               all styling and layout helpers
    app/camera_images.py       camera photos for the side panel
    app/sidebar.py             new conversation, manual upload, recent chats
    app/chat.py                rendering past turns and answering a new one

Command-line tools are in scripts/; the pipeline tests are in evals/.
"""

import os

import streamlit as st
from dotenv import load_dotenv

from app import camera_images as cams
from app import conversation_store as store
from app import observability as obs
from app import theme as ui
from app import chat as chat_view, sessions, sidebar
from app.resources import log_operator_notices

load_dotenv()

# Tracing has to be configured before the first chain is constructed, and the
# transcript store before the first turn is answered.
obs.configure_langsmith()
store.get_engine()

ui.configure_page()
ui.inject_css()

sessions.init()
log_operator_notices()

attachments = sidebar.render()

# ── Main ─────────────────────────────────────────────────────
ui.masthead()

if not os.getenv("GROQ_API_KEY"):
    st.error("No GROQ_API_KEY found. Add it to your `.env` before asking anything.")
    st.stop()

chat = sessions.current_chat()
# Read before the history renders — chat_input is pinned to the bottom wherever
# it's called — so the camera panel can open while the agents are still working.
prompt = st.chat_input("Describe your scene and camera")

# This question's cameras, or the last turn's when it names none.
previous_cameras = chat["history"][-1].get("cameras", []) if chat["history"] else []
shown_cameras = cams.for_turn(prompt, previous_cameras) if prompt else previous_cameras
ui.camera_panel(cams.resolve(shown_cameras))

if not chat["history"]:
    ui.example_card()

chat_view.render_history(chat)

if prompt:
    chat_view.answer_turn(chat, prompt, attachments, shown_cameras)
    st.rerun()
