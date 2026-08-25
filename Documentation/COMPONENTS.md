# Component Details

## 1. Agent State

The central data structure passed between all nodes.

**File**: `multiagent_chatbot.py` (lines 32-38)

```python
class AgentState(TypedDict):
    user_input: str           # Original user query
    context: str              # Retrieved document chunks
    analysis_1: str           # Output from Agent 1
    analysis_2: str           # Output from Agent 2
    final_response: str       # Final response to user
```

### How it flows:
1. `user_input` is set by `chat()` before the graph runs
2. `context` is populated by the supervisor from the vector DB
3. `analysis_1` is added by Agent 1
4. `analysis_2` is added by Agent 2
5. `final_response` is created by Response Generator

---

## 2. Supervisor

**File**: `multiagent_chatbot.py` (lines 40-53)

**Purpose**: Retrieval and logging. Not an LLM agent, and not a router.

**What it does:**
- Similarity-searches ChromaDB for the 4 chunks closest to the user's query
- Restricts the search to ingested documents via a metadata filter
- Joins them into `state["context"]`
- Logs the user input into the vector DB
- Passes state to Agent 1

```python
def supervisor_agent(state: AgentState) -> AgentState:
    """Supervisor retrieves related documents, then stores the user input"""
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

**Input**: `user_input`
**Output**: `context` + user input stored in vector DB

**Why the filter is there**: the collection also contains previous user inputs and
previous agent outputs. Without `filter={"type": "ingested_document"}`, the retrieved
"reference documents" would include the chatbot's own past chatter.

---

## 3. Agent 1: Scene Analysis

**File**: `multiagent_chatbot.py` (lines 56-67)

**Purpose**: Analyze scene conditions and photography context

**What it does:**
- Reads the retrieved documents and the user query
- Analyzes lighting, composition, environment
- Stores its analysis in ChromaDB
- Passes to Agent 2

```python
def agent_1(state: AgentState) -> AgentState:
    """Agent 1 performs analysis"""
    prompt = (
        f"You are a helpful Cameramen assistant. When asked to analyze something, "
        f"analyze scenic nature so that another agent could write a proper camera "
        f"settings for it.\n\n"
        f"Reference documents:\n{state['context']}\n\n"
        f"Analyze this: {state['user_input']}"
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    state["analysis_1"] = response.content

    vector_store.add_texts(
        texts=[response.content],
        metadatas=[{"type": "agent1_analysis"}]
    )
    return state
```

**Input**: `context` + `user_input`
**Output**: `analysis_1` (scene analysis)

---

## 4. Agent 2: Camera Settings Provider

**File**: `multiagent_chatbot.py` (lines 70-81)

**Purpose**: Provide specific camera settings based on the scene analysis

**What it does:**
- Reads the retrieved documents, Agent 1's analysis, and the original query
- Provides detailed camera settings
- Stores settings in ChromaDB

```python
def agent_2(state: AgentState) -> AgentState:
    """Agent 2 performs analysis"""
    prompt = (
        f"You are a helpful assistant. Provide detailed camera settings of that "
        f"camera model using the information you got from agent 1.\n\n"
        f"Reference documents:\n{state['context']}\n\n"
        f"Agent 1 analysis:\n{state['analysis_1']}\n\n"
        f"Give the settings for: {state['user_input']}"
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    state["analysis_2"] = response.content

    vector_store.add_texts(
        texts=[response.content],
        metadatas=[{"type": "agent2_analysis"}]
    )
    return state
```

**Input**: `context` + `analysis_1` + `user_input`
**Output**: `analysis_2` (camera settings)

> **Note**: earlier this prompt said *"using the information you got from agent 1"*
> but never actually interpolated `analysis_1` into the string — Agent 2 was working
> blind. The `analysis_1` interpolation above is the fix.

---

## 5. Response Generator

**File**: `multiagent_chatbot.py` (lines 84-95)

**Purpose**: Combine both analyses into the final response

```python
def response_generator(state: AgentState) -> AgentState:
    """Generate final response"""
    prompt = f"""Based on these analyses, generate a response:

Analysis 1: {state["analysis_1"]}
Analysis 2: {state["analysis_2"]}

Provide a final answer."""

    response = llm.invoke([HumanMessage(content=prompt)])
    state["final_response"] = response.content
    return state
```

**Input**: `analysis_1` + `analysis_2`
**Output**: `final_response`

> **Gap**: this node sees neither `context` nor `user_input`. It works because both
> analyses restate the question's substance, but the final wording is one step
> removed from what the user actually typed. Adding `{state['user_input']}` to this
> prompt would close it.

---

## 6. Document Ingestion Script

**File**: `ingest_documents.py` (148 lines)

**Purpose**: Load every document in a folder into the vector database

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

These deliberately match `multiagent_chatbot.py`, so ingested documents are
immediately visible to the chatbot with no further wiring.

### Supported formats

```python
LOADERS = {
    ".pdf":  PyPDFLoader,
    ".docx": Docx2txtLoader,
    ".doc":  Docx2txtLoader,
    ".csv":  CSVLoader,
    ".html": UnstructuredHTMLLoader,
    ".htm":  UnstructuredHTMLLoader,
    ".txt":  TextLoader,
    ".md":   TextLoader,
    ".json": TextLoader,
    ".py":   TextLoader,
}
```

Unsupported extensions are skipped with a message rather than raising.
HTML requires `unstructured`, which is listed in requirements but not installed by default.

### Key functions

| Function | Responsibility |
|---|---|
| `collect_files(folder)` | Recursive `os.walk`, skipping hidden files and hidden directories |
| `load_file(path)` | Routes by extension; catches and reports per-file failures so one bad file doesn't abort the run |
| `chunk_id(chunk)` | `sha256(source + content)[:32]` — deterministic ID making re-runs idempotent |
| `main()` | Arg parsing, optional reset, load → chunk → dedupe → batch insert |

### Metadata written

```python
doc.metadata["source"] = os.path.relpath(path, folder)   # e.g. "sony_a7iv_manual.pdf"
doc.metadata["type"] = "ingested_document"               # what the supervisor filters on
# plus start_index, added by the splitter
```

### Idempotency

Chunk IDs are content hashes, so ingesting the same unchanged folder twice leaves
the collection count unchanged (verified). **Caveat**: editing a file produces new
hashes, so the old chunks remain orphaned. Use `--reset` after editing sources.

---

## 7. Vector Database (ChromaDB)

**Purpose**: Persistent knowledge storage

**Collection**: `multi_agent_collection` in `./chroma_langchain_db/`

### Adding data:
```python
vector_store.add_texts(
    texts=["Camera instruction text"],
    metadatas=[{"type": "camera_settings"}]
)
```

### Retrieving data:
```python
results = vector_store.similarity_search(
    "sunset photography", k=4, filter={"type": "ingested_document"}
)
for doc in results:
    print(doc.page_content, doc.metadata)
```

### Inspecting relevance scores:
```python
for doc, distance in vector_store.similarity_search_with_score("sunset", k=4):
    print(f"{distance:.3f}  {doc.metadata['source']}")
```
Lower distance = closer match.

### Persistence:
- Data stored in `./chroma_langchain_db/`, survives restarts
- Both the chatbot and the ingestion script open the same collection

---

## 8. Embedding Model

**Model**: `sentence-transformers/all-MiniLM-L6-v2`
**Provider**: HuggingFace
**Purpose**: Convert text to 384-dimensional vectors

- Used by **both** the ingestion script and the chatbot — they must match
- Small and fast (~22MB), runs on CPU

```python
embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)
```

---

## 9. LLM Backend (Groq)

**Provider**: Groq API
**Model**: `openai/gpt-oss-120b` (configurable)
**Purpose**: Powers agent_1, agent_2, and response_generator — 3 calls per query

```python
llm = ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=groq_api_key
)
```

---

## 10. LangGraph Graph

**Nodes**: supervisor → agent_1 → agent_2 → response_generator → END

```python
graph_builder.add_edge(START, "supervisor")
graph_builder.add_edge("supervisor", "agent_1")
graph_builder.add_edge("agent_1", "agent_2")
graph_builder.add_edge("agent_2", "response_generator")
graph_builder.add_edge("response_generator", END)

