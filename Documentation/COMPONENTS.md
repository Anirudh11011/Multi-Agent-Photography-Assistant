# Component Details

All line references are to `streamlit_app.py` (441 lines) unless stated otherwise.

---

## 1. Agent State

The central data structure passed between all nodes.

**File**: `streamlit_app.py` (lines 61–73)

```python
class AgentState(TypedDict):
    user_input: str
    attached_context: str  # pre-ranked text from sidebar files, "" if none
    context: str           # the current rung's material
    source: str            # "attached" | "retrieved" | "web" | "none"
    stages: list           # sources still to try, in order
    stage: int             # index of the next source to try
    approved: bool
    verdict: str
    attempts: list         # [(source, verdict), …] across the whole ladder
    analysis_1: str
    analysis_2: str
    final_response: str
```

### How it flows

1. The UI sets `user_input`, `attached_context`, and the `stages` ladder before the graph runs
2. `gather_context` fills `context` and `source`, and increments `stage`
3. `supervisor` sets `approved` / `verdict` and appends to `attempts`
4. On rejection, control returns to step 2 for the next rung
5. On approval, `analysis_1` → `analysis_2` → `final_response` are filled in turn

`stage` and `stages` are what make the loop terminate — without them the
supervisor→gather_context edge would cycle forever.

---

## 2. Configuration Constants

**File**: `streamlit_app.py` (lines 47–57)

```python
MODEL_NAME = "openai/gpt-oss-120b"
TEMPERATURE = 0.7
TOP_K = 4
RELEVANCE_FLOOR = 0.25      # below this, retrieval is treated as a miss
MAX_CONTEXT_CHARS = 12000   # budget for attached-file context
MAX_ATTACHED_CHUNKS = 12
RECENT_CHAT_LIMIT = 12
WEB_RESULTS = 5             # DuckDuckGo hits pulled on the final fallback
REFUSAL = "I don't have relevant information to answer that — …"
```

These were sidebar controls in an earlier version. They are constants now so the
sidebar can hold only the two panels the UI actually needs.

---

## 3. gather_context

**File**: `streamlit_app.py` (lines 110–140)

**Purpose**: Load one rung of the ladder into `state["context"]`. No LLM call.

```python
def gather_context(state: AgentState) -> AgentState:
    stages, idx = state["stages"], state["stage"]
    if idx >= len(stages):
        state["source"], state["context"] = "none", ""
        return state

    src = stages[idx]
    state["stage"] = idx + 1
    state["source"] = src

    if src == "attached":
        state["context"] = (state.get("attached_context") or "").strip()

    elif src == "retrieved":
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Relevance scores must be")
            hits = store.similarity_search_with_relevance_scores(
                state["user_input"], k=TOP_K, filter={"type": "ingested_document"}
            )
        kept = [(d, s) for d, s in hits if s is not None and s >= RELEVANCE_FLOOR]
        state["context"] = "\n\n".join(
            f"[relevance {s:.2f}]\n{d.page_content}" for d, s in kept
        )

    else:  # web
        state["context"] = web_search(state["user_input"])

    return state
```

**Input**: `stages`, `stage`, `user_input`, `attached_context`
**Output**: `context`, `source`, incremented `stage`

**Why the metadata filter is there**: the collection also contains user inputs and
agent outputs written by the legacy CLI. Without
`filter={"type": "ingested_document"}`, the retrieved "reference documents" would
include the chatbot's own past chatter.

**Why the scores are embedded in the text**: each kept chunk is prefixed with
`[relevance 0.43]`, so the Agent trace in the UI shows exactly how strong each match
was — the fastest way to tell whether `RELEVANCE_FLOOR` is set sensibly.

---

## 4. supervisor

**File**: `streamlit_app.py` (lines 142–174)

**Purpose**: The gate and the router. Grades the current rung, decides where the graph
goes next.

```python
def supervisor(state: AgentState) -> AgentState:
    context, src = state["context"], state["source"]
    attempts = list(state.get("attempts") or [])

    if not context.strip():
        state["approved"] = False
        state["verdict"] = {…}.get(src, "No context available.")
    elif context.startswith("__SEARCH_FAILED__"):
        state["approved"] = False
        state["verdict"] = f"Web search unavailable: {context[18:].strip()}"
    else:
        prompt = (
            "You are a strict retrieval supervisor. Decide whether the passages "
            "below contain enough information to answer the question. Partial but "
            "genuinely on-topic material counts as sufficient; material that is "
            "merely on a related subject does not.\n\n"
            f"Question: {state['user_input']}\n\n"
            f"Passages:\n{context}\n\n"
            "Reply with exactly one line: 'YES - <reason>' or 'NO - <reason>'."
        )
        verdict = llm.invoke([HumanMessage(content=prompt)]).content.strip()
        state["verdict"] = verdict
        state["approved"] = verdict.upper().lstrip("*# ").startswith("YES")

    attempts.append((src, state["verdict"]))
    state["attempts"] = attempts
    return state
```

