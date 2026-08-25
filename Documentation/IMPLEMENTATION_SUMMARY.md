# Implementation Summary

## What Was Built

A **Multi-Agent Photography Assistant**: a Streamlit web app that uses LangGraph to
orchestrate several AI agents, grounded in a document corpus stored in a vector
database, with a supervisor agent that gates every source of context and a web-search
fallback for questions the corpus cannot answer.

### Project Name
**Multi-Agent Photography Assistant** — a specialized assistant for camera settings and
photography guidance, backed by camera manuals and field guides, with an honest refusal
path when it has nothing to go on.

---

## Technologies Used

### Interface
- **Streamlit**: Web UI, session state, file uploads, live status streaming

### Core Framework
- **LangGraph**: Agent orchestration, conditional edges, and a cyclic escalation loop
- **LangChain**: LLM abstractions and chains
- **Groq API**: Fast LLM inference backend

### Database & Storage
- **ChromaDB**: Vector database for knowledge storage
- **Sentence Transformers**: Embedding model (all-MiniLM-L6-v2)
- **LangChain HuggingFace**: Embeddings integration

### Search
- **ddgs**: DuckDuckGo search — no API key, no account

### Document Ingestion
- **langchain-community**: Document loaders (PDF, DOCX, CSV, HTML, text)
- **langchain-text-splitters**: `RecursiveCharacterTextSplitter` for chunking
- **pypdf**: PDF parsing
- **docx2txt**: Word document parsing

### Language Model
- **Groq ChatGroq**: LLM interface
- **Model**: openai/gpt-oss-120b, temperature 0.7

### Other
- **NumPy**: In-memory cosine ranking of attached-file chunks
- **python-dotenv**: Environment variable management
- **TypedDict**: State type definition

---

## System Architecture

### The Escalation Ladder

```
User Query (+ optional sidebar attachments)
    ↓
[GATHER_CONTEXT]  (no LLM call) — loads ONE rung per pass
├─ rung 1 "attached"  : pre-ranked text from sidebar files
├─ rung 2 "retrieved" : similarity search, k=4, filter type=ingested_document,
│                       dropping anything below RELEVANCE_FLOOR
└─ rung 3 "web"       : DuckDuckGo, top 5 results
    ↓
[SUPERVISOR]  (LLM call) — "do these passages answer the question? YES/NO"
├─ approved  → continue to the agents
├─ rejected + rungs remain → back to GATHER_CONTEXT with the next rung
└─ rejected + no rungs left → REFUSE
    ↓
[AGENT 1: Scene Analysis]     prompt = approved context + user_input
    ↓
[AGENT 2: Settings Provider]  prompt = context + analysis_1 + user_input
    ↓
[RESPONSE GENERATOR]          prompt = analysis_1 + analysis_2 + source disclosure
    ↓
Final Response + source badge + Agent trace
```

> **Note on naming:** unlike the legacy CLI's `supervisor_agent` — which made no LLM
> call and did not route — this supervisor is a genuine router. It calls the LLM and its
> verdict decides where the graph goes next.

### Data Management

**State Object** (AgentState):
```python
{
    "user_input": "string",
    "attached_context": "string",   # from sidebar files, "" if none
    "context": "string",            # the current rung's material
    "source": "string",             # attached | retrieved | web | none
    "stages": [...],                # the ladder for this query
    "stage": 0,                     # index of the next rung
    "approved": False,
    "verdict": "string",            # supervisor's one-line reason
    "attempts": [...],              # (source, verdict) per rung — full audit trail
    "analysis_1": "string",
    "analysis_2": "string",
    "final_response": "string"
}
```

**Vector Database**:
- Single collection `multi_agent_collection`, persisted to `./chroma_langchain_db/`
- Only `type="ingested_document"` entries are ever retrieved
- `user_input` / `agent1_analysis` / `agent2_analysis` entries exist from the legacy CLI
  and are never read back
- **The Streamlit app writes nothing to the database.** It is read-only; only
  `ingest_documents.py` adds to it