graph = graph_builder.compile()
result = graph.invoke(initial_state)
```

**Execution**: Sequential. All edges are unconditional, so the flow is a fixed chain.

---

## Data Flow Diagram

```
       documents/*.pdf
              │
              │  ingest_documents.py  (offline)
              │  load → chunk(1000/150) → embed → store
              ↓
     ┌──────────────────┐
     │    ChromaDB      │
     │ type=ingested_   │
     │    document      │
     └────────┬─────────┘
              │ similarity_search(k=4, filter=type)
              │
┌─────────────┴───┐
│   User Input    │
└────────┬────────┘
         ↓
┌──────────────────────┐
│ Supervisor           │  ← retrieves context
│ - No LLM call        │  → stores user_input
│ - Fills context      │
└────────┬─────────────┘
         │  context + user_input
         ↓
┌──────────────────────┐
│ Agent 1              │  → stores agent1_analysis
│ - Scene Analysis     │
└────────┬─────────────┘
         │  context + analysis_1 + user_input
         ↓
┌──────────────────────┐
│ Agent 2              │  → stores agent2_analysis
│ - Camera Settings    │
└────────┬─────────────┘
         │  analysis_1 + analysis_2
         ↓
┌──────────────────────┐
│ Response Generator   │
│ - Formats response   │
└────────┬─────────────┘
         ↓
┌─────────────────┐
│   Final Output  │
└─────────────────┘
```

---

## How Components Work Together

1. **You** run `ingest_documents.py` once to load the corpus
2. **User** types a query
3. **Supervisor** retrieves the 4 closest document chunks and logs the query
4. **Agent 1** analyzes the scene using those chunks
5. **Agent 2** produces settings from the chunks + Agent 1's analysis
6. **Response Generator** combines both analyses into the final answer
7. **ChromaDB** persists the documents and the conversation trail

This modular design allows easy addition of new agents, a knowledge base that
updates without touching code, and clear separation between ingestion and querying.