**Input**: `context`, `source`, `user_input`
**Output**: `approved`, `verdict`, appended `attempts`

Three things worth noting:

- **It short-circuits.** Empty context, a floor rejection, or a failed search are all
  rejected without an LLM call. An off-topic question therefore costs nothing.
- **`.lstrip("*# ")`** before the `YES` check — the model sometimes wraps its verdict in
  markdown (`**YES - …**`), which would otherwise be read as a rejection.
- **`attempts` accumulates across rungs**, giving a complete audit trail of every source
  tried and why each was rejected.

> **Contrast with the legacy CLI**: `multiagent_chatbot.py` also has a function called
> `supervisor_agent`, but it makes no LLM call and does not route — it is a retrieval
> step with a misleading name. This one is a real router.

---

## 5. web_search

**File**: `streamlit_app.py` (lines 76–88)

**Purpose**: The final rung. DuckDuckGo through `ddgs` — no API key, no account.

```python
def web_search(query: str) -> str:
    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=WEB_RESULTS)
    except Exception as exc:                       # offline, rate-limited, blocked
        return f"__SEARCH_FAILED__ {exc}"
    blocks = []
    for r in results:
        title = (r.get("title") or "").strip()[:120]
        blocks.append(f"[web] {title}\n{r.get('href', '')}\n{(r.get('body') or '').strip()}")
    return "\n\n".join(blocks)
```

**Input**: the raw user question
**Output**: formatted results, or a `__SEARCH_FAILED__` sentinel

The sentinel rather than an exception is deliberate: a failed search should degrade to
a refusal with a readable reason in the trace, not crash a run that has already spent
several LLM calls. The import is inside the function so the app still starts if `ddgs`
is not installed.

---

## 6. Agent 1: Scene Analysis

**File**: `streamlit_app.py` (lines 181–189)

**Purpose**: Analyze scene conditions and photography context.

```python
def agent_1(state: AgentState) -> AgentState:
    prompt = (
        "You are a helpful Cameramen assistant. When asked to analyze something, "
        "analyze scenic nature so that another agent could write a proper camera "
        f"settings for it.\n\nReference documents:\n{state['context']}\n\n"
        f"Analyze this: {state['user_input']}"
    )
    state["analysis_1"] = llm.invoke([HumanMessage(content=prompt)]).content
    return state
```

**Input**: approved `context` + `user_input`
**Output**: `analysis_1`

It only ever runs on material the supervisor approved, so `context` here is always
relevant — whether it came from attached files, the archive, or the web.

---

## 7. Agent 2: Camera Settings Provider

**File**: `streamlit_app.py` (lines 191–200)

**Purpose**: Provide specific camera settings based on the scene analysis.

```python
def agent_2(state: AgentState) -> AgentState:
    prompt = (
        "You are a helpful assistant. Provide detailed camera settings of that "
        "camera model using the information you got from agent 1.\n\n"
        f"Reference documents:\n{state['context']}\n\n"
        f"Agent 1 analysis:\n{state['analysis_1']}\n\n"
        f"Give the settings for: {state['user_input']}"
    )
    state["analysis_2"] = llm.invoke([HumanMessage(content=prompt)]).content
    return state
```

**Input**: `context` + `analysis_1` + `user_input`
**Output**: `analysis_2`

---

## 8. Response Generator

**File**: `streamlit_app.py` (lines 202–217)

**Purpose**: Combine both analyses into the final answer, and disclose the source.

```python
def response_generator(state: AgentState) -> AgentState:
    note = {
        "attached": "The material came from files the user attached.",
        "retrieved": "The material came from the user's own ingested documents.",
        "web": ("The material came from a live web search because neither the "
                "attached files nor the archive covered this. Say so in one short "
                "line at the end, and cite the source URLs you relied on."),
    }.get(state["source"], "")
    prompt = (
        "Based on these analyses, generate a response:\n\n"
        f"Analysis 1: {state['analysis_1']}\n\n"
        f"Analysis 2: {state['analysis_2']}\n\n"
        f"{note}\n\nProvide a final answer."
    )
    state["final_response"] = llm.invoke([HumanMessage(content=prompt)]).content
    return state
```

