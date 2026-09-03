# ShutterAide

**A multi-agent photography assistant that answers "what settings do I use here — and where is that on *this* camera?"**

🔗 **Live app:** https://multi-agent-photography-assistant-gpegihzwybyrkdw233xcmn.streamlit.app/

---

## What it is

A hobbyist in front of a scene has two questions at once: what the light calls for in
aperture, shutter and ISO, and where that camera keeps those controls. A manual explains the
camera but never the scene; a forum post explains the scene and assumes you own the camera.

ShutterAide answers both halves. Ask it in plain language — *"what settings for a mountain
landscape on a Canon R5?"* — and two agents work in sequence: the first reads the **scene**
(light, motion, depth), the second turns that into **settings for that body**, grounded in
its manual.

Built with LangGraph, ChromaDB, Groq and Streamlit.

## How it stays honest

Settings are advice someone acts on, and a beginner can't tell a good answer from a confident
guess. So context has to be earned. Every source is graded by a supervisor agent before it is
allowed to produce an answer, and the app climbs a ladder until one passes:

```
attached files  →  supervisor  ─approved→  Agent 1 → Agent 2 → Editor → answer
      ↓ rejected
archive search  →  supervisor  ─approved→  Agent 1 → Agent 2 → Editor → answer
      ↓ rejected
web search      →  supervisor  ─approved→  Agent 1 → Agent 2 → Editor → answer
      ↓ rejected
"I don't have relevant information"
```

If nothing holds up, it says so rather than inventing an f-stop — and it names the source
that won.

---

## Where to find things

### Documentation

| Document | What's in it |
|---|---|
| [Documentation/README.md](Documentation/README.md) | Overview, project structure, quick start |
| [Documentation/SETUP.md](Documentation/SETUP.md) | **Installation, API keys, and how to run it** |
| [Documentation/ARCHITECTURE.md](Documentation/ARCHITECTURE.md) | The escalation ladder, routing logic, LangGraph flow |
| [Documentation/COMPONENTS.md](Documentation/COMPONENTS.md) | Each module explained in detail |
| [Documentation/USAGE.md](Documentation/USAGE.md) | Using the app and customizing it |
| [Documentation/OBSERVABILITY.md](Documentation/OBSERVABILITY.md) | LangSmith tracing and conversation recording |
| [Documentation/IMPLEMENTATION_SUMMARY.md](Documentation/IMPLEMENTATION_SUMMARY.md) | Full summary and change log |
| [deliverables/README.md](deliverables/README.md) | Project write-up: problem, design decisions, limits |
| [deliverables/AI_NOTE.md](deliverables/AI_NOTE.md) | Notes on AI assistance during development |

> **Want to run it locally?** Start at [Documentation/SETUP.md](Documentation/SETUP.md).

### Code

| File | Role |
|---|---|
| [streamlit_app.py](streamlit_app.py) | **The application** — UI plus the full agent pipeline |
| [vintage_theme.py](vintage_theme.py) | Styling: palette, CSS, layout helpers |
| [ingest_documents.py](ingest_documents.py) | Ingestion CLI — folder of documents → vector database |
| [observability.py](observability.py) | LangSmith tracing setup and run metadata |
| [conversation_store.py](conversation_store.py) | Durable transcript store (SQLite / Postgres) |
| [export_conversations.py](export_conversations.py) | Export recorded turns for evaluation or training |
| [multiagent_chatbot.py](multiagent_chatbot.py) | Legacy terminal chatbot — older, simpler flow |
| [main.py](main.py) | Early prototype, superseded — not part of the pipeline |
| [documents/](documents/) | Drop camera manuals and photography guides here |
| [.streamlit/config.toml](.streamlit/config.toml) | Streamlit theme settings |

Start with [streamlit_app.py](streamlit_app.py) — everything the live app does runs through it.

---

## Stack

LangGraph · LangChain · ChromaDB · Groq (`gpt-oss-120b`) · `all-MiniLM-L6-v2` embeddings ·
DuckDuckGo search · Streamlit · LangSmith