- **Attached files are never stored** — parsed, ranked, and used in memory for that
  session only

---

## Key Features Implemented

✅ **Escalation ladder** — attached files → archive → web, each rung graded before use

✅ **Supervisor gate** — a real LLM router; unsupported questions are refused, not
hallucinated. Short-circuits without an LLM call when context is empty or search failed

✅ **Two-gate retrieval** — a cheap relevance floor catches off-topic questions for free;
the LLM grader catches on-topic questions whose answer isn't actually in the text

✅ **Web search fallback** — DuckDuckGo via `ddgs`, no API key; failures degrade to a
refusal rather than a crash

✅ **Attach-for-context** — sidebar files answer the current question without being
permanently ingested; large files are cosine-ranked against the question within a budget

✅ **Full provenance** — a badge per answer naming the winning source, and an Agent trace
showing every rung, every relevance score, and every supervisor verdict

✅ **Source disclosure** — web-sourced answers say so and cite URLs

✅ **Multi-conversation UI** — recent chats in the sidebar, auto-titled from the first
question

✅ **Vintage themed interface** — aged-paper palette, letterpress typography, all styling
isolated in one module

✅ **Document Ingestion Pipeline** — unchanged: recursive folder walk, multi-format
support, content-hash IDs for idempotent re-runs

---

## Project Files

### Core Application Files

1. **streamlit_app.py** (441 lines)
   - The application: graph definition, escalation routing, web search, attachment
     handling, chat sessions, and layout

2. **vintage_theme.py** (236 lines)
   - All styling: palette constants, CSS, masthead, badges, trace rendering

3. **.streamlit/config.toml**
   - Streamlit's own theme settings, so widget chrome matches before the CSS loads

4. **ingest_documents.py** (148 lines)
   - Document ingestion CLI — folder → chunks → ChromaDB. Unchanged by the UI work; the
     app imports its constants and `load_file` rather than duplicating them

5. **multiagent_chatbot.py** (136 lines)
   - **Legacy** terminal chatbot. Still runs, but on the older linear flow: no supervisor
     gate, no relevance floor, no web fallback, and it writes every turn to ChromaDB.
     Not kept in sync with the app — the agent prompts are duplicated between the two

6. **main.py** (22 lines)
   - Early scratch/prototype file. Uses a different collection name
     (`Multi_agent_collection`, capital M) and passes `SentenceTransformer.encode`
     directly as `embedding_function`. Not part of the working pipeline

7. **.env** — `GROQ_API_KEY`. Not tracked in git