**Input**: `analysis_1` + `analysis_2` + source note
**Output**: `final_response`

The source note is what makes a web-sourced answer say so and cite its URLs, instead of
presenting searched material with the same authority as your own manuals.

> **Gap**: this node still sees neither `context` nor `user_input`. It works because
> both analyses restate the question's substance, but the final wording is one step
> removed from what the user typed. Adding `{state['user_input']}` would close it.

---

## 9. refuse

**File**: `streamlit_app.py` (lines 176–179)

```python
def refuse(state: AgentState) -> AgentState:
    state["final_response"] = REFUSAL
    state["source"] = "none"
    return state
```

Reached only when every rung has been tried and rejected. Setting `source` to `"none"`
is what makes the UI badge read "Context · none found" rather than naming the last rung
that failed.

---

## 10. Routing

**File**: `streamlit_app.py` (lines 219–243)

```python
def route_after_supervisor(state: AgentState) -> str:
    """Approved → answer. Rejected → next source. Out of sources → refuse."""
    if state["approved"]:
        return "agent_1"
    return "gather_context" if state["stage"] < len(state["stages"]) else "refuse"


builder.add_edge(START, "gather_context")
builder.add_edge("gather_context", "supervisor")
builder.add_conditional_edges("supervisor", route_after_supervisor,
                              {"agent_1": "agent_1", "refuse": "refuse",
                               "gather_context": "gather_context"})
builder.add_edge("refuse", END)
builder.add_edge("agent_1", "agent_2")
builder.add_edge("agent_2", "response_generator")
builder.add_edge("response_generator", END)
```

**Execution**: Cyclic. The `supervisor → gather_context` mapping is the loop; at most
three passes, well inside LangGraph's default recursion limit of 25.

---

## 11. Attached-File Handling

**File**: `streamlit_app.py` (lines 246–296)

Two functions turn sidebar uploads into graded context, entirely in memory.

### `extract_chunks(file_bytes, filename)` — line 247

Writes the upload to a temp file (the LangChain loaders need a path), parses it with
`load_file` from `ingest_documents.py`, deletes the temp file, and splits the result
with the same 1000/150 splitter used by ingestion. Decorated `@st.cache_data`, so it is
keyed on file content — re-asking against the same attachments does not re-parse them.

### `build_attached_context(files, question)` — line 265

```python
joined = "\n\n".join(f"[{lab}]\n{c}" for lab, c in zip(labels, chunks))
if len(joined) <= MAX_CONTEXT_CHARS:
    return joined
# otherwise: embed, cosine-rank against the question, take the best that fit
```

Small attachments are used whole. Large ones are embedded with the same MiniLM model,
cosine-ranked against the question in NumPy, and the top `MAX_ATTACHED_CHUNKS` are
taken within the character budget. Each block keeps a `[filename]` label so the agents
can attribute a setting to the file it came from.

**Nothing here touches ChromaDB.** Attachments are session context, not archive
material — close the browser tab and they are gone.

---

## 12. Chat Sessions

**File**: `streamlit_app.py` (lines 300–317)

```python
def new_chat() -> str:
    cid = uuid.uuid4().hex[:8]
    st.session_state.chats[cid] = {"title": "New conversation", "history": [],
                                   "created": time.time()}
    st.session_state.current = cid
    return cid
```

Conversations live in `st.session_state.chats`, keyed by a short uuid. Each holds a
title, a history list, and a creation timestamp. The title is replaced by the first 40
characters of the first question asked. The sidebar lists them newest-first, capped at
`RECENT_CHAT_LIMIT`.

**Scope**: browser session. Chats survive Streamlit reruns and switching between
conversations, but not a server restart or a page reload in a new session. Persisting
them would mean writing to disk, which is not implemented.

---

## 13. The Sidebar

**File**: `streamlit_app.py` (lines 320–348)

Exactly two panels:

| Panel | Contents |
|---|---|
| **Context** | A multi-file drag-and-drop uploader, plus a caption stating whether attachments will be tried first |
| **Recent chats** | "New conversation" button, then one flat button per conversation, `›` marking the current one |

Model name, temperature, `k`, and the trace toggle were all removed from the sidebar in
favour of the constants in section 2.

---

## 14. The Main Column

