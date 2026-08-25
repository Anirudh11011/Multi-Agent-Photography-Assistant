# System Architecture

## High-Level Flow

```
Documents in documents/
    ↓  (offline, via ingest_documents.py)
ChromaDB
    │
    │            ┌──────────────── Files attached in the sidebar (session only)
    │            │
User Input ──────┴──→ [gather_context]  loads ONE source per pass
                            ↓
                      [supervisor]  LLM grades: does this answer the question?
                        ↓        ↓
                 approved      rejected → back to gather_context (next rung)
                        ↓                 …or refuse when rungs run out
                  [Agent 1: Analysis]     context + user_input
                        ↓
                  [Agent 2: Settings]     context + analysis_1 + user_input
                        ↓
                  [Response Generator]    analysis_1 + analysis_2 + source note
                        ↓
                    User Output
```

There are three pipelines in the project:

- **Ingestion (offline)** — `ingest_documents.py` reads a folder, chunks the text,
  embeds it, and writes it to ChromaDB tagged `type: "ingested_document"`.
- **Query (online, primary)** — `streamlit_app.py` runs the escalation ladder above.
- **Query (legacy)** — `multiagent_chatbot.py`, the original terminal chatbot. It runs
  an older, simpler flow: fixed linear chain, no supervisor gate, no relevance floor,
  no web fallback. It is **not** kept in sync with the app; see "Legacy CLI" below.

Ingestion and query share the collection name, persist directory, and embedding model.
Those three must stay in sync or retrieval silently returns nothing.

---

## The Escalation Ladder

This is the core design. Rather than one retrieval feeding a fixed chain, context is
gathered **one source at a time**, and each source must pass a supervisor grade before
it is allowed to produce an answer.

| Rung | Source | When it is tried |
|---|---|---|
| 1 | `attached` | Only when files are attached in the sidebar |
| 2 | `retrieved` | Always (rung 1 rejected, or no files attached) |
| 3 | `web` | Both previous rungs rejected |
| — | refuse | All rungs exhausted |

The ladder is built per query in `streamlit_app.py`:

```python
stages = (["attached"] if attached_context else []) + ["retrieved", "web"]
```

### Why attachments are graded too

An earlier version trusted attached files outright and skipped the supervisor. That
was wrong: a user can attach a document about one camera and then ask about another.
Grading attachments means an off-target file falls through to the archive and then the
web, instead of the agents being forced to answer from material that doesn't fit.

Verified example — a file about the Fujifilm X-T5 attached, question asked about the
Nikon Z9 battery:

```
attached:  NO - the passage discusses the Fujifilm X-T5 and contains no
                information about the Nikon Z9's battery life
retrieved: Nothing in the archive scored above the relevance floor.
web:       YES - the passages give explicit battery life figures
→ answered from the web
```

### The loop in LangGraph terms

`supervisor` has conditional edges pointing back at `gather_context`, which makes the
graph a genuine cycle rather than a chain:

```python
def route_after_supervisor(state):
    if state["approved"]:
        return "agent_1"
    return "gather_context" if state["stage"] < len(state["stages"]) else "refuse"
```

`state["stage"]` is the index of the next rung, incremented by `gather_context` each
pass, which is what terminates the loop.

---

## Component Breakdown

### 1. **gather_context**
- **Role**: Load the next rung's material into `state["context"]`
- **Does NOT call the LLM**
- **Per rung**:
  - `attached` — the pre-ranked text of the sidebar files
  - `retrieved` — `similarity_search_with_relevance_scores(k=4)` filtered to
    `type="ingested_document"`, keeping only chunks at or above `RELEVANCE_FLOOR`
  - `web` — a DuckDuckGo search via `ddgs`, top 5 results as title/URL/snippet

The metadata filter matters. The collection also holds past user inputs and past agent
outputs from the legacy CLI; without it, the "reference documents" block would fill up
with the chatbot's own previous chatter instead of your manuals.

### 2. **supervisor**
- **Role**: The gate. Decides whether the current context actually answers the question
- **Calls the LLM** (one call per rung attempted)
- Short-circuits without an LLM call when the context is empty, when the relevance
  floor rejected everything, or when the web search failed