8. **documents/** — drop-folder for source documents to ingest

9. **.gitignore** — excludes `.env`, `venv/`, `__pycache__/`, `chroma_langchain_db/`,
   `.streamlit/secrets.toml`, `.DS_Store`

### Configuration Files

10. **requirements.txt** — 12 active packages (`unstructured` commented out)

### Documentation Files (This folder)

11. **README.md** - Project overview and quick start
12. **ARCHITECTURE.md** - System design, escalation ladder, retrieval behaviour
13. **SETUP.md** - Installation and configuration guide
14. **COMPONENTS.md** - Detailed component explanation
15. **USAGE.md** - How to use, tune the gates, and customize
16. **IMPLEMENTATION_SUMMARY.md** - This file

---

## Change Log — Streamlit UI, Supervisor Gate & Web Fallback

This section records the work done after the original RAG wiring (which is preserved
further below).

### 1. Created `streamlit_app.py` and `vintage_theme.py` (new files)

A Streamlit front end replacing the terminal loop as the primary interface, with all
styling isolated in a second module so the application file emits no HTML.

Initial version mirrored the CLI's linear chain, with sidebar controls for model,
temperature, `k`, and a trace toggle, plus an uploader that ingested into ChromaDB.

### 2. Removed the photography-themed UI copy

The vintage *look* (aged paper, sepia palette, letterpress type, film-grain texture) was
kept; the photography *metaphors* in the copy were removed.

| Before | After |
|---|---|
| "Darkroom" masthead | "Multi-Agent Desk" |
| "The Camera Bag" sidebar | "Context" / "Recent chats" |
| "Contact sheet" | "Agent trace" |
| "Plates / exposure / develop & file" | plain wording |
| 🎞️ / 📷 avatars | ✒️ / 📖 |

`plate` survives only as an internal CSS class name. The agent prompts still reference
cameras — that is the application's domain, not UI chrome.

### 3. Rebuilt the sidebar to two panels

Removed the model selector, temperature slider, `k` slider, trace toggle, API-key status
caption, and the archive metric. They became constants at the top of `streamlit_app.py`.

Added:
- **Context** — a drag-and-drop uploader whose files are session context, tried ahead of
  the archive and never written to the database
- **Recent chats** — per-session conversations keyed by uuid, auto-titled from the first
  question, newest-first, with a "New conversation" button

> The uploader's behaviour changed here: previously it permanently ingested into
> ChromaDB; now it supplies session-scoped context only. Permanent ingestion is
> `documents/` + `ingest_documents.py`.

### 4. Replaced the linear chain with a gated, branching graph

The supervisor became a real LLM router with conditional edges:

```python
def route_after_supervisor(state):
    if state["approved"]:
        return "agent_1"
    return "gather_context" if state["stage"] < len(state["stages"]) else "refuse"
```

Added a `refuse` node returning an explicit "I don't have relevant information" instead
of letting the agents answer from unsuitable material.

Retrieval moved from `similarity_search` to `similarity_search_with_relevance_scores`
with a `RELEVANCE_FLOOR`, so weak matches are dropped rather than padded into the prompt.

### 5. Graded attachments too, instead of trusting them

The first version of the gate let attached files bypass the supervisor entirely. That
was wrong — a user can attach a document about one camera and ask about another. Every
rung is now graded.

### 6. Added the web-search fallback

`web_search()` using `ddgs` (DuckDuckGo, no API key), as the final rung. Search results
are graded like any other source. Failures return a `__SEARCH_FAILED__` sentinel that the
supervisor treats as a rejection, so a rate-limit or outage degrades to a refusal rather
than crashing a run that has already spent several LLM calls.

The Response Generator now receives a source note; when the web rung wins it is
instructed to say so and cite URLs.

### 7. Calibration finding: Chroma relevance scores go negative

Measured against the project's own corpus with `all-MiniLM-L6-v2`:

| Query | Top scores |
|---|---|
| "Sony A7 IV landscape settings" | 0.433, 0.203 |
| "Nikon Z9 autofocus menu" | −0.096, −0.191 |
| "how do I bake sourdough bread" | −0.264, −0.444 |

Because the values fall outside `[0, 1]`, LangChain emits a range warning; it is
suppressed at the call site since negative scores are precisely the signal being used.
`RELEVANCE_FLOOR = 0.25` sits in the wide gap. **This number is corpus-specific** and
should be re-checked after a substantially larger ingest.

### 8. Updated `requirements.txt`

Added `streamlit` and `ddgs`. Both installed into `venv/`.

### 9. Verification performed

Every path was exercised end to end against the real corpus and a live Groq key.

| Test | Path taken | Result |
|---|---|---|
| "Sony A7 IV landscape settings" | archive → approved | Answered, 11.3 s |
| "How many megapixels is the Canon R5 sensor?" | archive rejected → web → approved | Correct (44.8 MP), 45.6 s |
| "Exact battery life in shots for the A7 IV?" | archive passed floor at 0.41 → supervisor **NO** | Refused instead of inventing a figure |
| "How do I bake sourdough bread?" | floor rejected | Refused in 0.1 s, **zero LLM calls** |
| Fuji X-T5 file attached, asked about Nikon Z9 battery | attached rejected → archive rejected → web approved | Answered from the web |
| X-T5 file attached, asked about the X-T5 | attached → approved, supervisor skipped for later rungs | Answered from the file — a camera absent from the archive |
| Unanswerable question, web forced empty | archive → web → rungs exhausted | Refused |

The "battery life" row is the one that justifies having two gates: the chunk cleared the
relevance floor, so a threshold alone would have passed it through and the chain would
have hallucinated a figure. The LLM grader caught it.

### 10. Documentation refreshed

All six documents rewritten to describe the Streamlit app as the primary entry point,
the escalation ladder, the two gates, the web fallback, and the legacy status of
`multiagent_chatbot.py`.

---

## Change Log — Document Ingestion + RAG Wiring (earlier work)

### 1. Created `ingest_documents.py`

A standalone CLI that reads a folder of documents and writes them into the same
ChromaDB collection the assistant reads.

| Concern | Decision |
|---|---|
| File discovery | `os.walk` recursive; hidden files and directories skipped |
| Format routing | Extension → loader map (`.pdf` → `PyPDFLoader`, `.docx`/`.doc` → `Docx2txtLoader`, `.csv` → `CSVLoader`, `.html`/`.htm` → `UnstructuredHTMLLoader`, `.txt`/`.md`/`.json`/`.py` → `TextLoader`) |
| Unsupported types | Skipped with a printed message, not an error |
| Parse failures | Caught per file and reported; remaining files still ingest |
| Chunking | `RecursiveCharacterTextSplitter`, 1000 / 150, `add_start_index=True` |
| Metadata | `source` = path relative to the ingest folder; `type` = `"ingested_document"` |
| IDs | `sha256(source + content)[:32]`, so re-running overwrites instead of duplicating |
| Batching | Chunks written 100 at a time with progress output |

The `type: "ingested_document"` tag was the design decision that makes the retrieval
filter possible — and it is still what separates real documents from legacy chat entries.

### 2. Created `documents/` folder

The default ingest location.

### 3. Wired the agents to read from the vector store

Added `context` to the state, made the supervisor retrieve before storing, and
interpolated `context` into both agent prompts. This also fixed a pre-existing bug:
Agent 2's prompt said *"using the information you got from agent 1"* but `analysis_1`
was never actually interpolated — Agent 2 was working blind.

### 4. Verification performed

| Test | Result |
|---|---|
| Ingest a sample `.txt` | 1 chunk stored |
| Re-run ingestion unchanged | Count unchanged — content-hash IDs prevent duplicates |
| End-to-end retrieval | A Canon R5 note (f/11, ISO 100, 1/125, polarizing filter) was ingested; the answer to *"settings for a mountain landscape"* contained exactly those values including the polarizer |

---

## Known Limitations

1. **Prompt duplication.** The agent prompts exist in both `streamlit_app.py` and
   `multiagent_chatbot.py`. Editing one does not change the other. Extracting a shared
   `pipeline.py` would fix this; it has not been done.

2. **`RELEVANCE_FLOOR` is corpus-specific.** 0.25 was calibrated against a two-chunk
   corpus with `all-MiniLM-L6-v2`. A much larger corpus, or a different embedding model,
   needs re-calibration.

3. **Recent chats are session-only.** They live in `st.session_state` and do not survive
   a server restart or a new browser session.

4. **`response_generator` receives neither `context` nor `user_input`.** It composes the
   final answer from the two analyses plus a source note. Adding `{state['user_input']}`
   is a one-line fix.

5. **Stale chunks on edit.** IDs are derived from content, so editing a file creates new
   chunks while the old ones remain. Re-ingest with `--reset`.

6. **DuckDuckGo rate limits.** Heavy use gets throttled. A blocked search surfaces as
   "Web search unavailable" and becomes a refusal.

7. **Fixed `k=4` retrieval.** With a large corpus, a mixed-intent query can have all four
   slots filled by chunks matching only one half of the question. See ARCHITECTURE.md →
   "Slot competition".

8. **No conversational memory.** Each question is answered independently; previous turns
   in a chat are displayed but not fed back into the graph.

9. **HTML ingestion needs `unstructured`**, which is commented out in requirements.

10. **Escalation latency.** A full escalation to the web takes ~45 s versus ~11 s for an
    archive hit, because each rung adds a supervisor call.

---

## Performance Characteristics

Measured on the project's corpus with Groq `openai/gpt-oss-120b`:

| Path | Time | LLM calls |
|---|---|---|
| Archive hit (approved on the first rung tried) | ~11 s | 4 |
| Full escalation to web | ~45 s | 6 |
| Off-topic refusal | ~0.1 s | 0 |

- **Startup**: ~2–3 s for the embedding model, cached per server by `@st.cache_resource`
- **Ingestion**: ~1–2 s per 100 chunks on CPU
- **Retrieval**: milliseconds at this corpus size
- **Memory**: ~500 MB (embeddings + ChromaDB)
- **Vector DB size**: static under the app — it only grows when you re-ingest

---

## Security Considerations

✅ **API Key Management**
- Stored in `.env` (gitignored), loaded via python-dotenv

✅ **Query privacy improved**
- The app no longer writes user questions into the vector database. (The legacy CLI still
  does — do not type sensitive text into `multiagent_chatbot.py`.)

⚠️ **Vector DB**
- Local storage, not encrypted, accessible to any process on the machine

⚠️ **Ingested and attached content**
- Document text is inserted into LLM prompts verbatim. Only ingest or attach documents
  you trust.

⚠️ **Web results are model input**
- Search snippets are untrusted third-party text placed into prompts. The supervisor
  grades them for relevance, not for safety or accuracy.

⚠️ **Attachments are written to a temp file** during parsing, then deleted.

---

## Future Enhancements

1. Extract a shared `pipeline.py` so the CLI and the app stop duplicating prompts
2. Pass `user_input` (and optionally `context`) to `response_generator`
3. Persist recent chats to disk
4. Show document filenames alongside relevance scores in the context
5. Conversation memory across turns within a chat
6. Delete-by-source before re-ingest, to fix the stale-chunk issue properly
7. A cheaper/faster model for the supervisor than for the agents
8. Fetch and read full web pages rather than search snippets
9. Separate collections for documents vs. legacy conversation history

---

## Files Modified/Created Timeline

1. **Initial**: `multiagent_chatbot.py` — basic multi-agent structure
2. **Enhancement**: ChromaDB integration
3. **Improvement**: fixed embedding function error with HuggingFaceEmbeddings
4. **Customization**: camera use case with Groq API
5. **Documentation**: created the documentation suite
6. **Ingestion**: added `ingest_documents.py` + `documents/`; expanded `requirements.txt`
7. **RAG wiring**: supervisor retrieval, `context` in state, both agent prompts updated,
   Agent 2's missing `analysis_1` fixed
8. **Streamlit UI**: added `streamlit_app.py`, `vintage_theme.py`, `.streamlit/config.toml`
9. **UI revision**: photography metaphors removed from the copy; sidebar reduced to
   Context + Recent chats; settings became constants
10. **Supervisor gate**: relevance floor, LLM grader, `refuse` node, conditional edges
11. **Escalation ladder**: attachments graded too; web-search fallback via `ddgs`; the
    supervisor loops back through the rungs
12. **Documentation refresh**: all six docs updated to match the code as it now stands

---

## Getting Started Quick Reference

```bash
# 1. Install
pip install -r requirements.txt

# 2. Setup
# Create .env with GROQ_API_KEY

# 3. Add documents (optional — the web fallback works without them)
# Copy camera manuals / photography guides into documents/

# 4. Ingest
python ingest_documents.py

# 5. Run
streamlit run streamlit_app.py
```

---

## Conclusion

This assistant demonstrates modern LLM orchestration patterns: a LangGraph workflow with
conditional edges and a genuine cycle, vector-database retrieval with metadata
filtering, a reusable ingestion pipeline, and a layered escalation strategy that decides
*where* context should come from rather than assuming one source.

The design choice worth carrying forward is that **no agent runs on material that has
not been judged capable of answering the question**. A relevance threshold alone is not
enough — it passes on-topic documents that happen to lack the specific answer, which is
exactly when a language model is most likely to fabricate. The supervisor gate closes
that gap, and the escalation ladder means the honest fallback is "let me search the web"
before it is ever "I don't know".