**File**: `streamlit_app.py` (lines 351–441)

Renders the masthead, replays the current conversation's history, and runs new queries.
Each answer shows:

- a **badge** naming the winning source (`Context · archive search`, etc.)
- an **Agent trace** expander — every rung tried, with its material and relevance
  scores, the supervisor's verdict at each rung, and each agent's output
- the answer itself, and the elapsed time

The query runs through `get_graph().stream(state, stream_mode="updates")`, so the status
line updates live: *"Trying Context · archive search…"*, then *"Supervisor on retrieved:
rejected, escalating…"*, and so on. Because `gather_context` and `supervisor` can run
several times, the trace legitimately contains repeated entries — one pair per rung.

---

## 15. Styling (`vintage_theme.py`)

**File**: `vintage_theme.py` (236 lines)

All visual decisions live here; `streamlit_app.py` emits no HTML of its own.

| Export | Purpose |
|---|---|
| `PAPER`, `INK`, `SEPIA`, `BRASS`, … (lines 10–16) | The palette, as constants |
| `PAGE_TITLE`, `PAGE_ICON`, `USER_AVATAR`, `BOT_AVATAR` | Page and chat identity |
| `STEP_LABELS` (line 24) | Roman-numbered captions per graph node, used by the trace and the status line |
| `_CSS` (line 35) | The full stylesheet: aged-paper background with an SVG grain filter, Playfair Display headings over Courier Prime body text, bordered chat cards, brass buttons, flat sidebar chat entries |
| `configure_page()` (line 186) | `st.set_page_config` — must run before any other Streamlit call |
| `inject_css()` (line 196) | Injects `_CSS` |
| `masthead()` (line 200) | The double-ruled title block |
| `plate_header(node)` (line 210) | The letterpress label above one step in the trace |
| `badge(text)` (line 218) | The small source banner above each answer |
| `caption(text)` (line 222) | Italic secondary text |
| `step_status_label(node)` (line 226) | Formats a node name for the live status line |
| `render_trace(steps)` (line 231) | The whole Agent trace expander |

`.streamlit/config.toml` sets Streamlit's own theme (base colors and serif font) so the
widget chrome matches before the custom CSS loads.

---

## 16. Document Ingestion Script

**File**: `ingest_documents.py` (148 lines) — **unchanged** by the Streamlit work

```bash
python ingest_documents.py            # ingests ./documents
python ingest_documents.py /some/dir  # any folder
python ingest_documents.py --reset    # wipe the collection first
```

### Configuration constants (top of file)

```python
DOCS_DIR = "./documents"
PERSIST_DIR = "./chroma_langchain_db"
COLLECTION = "multi_agent_collection"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
```

`streamlit_app.py` **imports these rather than redeclaring them**:

```python
from ingest_documents import (
    load_file, COLLECTION, PERSIST_DIR, CHUNK_SIZE, CHUNK_OVERLAP,
)
```

so the CLI and the UI cannot drift apart on collection name, storage path, or chunking.
`load_file` is reused for attachment parsing, which is why the sidebar supports exactly
the same formats as the ingester.

### Supported formats

```python
LOADERS = {
    ".pdf":  PyPDFLoader,       ".docx": Docx2txtLoader,   ".doc":  Docx2txtLoader,
    ".csv":  CSVLoader,         ".html": UnstructuredHTMLLoader,
    ".htm":  UnstructuredHTMLLoader,
    ".txt":  TextLoader,        ".md":   TextLoader,
    ".json": TextLoader,        ".py":   TextLoader,
}
```

Unsupported extensions are skipped with a message rather than raising.
HTML requires `unstructured`, which is listed in requirements but commented out.

### Key functions

| Function | Responsibility |
|---|---|
| `collect_files(folder)` | Recursive `os.walk`, skipping hidden files and directories |
| `load_file(path)` | Routes by extension; catches per-file failures so one bad file doesn't abort the run. **Also used by the app for attachments** |
| `chunk_id(chunk)` | `sha256(source + content)[:32]` — deterministic ID making re-runs idempotent |
| `main()` | Arg parsing, optional reset, load → chunk → dedupe → batch insert |

### Idempotency

Chunk IDs are content hashes, so ingesting the same unchanged folder twice leaves the
collection count unchanged. **Caveat**: editing a file produces new hashes, so the old
chunks remain orphaned. Use `--reset` after editing sources.

---

## 17. Vector Database (ChromaDB)

**Collection**: `multi_agent_collection` in `./chroma_langchain_db/`

