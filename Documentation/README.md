# Multi-Agent Photography Assistant — Documentation

## Overview

A multi-agent assistant built with LangGraph, ChromaDB, and the Groq API, driven from
a Streamlit web UI. It answers photography questions from **your own documents**, and
when your documents don't cover the question it escalates — first to a web search, and
finally to an explicit "I don't have relevant information" rather than a guess.

The defining behaviour is the **escalation ladder**. Every source of context is graded
by a supervisor agent before it is allowed to produce an answer:

```
attached files  →  supervisor  ─approved→  Agent 1 → Agent 2 → Editor → answer
      ↓ rejected
archive search  →  supervisor  ─approved→  Agent 1 → Agent 2 → Editor → answer
      ↓ rejected
web search      →  supervisor  ─approved→  Agent 1 → Agent 2 → Editor → answer
      ↓ rejected
"I don't have relevant information"
```

## Project Structure

```
Multi-Agent-Photography-Assistant/
├── streamlit_app.py           # The application — UI + agent pipeline
├── vintage_theme.py           # All styling: palette, CSS, layout helpers
├── .streamlit/config.toml     # Streamlit's own theme settings
├── ingest_documents.py        # Document ingestion CLI (folder → vector DB)
├── observability.py           # LangSmith tracing setup and run metadata
├── conversation_store.py      # Durable transcript database (SQLite / Postgres)
├── export_conversations.py    # Export recorded turns for training or evaluation
├── multiagent_chatbot.py      # Legacy terminal chatbot (older, simpler flow)
├── main.py                    # Early prototype, superseded — not part of the pipeline
├── documents/                 # Drop your PDFs / manuals / guides here
├── .env                       # Environment variables (API keys, DATABASE_URL)
├── requirements.txt           # Python dependencies
├── chroma_langchain_db/       # Persisted vector database
├── conversations.db           # Recorded transcripts (SQLite fallback)
└── Documentation/             # This folder
    ├── README.md             # Overview
    ├── ARCHITECTURE.md       # System architecture and routing logic
    ├── SETUP.md              # Installation & setup guide
    ├── COMPONENTS.md         # Detailed component explanation
    ├── USAGE.md              # How to use and customize
    ├── OBSERVABILITY.md      # LangSmith tracing + conversation recording
    └── IMPLEMENTATION_SUMMARY.md  # Full summary + change log
```

## Quick Start

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Setup Environment:**
   - Create `.env` with your Groq API key
   - See `SETUP.md` for details

3. **Add Documents** (optional — the web fallback works without them):
   Copy camera manuals, photography guides, or any reference files into `documents/`.
   Supported: PDF, DOCX, CSV, HTML, TXT, MD, JSON, PY.

4. **Ingest Documents:**
   ```bash
   python ingest_documents.py
   ```

5. **Run the App:**
   ```bash
   streamlit run streamlit_app.py
   ```
   Opens at `http://localhost:8501`.

## The Interface

A vintage, letterpress-styled web page with two sidebar panels and nothing else:

- **Context** — a drag-and-drop box. Files dropped here are used as the context for
  the current question, ahead of the archive. They are session-scoped and are **not**
  written into the vector database.
- **Recent chats** — the conversations from this browser session, titled from their
  first question, plus a "New conversation" button.

Every answer carries a **badge** naming the source that produced it (attached files /
archive search / web search), and an **Agent trace** expander showing the retrieved
passages with their relevance scores, the supervisor's verdict at each rung, and each
agent's working.

## Key Features

✅ **Escalation ladder** — attached files → archive → web, never silently skipped
✅ **Supervisor gate** — an LLM grades every source; unsupported questions are refused, not hallucinated
✅ **Web search fallback** — DuckDuckGo via `ddgs`; no API key, no account
✅ **Attach-for-context** — drop files in the sidebar without permanently ingesting them
✅ **Document Ingestion** — one command loads a whole folder into the vector DB
✅ **Full transparency** — relevance scores and supervisor verdicts visible per answer
✅ **Vector Database** — ChromaDB stores and retrieves document chunks
✅ **LangGraph** — orchestrates the agents, including the escalation loop
✅ **Groq API** — fast LLM inference
✅ **LangSmith tracing** — every node, prompt and LLM call, grouped one thread per conversation
✅ **Conversation recording** — every turn stored in SQL, local and deployed, exportable for training

## Technology Stack

- **Streamlit**: Web UI
- **LangGraph**: Agent workflow orchestration, including conditional edges and cycles
- **ChromaDB**: Vector database for knowledge storage
- **Groq API**: LLM backend (`openai/gpt-oss-120b`)
- **Sentence Transformers**: Embedding model (all-MiniLM-L6-v2)
- **ddgs**: DuckDuckGo search for the web fallback
- **LangChain**: Core LLM abstractions
- **LangSmith**: Tracing and evaluation
- **SQLAlchemy**: Conversation store — SQLite locally, Postgres in deploy mode
- **langchain-community / pypdf / docx2txt**: Document loaders

## Where to Read Next

- New to the project → `SETUP.md`
- Want to understand the routing → `ARCHITECTURE.md`
- Want line-by-line detail → `COMPONENTS.md`
- Want to use or customize it → `USAGE.md`
- Want traces, stored conversations, or training exports → `OBSERVABILITY.md`
- Want the full change history → `IMPLEMENTATION_SUMMARY.md`
