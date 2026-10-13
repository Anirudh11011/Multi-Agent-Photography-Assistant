"""The pieces of the Streamlit app, assembled by streamlit_app.py.

    settings            fixed model, retrieval and history settings
    prompts             every prompt
    pipeline            the LangGraph escalation ladder (no Streamlit in it)
    guardrails          deterministic checks on a finished answer
    loaders             document loaders shared with the ingestion CLI
    resources           cached embeddings, vector store and compiled graph
    attachments         uploaded files → session-only context
    conversation_store  durable transcript store
    observability       LangSmith tracing
    sessions            chat sessions held in st.session_state
    theme               all styling and layout helpers
    camera_images       camera photos for the side panel
    sidebar             new conversation, manual upload, recent chats
    chat                rendering past turns and answering a new one
"""