### What the app reads

```python
hits = store.similarity_search_with_relevance_scores(
    query, k=4, filter={"type": "ingested_document"}
)
```

Higher score = closer match. In this configuration scores can be **negative** for
unrelated text — see ARCHITECTURE.md → "The relevance floor".

### What the app writes

Nothing. The Streamlit app is read-only against ChromaDB: it does not log questions,
agent output, or attached files. The database changes only when you run
`ingest_documents.py`.

The legacy `multiagent_chatbot.py` does still write `user_input`, `agent1_analysis`, and
`agent2_analysis` on every turn — those entries in your collection came from it.

### Inspecting what is actually stored

```python
import chromadb
col = chromadb.PersistentClient(path="./chroma_langchain_db") \
              .get_collection("multi_agent_collection")
r = col.get(where={"type": "ingested_document"}, include=["metadatas", "documents"])
print(len(r["documents"]), "retrievable chunks")
for m, d in zip(r["metadatas"], r["documents"]):
    print(m["source"], "|", d[:80])
```

Only `type="ingested_document"` entries are ever retrieved, so this is the honest
measure of your knowledge base — the raw collection count includes legacy chat entries.

---

## 18. Embedding Model

**Model**: `sentence-transformers/all-MiniLM-L6-v2`
**Provider**: HuggingFace
**Purpose**: 384-dimensional vectors for ingestion, retrieval, and attachment ranking

```python
@st.cache_resource(show_spinner="Loading the embedding model…")
def get_embeddings():
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
```

Small and fast (~22MB), runs on CPU. The `@st.cache_resource` decorator means it loads
once per server, not once per question. Ingestion and query **must** use the same model.

---

## 19. LLM Backend (Groq)

**Provider**: Groq API
**Model**: `openai/gpt-oss-120b`
**Purpose**: Powers supervisor, agent_1, agent_2, and response_generator

```python
llm = ChatGroq(model=MODEL_NAME, api_key=os.getenv("GROQ_API_KEY"),
               temperature=TEMPERATURE)
```

Call count varies with the ladder: 3 calls for an answer from the first rung, +1 per
extra rung attempted, 0 for a refusal that never reaches the LLM.

---

## Data Flow Diagram

```
       documents/*.pdf                    sidebar attachments
              │                                   │
              │  ingest_documents.py              │  parsed + ranked in memory
              │  load → chunk → embed → store     │  (never stored)
              ↓                                   │
     ┌──────────────────┐                         │
     │    ChromaDB      │                         │
     │ type=ingested_   │                         │
     │    document      │                         │
     └────────┬─────────┘                         │
              │                                   │
              │        ┌──────────────────────────┘
              │        │        ┌───────────── DuckDuckGo (ddgs)
              ↓        ↓        ↓
        ┌──────────────────────────┐
        │     gather_context       │  ← one rung per pass
        │     - no LLM call        │
        └────────────┬─────────────┘
                     ↓
        ┌──────────────────────────┐
        │       supervisor         │  ← LLM grades the rung
        └──────┬────────────┬──────┘
     rejected  │            │  approved
   (next rung) │            ↓
        ┌──────┴──────┐  ┌──────────────────────┐
        │  refuse     │  │ Agent 1: Scene       │
        │ (rungs out) │  └──────────┬───────────┘
        └──────┬──────┘             ↓
               │        ┌──────────────────────┐
               │        │ Agent 2: Settings    │
               │        └──────────┬───────────┘
               │                   ↓
               │        ┌──────────────────────┐
               │        │ Response Generator   │
               │        │ + source disclosure  │
               │        └──────────┬───────────┘
               ↓                   ↓
        ┌──────────────────────────────┐
        │  Answer + source badge       │
        │  + Agent trace               │
        └──────────────────────────────┘
```

---

## How Components Work Together

1. **You** run `ingest_documents.py` to load the corpus (optional — the web rung works without it)
2. **User** types a question, optionally with files attached in the sidebar
3. **gather_context** loads the first rung: attachments if present, else the archive
4. **supervisor** grades it — approve and answer, or reject and drop to the next rung
5. **Agent 1** analyzes the scene using whatever material was approved
6. **Agent 2** produces settings from that material + Agent 1's analysis
7. **Response Generator** combines both and discloses where the material came from
8. **refuse** ends the run honestly if no rung ever passed

The escalation ladder is the part worth understanding: no agent ever runs on material
that has not been judged capable of answering the question.