- **Output**: `approved` (bool), `verdict` (the model's one-line reason), and an entry
  appended to `attempts`

```python
prompt = (
    "You are a strict retrieval supervisor. Decide whether the passages "
    "below contain enough information to answer the question. Partial but "
    "genuinely on-topic material counts as sufficient; material that is "
    "merely on a related subject does not.\n\n"
    f"Question: {state['user_input']}\n\n"
    f"Passages:\n{context}\n\n"
    "Reply with exactly one line: 'YES - <reason>' or 'NO - <reason>'."
)
```

Unlike the legacy CLI's supervisor — which was a retrieval step with a misleading name —
this one is a real router. It calls the LLM and it decides where the graph goes next.

### 3. **Agent 1: Scene Analysis**
- **Role**: Analyzes scenic nature and photography context
- **Sees**: approved `context` + `user_input`
- **Output**: `analysis_1`

### 4. **Agent 2: Settings Provider**
- **Role**: Provides detailed camera settings
- **Sees**: approved `context` + `analysis_1` + `user_input`
- **Output**: `analysis_2`

### 5. **Response Generator**
- **Role**: Final output formatter
- **Sees**: `analysis_1` + `analysis_2` + a note naming the source rung
- **Output**: `final_response`
- When the winning rung was `web`, the note instructs it to say so and cite URLs

### 6. **refuse**
- Sets `final_response` to the standard refusal and `source` to `"none"`
- Reached only when every rung has been tried and rejected

---

## Data Flow

### State Management (AgentState)

```python
class AgentState(TypedDict):
    user_input: str
    attached_context: str  # pre-ranked text from sidebar files, "" if none
    context: str           # the current rung's material
    source: str            # "attached" | "retrieved" | "web" | "none"
    stages: list           # the ladder for this query
    stage: int             # index of the next rung to try
    approved: bool         # supervisor's decision on the current rung
    verdict: str           # supervisor's one-line reason
    attempts: list         # [(source, verdict), …] across the whole ladder
    analysis_1: str
    analysis_2: str
    final_response: str
```

### What each node actually receives

| Node | LLM call | Prompt contents |
|---|---|---|
| gather_context | no | — (retrieval / search only) |
| supervisor | yes¹ | user_input + current context |
| agent_1 | yes | context + user_input |
| agent_2 | yes | context + analysis_1 + user_input |
| response_generator | yes | analysis_1 + analysis_2 + source note |
| refuse | no | — |

¹ Skipped when the context is empty or the search failed — those are rejected without
spending a call.

**LLM calls per query**: 3 for an answer from the first rung, +1 per extra rung
attempted. A full escalation to web costs 6. A refusal after an empty archive and a
failed search costs 0.

### Vector Database (ChromaDB)

One collection, `multi_agent_collection`, partitioned by the `type` metadata field:

| `type` value | Written by | Read back? |
|---|---|---|
| `ingested_document` | `ingest_documents.py` | **Yes** — this is what rung 2 retrieves |
| `user_input` | legacy CLI only | No |
| `agent1_analysis` | legacy CLI only | No |
| `agent2_analysis` | legacy CLI only | No |

Persisted to `./chroma_langchain_db/`.

> **Changed behaviour:** the Streamlit app does **not** write anything back to the
> collection — not your questions, not the agents' output. The database only grows when
> you run `ingest_documents.py`. The legacy CLI still writes on every turn, which is
> where the existing `user_input` / `agent*_analysis` entries came from.
>
> Attached files are also never written to the collection. They are parsed, ranked, and
> used in memory for that session only.

### LangGraph Graph

```python
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

The `supervisor → gather_context` edge is the cycle. Maximum three passes, well inside
LangGraph's default recursion limit of 25.

---

## Retrieval Behavior

### How a query finds documents

Retrieval is **semantic**, not keyword-based. The query is embedded into a
384-dimensional vector and compared against every stored chunk; the `k=4` nearest are
returned with relevance scores, and anything below `RELEVANCE_FLOOR` is dropped.

### The relevance floor

`RELEVANCE_FLOOR = 0.25`. Chroma's relevance score is derived from distance and, in
this configuration, **can go negative** for unrelated text. Measured against the
project's own two-document corpus:

| Query | Top scores |
|---|---|
| "Sony A7 IV landscape settings" | 0.433, 0.203 |
| "Nikon Z9 autofocus menu" | −0.096, −0.191 |
| "how do I bake sourdough bread" | −0.264, −0.444 |

The separation is wide, which is what makes a single threshold workable. Because scores
fall outside `[0, 1]`, LangChain emits a range warning; it is suppressed deliberately
at the call site, since negative scores are exactly the signal being used.

> **This number is corpus-specific.** It was calibrated against a two-chunk corpus with
> `all-MiniLM-L6-v2`. Re-check it after ingesting a substantially larger corpus, or a
> different embedding model.

### Two gates, not one

The floor and the supervisor catch different failures, which is why both exist:

| Failure | Caught by | Example |
|---|---|---|
| Question is off-topic entirely | Relevance floor | "How do I bake sourdough bread?" — rejected in ~0.1s, no LLM call |
| Question is on-topic but the answer isn't in the text | Supervisor | "Exact battery life of the Sony A7 IV?" — the A7 IV chunk scored 0.41 and passed the floor, but the supervisor replied *"NO - The passage does not provide any information about the Sony A7 IV's battery life"* |

The second row is the important one. A threshold alone would have passed that chunk
through and the chain would have invented a battery figure.

### Slot competition

A real camera manual is hundreds of pages, so it becomes hundreds of chunks. With
`k=4`, a mixed-intent query (a scene *and* a camera model) has only four slots, and
several near-identical chunks from one large document can fill all four. Options if
this becomes a problem — raising `k`, retrieving twice with category filters, or
smaller chunks — are covered in `USAGE.md` → "Tuning Retrieval".

---

## Web Search Fallback

- **Engine**: DuckDuckGo via the `ddgs` package — no API key, no account, free
- **Depth**: `WEB_RESULTS = 5`, formatted as `[web] title / URL / snippet`
- **Graded like any other rung** — search results are not trusted automatically
- **Failure handling**: network errors, rate limits, and blocks are caught and surface
  in the trace as "Web search unavailable: …", which the supervisor treats as a
  rejection rather than crashing the run

DuckDuckGo rate-limits heavy use. A blocked search degrades to a refusal, not an error.

### Legacy CLI

`multiagent_chatbot.py` predates all of this. It runs
`START → supervisor → agent_1 → agent_2 → response_generator → END` with unconditional
edges, retrieves `k=4` with no relevance floor and no grading, has no web fallback, and
writes every turn back into the collection. It shares only the collection, persist
directory, and embedding model with the app. **Prompts and behaviour are duplicated
between the two files** — editing one does not change the other.

---

## Embedding Model

- **Model**: `sentence-transformers/all-MiniLM-L6-v2`
- **Dimensions**: 384
- **Purpose**: Ingestion, query retrieval, and in-memory ranking of attached files
- **Provided by**: HuggingFaceEmbeddings (from LangChain)
- **Important**: ingestion and query must use the *same* model, or the vectors are not
  comparable and retrieval returns noise
- Loaded once per Streamlit server via `@st.cache_resource`, not per query

---

## LLM Backend

- **Provider**: Groq API
- **Model**: `openai/gpt-oss-120b` (constant at the top of `streamlit_app.py`)
- **Temperature**: 0.7
- **Purpose**: Powers the supervisor, agent_1, agent_2, and response_generator
- **Authentication**: API key from `.env`; the app stops with a clear message if missing

---

## Attached-File Handling

Files dropped in the sidebar are handled entirely in memory:

1. Written to a temporary file so the LangChain loaders can parse them, then deleted
2. Split with the same 1000/150 splitter used by ingestion
3. If the total fits `MAX_CONTEXT_CHARS` (12000), all of it is used
4. Otherwise chunks are embedded and cosine-ranked against the question, and the top
   `MAX_ATTACHED_CHUNKS` (12) are taken within the character budget

Parsing is cached on file content, so re-asking against the same attachments does not
re-parse them.

---

## Performance Characteristics

Measured on the project's own corpus, Groq `openai/gpt-oss-120b`:

| Path | Time | LLM calls |
|---|---|---|
| Archive hit (approved on rung 2) | ~11 s | 4 |
| Full escalation to web | ~45 s | 6 |
| Off-topic refusal (floor rejects, search returns nothing) | ~0.1 s | 0 |

Response time is dominated by the sequential Groq calls. The escalation ladder trades
latency for correctness: a wrong-source answer is avoided at the cost of one extra
supervisor call per rung.

---

## Sequential vs Parallel Processing

Execution is **sequential**. Agent 2 depends on Agent 1's output, so those two cannot
be parallelized as written, and the ladder is inherently ordered — each rung is only
tried because the previous one was rejected. Retrieval happens once per rung and is
shared by both agents, which keeps their reference material identical.
