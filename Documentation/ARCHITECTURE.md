# System Architecture

## High-Level Flow

```
Documents in documents/
    ↓  (offline, via ingest_documents.py)
ChromaDB  ──────────────────┐
                            │
User Input                  │
    ↓                       │
[Supervisor] ───────────────┘  retrieves top-4 chunks → state["context"]
    ↓
[Agent 1: Analysis]      context + user_input
    ↓
[Agent 2: Settings]      context + analysis_1 + user_input
    ↓
[Response Generator]     analysis_1 + analysis_2
    ↓
User Output
```

There are two separate pipelines:

- **Ingestion (offline)** — `ingest_documents.py` reads a folder, chunks the text,
  embeds it, and writes it to ChromaDB tagged `type: "ingested_document"`.
- **Query (online)** — `multiagent_chatbot.py` retrieves from that same collection
  and runs the agent chain.

They share the collection name, persist directory, and embedding model. Those three
must stay in sync or retrieval silently returns nothing.

---

## Component Breakdown

### 1. **Supervisor**
- **Role**: Retrieval + logging entry point
- **Does NOT call the LLM** and does not route — the graph edges are fixed and linear,
  so despite the name it never chooses between agents
- **Function**: Similarity-searches the vector DB, stores user input for the record
- **Output**: Populates `state["context"]`, passes to Agent 1

```python
def supervisor_agent(state: AgentState) -> AgentState:
    docs = vector_store.similarity_search(
        state["user_input"],
        k=4,
        filter={"type": "ingested_document"}
    )
    state["context"] = "\n\n".join(d.page_content for d in docs)

    vector_store.add_texts(
        texts=[state["user_input"]],
        metadatas=[{"type": "user_input"}]
    )
    return state
```

The `filter` matters. The collection also holds past user inputs and past agent
outputs; without it, the "reference documents" block would fill up with the
chatbot's own previous chatter instead of your manuals.

### 2. **Agent 1: Scene Analysis**
- **Role**: Analyzes scenic nature and photography context
- **Sees**: retrieved `context` + `user_input`
- **Output**: `analysis_1`, also written to the vector DB as `agent1_analysis`

### 3. **Agent 2: Settings Provider**
- **Role**: Provides detailed camera settings
- **Sees**: retrieved `context` + `analysis_1` + `user_input`
- **Output**: `analysis_2`, also written to the vector DB as `agent2_analysis`

### 4. **Response Generator**
- **Role**: Final output formatter
- **Sees**: `analysis_1` + `analysis_2` only — not the context, not the original query
- **Output**: `final_response`

---

## Data Flow

### State Management (AgentState)
```python
class AgentState(TypedDict):
    user_input: str           # Original user query
    context: str              # Retrieved document chunks
    analysis_1: str           # Scene analysis from Agent 1
    analysis_2: str           # Settings from Agent 2
    final_response: str       # Combined response
```

### What each node actually receives

| Node | LLM call | Prompt contents |
|---|---|---|
| supervisor | no | — (retrieval only) |
| agent_1 | yes | context + user_input |
| agent_2 | yes | context + analysis_1 + user_input |
| response_generator | yes | analysis_1 + analysis_2 |

### Vector Database (ChromaDB)

One collection, `multi_agent_collection`, partitioned by the `type` metadata field:

| `type` value | Written by | Read back? |
|---|---|---|
| `ingested_document` | `ingest_documents.py` | **Yes** — this is what the supervisor retrieves |
| `user_input` | supervisor | No |
| `agent1_analysis` | agent_1 | No |
| `agent2_analysis` | agent_2 | No |

Persisted to `./chroma_langchain_db/`. Note that the collection grows with every
chat turn even though those entries are never retrieved.

### LangGraph Graph
- **Execution**: START → supervisor → agent_1 → agent_2 → response_generator → END
- **State Passing**: Each node receives and modifies the AgentState

---

## Retrieval Behavior

### How a query finds documents

Retrieval is **semantic**, not keyword-based. The query is embedded into a
384-dimensional vector and compared against every stored chunk by cosine distance;
the 4 nearest are returned. There is no keyword matching, no brand filter, and no
relevance threshold — the 4 nearest chunks come back even if all 4 are poor matches.

### Worked example

Corpus: two camera manuals (Sony A7 IV, Canon R6) and three scene guides
(beach sunset, forest, birds), one chunk each.

Query: *"I have to take a photo of sunset at beach give camera setting for sony camera"*

Measured result (lower distance = closer match):

| Rank | Source | Distance |
|---|---|---|
| 1 | beach_sunset_guide | 0.619 |
| 2 | sony_a7iv_manual | 0.993 |
| 3 | forest_guide | 1.150 |
| 4 | bird_guide | 1.301 |

Both halves of the question were served: the scene guide and the correct brand's
manual ranked 1 and 2, ahead of the irrelevant guides. Because `k=4`, the forest
and bird guides were still passed to the agents as "reference documents" despite
being irrelevant — the LLM has to ignore them.

### Where this gets harder

A real camera manual is hundreds of pages, so it becomes hundreds of chunks rather
than one. Two consequences:

1. **Slot competition.** A mixed-intent query (a scene *and* a camera model) has only
   4 slots. Several near-identical chunks from one large document can fill all 4,
   crowding out the other half of the question.
2. **Section relevance.** Most manual chunks are about menus, batteries, and card
   slots. The relevant section (e.g. "Sunset Scene Mode") competes against its own
   document's irrelevant sections.

Options if this becomes a problem:

- **Raise `k`** to 6–8. Simplest fix; costs prompt tokens.
- **Retrieve twice** — once filtered to scene guides, once to manuals — and concatenate.
  Requires tagging documents by category at ingest time.
- **Filter by brand** when the query names one, using a `brand` metadata field.
- **Smaller chunks** so a matching section is less diluted by surrounding text.

None of these are implemented; `k=4` with a single unfiltered search is the current behavior.

---

## Embedding Model

- **Model**: `sentence-transformers/all-MiniLM-L6-v2`
- **Dimensions**: 384
- **Purpose**: Converts text to embeddings for both ingestion and query
- **Provided by**: HuggingFaceEmbeddings (from LangChain)
- **Important**: ingestion and query must use the *same* model, or the vectors are
  not comparable and retrieval returns noise

---

## LLM Backend

- **Provider**: Groq API
- **Model**: openai/gpt-oss-120b (configurable)
- **Purpose**: Powers agent_1, agent_2, and response_generator (3 calls per query)
- **Authentication**: API key from `.env` file

---

## Sequential vs Parallel Processing

Current implementation is **sequential**:
1. All nodes run one after another
2. Agent 2 depends on Agent 1's output, so those two cannot be parallelized as written
3. State accumulates as it passes through

Retrieval was deliberately placed **once** in the supervisor rather than repeated in
each agent — one search, shared by both, which keeps the reference material
consistent between the two agents and avoids a redundant embedding call.
