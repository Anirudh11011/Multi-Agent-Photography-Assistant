# Setup & Installation Guide

## Prerequisites
- Python 3.8 or higher
- pip package manager
- Groq API key (free signup at https://console.groq.com)

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

### Required Packages

**Application:**
- `streamlit` - Web UI
- `langchain-groq` - Groq LLM integration
- `langgraph` - Agent workflow orchestration
- `sentence-transformers` - Embedding model
- `langchain-chroma` - ChromaDB vector store
- `langchain-huggingface` - HuggingFace embeddings
- `python-dotenv` - Environment variable management
- `ddgs` - DuckDuckGo search for the web fallback

**Document ingestion:**
- `langchain-community` - Document loaders
- `langchain-text-splitters` - Chunking
- `pypdf` - PDF parsing
- `docx2txt` - Word document parsing
- `unstructured` - HTML parsing (large; see note below)

> **Note on `unstructured`**: it is commented out in `requirements.txt` because it is a
> large dependency. Everything except HTML ingestion works without it. Install it only
> if you need `.html`/`.htm` support:
> ```bash
> pip install unstructured
> ```

> **Note on `ddgs`**: this is the current name of the DuckDuckGo search package
> (formerly `duckduckgo-search`). No API key or account is needed. Heavy use is
> rate-limited by DuckDuckGo; a blocked search shows as "Web search unavailable" in the
> Agent trace and degrades to a refusal rather than crashing.

## Step 2: Setup Environment Variables

Create a `.env` file in the project root:

```bash
touch .env
```

Add your Groq API key:

```
GROQ_API_KEY=your_groq_api_key_here
```

**How to get a Groq API key:**
1. Go to https://console.groq.com
2. Sign up for a free account
3. Generate an API key
4. Copy and paste it into `.env`

The app checks for this at startup and stops with a clear message if it is missing.
`.env` is listed in `.gitignore` and is not committed. Copy `.env.example` for the full
list of settings.

### Optional: LangSmith tracing

Add a key from https://smith.langchain.com → Settings → API Keys:

```
LANGSMITH_API_KEY=your_langsmith_key_here
LANGSMITH_PROJECT=multi-agent-photography-assistant
```

Every agent node, LLM call and retrieval is then traced, grouped one thread per
conversation. Leave the key blank and tracing simply stays off. See
`OBSERVABILITY.md`.

### Conversation recording

Every turn is written to a database automatically — no configuration needed locally,
where it lands in `./conversations.db`. **A deployment needs `DATABASE_URL`** pointing
at a managed database, or the transcripts are lost on each restart:

```
DATABASE_URL=postgresql://user:password@host:5432/dbname
APP_ENV=deploy
```

with `pip install "psycopg[binary]"`. See `OBSERVABILITY.md` for the schema, the
Streamlit Cloud secrets block, and the export tool.

## Step 3: Add Your Documents (optional)

Put your source material into the `documents/` folder:

```bash
cp ~/Downloads/sony_a7iv_manual.pdf documents/
cp ~/Downloads/beach_sunset_guide.pdf documents/
```

Subfolders are supported — the ingester walks the tree recursively.
Hidden files and hidden directories are skipped.

**Supported formats**: `.pdf`, `.docx`, `.doc`, `.csv`, `.html`, `.htm`, `.txt`,
`.md`, `.json`, `.py`. Anything else is skipped with a message.

This step is optional. With an empty archive the app still works — every question
simply falls through to the web-search rung. You also do not need to ingest a file just
to ask about it once: drop it into the sidebar Context box instead (Step 6).

## Step 4: Ingest Documents into the Vector Database

```bash
python ingest_documents.py
```

Output looks like:
```
Found 3 file(s) in /Users/you/Multi-Agent-Photography-Assistant/documents

  loaded  47 page(s)/section(s): sony_a7iv_manual.pdf
  loaded   1 page(s)/section(s): beach_sunset_guide.txt
  skipped (unsupported type): documents/cover.png

Embedding 138 chunk(s)...
  stored 100/138
  stored 138/138

Done. Collection 'multi_agent_collection' now holds 138 chunk(s) in ./chroma_langchain_db
```

**Options:**
```bash
python ingest_documents.py /path/to/other/folder   # ingest a different folder
python ingest_documents.py --reset                 # wipe collection first
```

Re-running on an unchanged folder is safe — chunk IDs are content hashes, so nothing is
duplicated. **However**, if you *edit* a document, the old chunks stay behind. Use
`--reset` after editing source files.

## Step 5: Run the App

```bash
streamlit run streamlit_app.py
```

It opens at `http://localhost:8501`. The first question is slower than the rest — the
embedding model loads on demand and is then cached for the life of the server.

Ask a test question about something in your documents:

```
What are the landscape settings for the Sony A7 IV?
```

Expected: an answer with a **Context · archive search** badge. Open the **Agent trace**
expander to confirm the retrieved passages and the supervisor's `YES` verdict.

Then ask something your documents cannot cover:

```
How many megapixels is the Canon R5 sensor?
```

If that detail is not in your files, the trace should show the archive rejected and the
answer arriving with a **Context · web search** badge. That confirms both the supervisor
gate and the web fallback are working.

## Step 6: Try the Context Box

Drag a file into the sidebar **Context** panel and ask a question about it. The badge
should read **Context · attached files**.

Attachments are session-scoped: they are parsed and ranked in memory and are **not**
written to the vector database. To add something permanently, put it in `documents/`
and re-run Step 4.

## Optional: The Legacy Terminal Chatbot

```bash
python multiagent_chatbot.py
```

This is the original command-line version. It still runs, but it uses an **older,
simpler flow**: a fixed linear chain with no supervisor gate, no relevance floor, and no
web fallback, and it writes every turn back into the vector database. It is not kept in
sync with `streamlit_app.py` — the agent prompts are duplicated between the two files.
Use it only for quick terminal testing.

## Troubleshooting

### ModuleNotFoundError
```bash
pip install --upgrade -r requirements.txt
```

### "No module named 'streamlit'" / "'ddgs'"
```bash
pip install streamlit ddgs
```

### The app says "No GROQ_API_KEY found"
`.env` is missing, in the wrong folder, or the key name is misspelled. It must sit in
the project root next to `streamlit_app.py`, and the line must read exactly
`GROQ_API_KEY=...`.

### Everything gets refused / everything escalates to web

Your archive is probably emptier than you think. The collection count includes legacy
chat entries that are never retrieved — count only the real ones:

```python
import chromadb
col = chromadb.PersistentClient(path="./chroma_langchain_db") \
              .get_collection("multi_agent_collection")
r = col.get(where={"type": "ingested_document"}, include=["metadatas"])
print(len(r["ids"]), "retrievable chunks")
```

An empty or tiny result means ingestion never ran or wrote elsewhere. If the count looks
right but questions are still refused, the relevance floor may be too high for your
corpus — see USAGE.md → "Tuning the gates".

### Answers come from the web when the archive should have them

Open the Agent trace and read the supervisor's verdict on the `retrieved` rung. Either
the passages genuinely lack the answer (correct behaviour) or the relevance floor
dropped chunks that should have been kept. The trace prints each kept chunk's score, so
you can see immediately which case you are in.

### Web search always fails

Check connectivity, then re-run the search directly:

```python
from ddgs import DDGS
print(DDGS().text("test query", max_results=3))
```

A rate-limit or block from DuckDuckGo surfaces in the trace as "Web search unavailable"
and turns into a refusal, which is by design.

### PDF loads as 0 pages
Scanned/image-only PDFs have no text layer. `pypdf` extracts nothing from them. You'd
need OCR (e.g. `unstructured` with OCR extras, or a separate OCR pass).

### ChromaDB errors
```bash
rm -rf ./chroma_langchain_db/
python ingest_documents.py
```

### Groq API authentication error
- Verify `.env` has the correct API key
- Check the key is valid at https://console.groq.com
- Ensure no trailing spaces

### Styling looks wrong / unstyled
Confirm `vintage_theme.py` sits next to `streamlit_app.py` and `.streamlit/config.toml`
exists in the project root. The custom fonts come from Google Fonts, so an offline
machine falls back to system serif and monospace — colors and layout still apply.

## Directory Structure After Setup

```
Multi-Agent-Photography-Assistant/
├── streamlit_app.py          # ← run this
├── vintage_theme.py
├── .streamlit/
│   └── config.toml
├── ingest_documents.py
├── observability.py          # LangSmith tracing
├── conversation_store.py     # transcript database
├── export_conversations.py   # export transcripts for training
├── multiagent_chatbot.py     # legacy CLI
├── main.py                   # early prototype, unused
├── documents/                # ← your source files here
│   └── sony_a7iv_manual.pdf
├── .env                      # ← your API keys here
├── .env.example
├── conversations.db          # ← created on the first answer (SQLite fallback)
├── .gitignore
├── requirements.txt
├── chroma_langchain_db/      # ← created/populated by ingest_documents.py
│   └── (vector database files)
├── venv/
└── Documentation/
```

## Optional: Virtual Environment

Recommended for project isolation:

```bash
python3 -m venv venv
source venv/bin/activate       # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

This project already has a `venv/`. To use it without activating:

```bash
./venv/bin/python ingest_documents.py
./venv/bin/python -m streamlit run streamlit_app.py
```

Note the `-m streamlit` form — `./venv/bin/streamlit` also works, but `-m` is safer if
several Streamlit installations exist on the machine.

## Next Steps

- See `COMPONENTS.md` to understand each component
- See `ARCHITECTURE.md` for the escalation ladder and retrieval behaviour
- See `USAGE.md` for tuning the gates and customizing the agents
