# Implementation Summary

## What Was Built

A **Multi-Agent Chatbot System** that uses LangGraph to orchestrate multiple AI agents working together to analyze user queries and provide intelligent responses, grounded in a document corpus stored in a vector database.

### Project Name
**Multi-Agent Camera Chatbot** - A specialized chatbot for providing camera settings and photography guidance, backed by camera manuals and photography field guides.

---

## Technologies Used

### Core Framework
- **LangGraph**: Agent orchestration and workflow management
- **LangChain**: LLM abstractions and chains
- **Groq API**: Fast LLM inference backend

### Database & Storage
- **ChromaDB**: Vector database for knowledge storage
- **Sentence Transformers**: Embedding model (all-MiniLM-L6-v2)
- **LangChain HuggingFace**: Embeddings integration

### Document Ingestion
- **langchain-community**: Document loaders (PDF, DOCX, CSV, HTML, text)
- **langchain-text-splitters**: `RecursiveCharacterTextSplitter` for chunking
- **pypdf**: PDF parsing
- **docx2txt**: Word document parsing

### Language Model
- **Groq ChatGroq**: LLM interface
- **Model**: openai/gpt-oss-120b (configurable)

### Other
- **python-dotenv**: Environment variable management
- **TypedDict**: State type definition

---

## System Architecture

### Four-Node Pipeline

```
User Query
    ↓
[SUPERVISOR]  (no LLM call)
├─ Retrieves top-4 relevant document chunks from ChromaDB
├─ Filters to type = "ingested_document"
├─ Stores user input in ChromaDB
└─ Puts retrieved text into state["context"]
    ↓
[AGENT 1: Scene Analysis]
├─ Prompt = context + user_input
├─ Analyzes scene conditions
├─ Stores analysis in ChromaDB
└─ Writes state["analysis_1"]
    ↓
[AGENT 2: Settings Provider]
├─ Prompt = context + analysis_1 + user_input
├─ Provides specific camera settings
├─ Stores settings in ChromaDB
└─ Writes state["analysis_2"]
    ↓
[RESPONSE GENERATOR]
├─ Prompt = analysis_1 + analysis_2
├─ Creates coherent response
└─ Writes state["final_response"]
    ↓
Final Response to User
```

> **Note on naming:** the "supervisor" does not call the LLM and does not route.
> The graph edges are fixed and linear, so it never chooses between agents.
> It is a retrieval + logging step.

### Data Management

**State Object** (AgentState):
```python
{
    "user_input": "string",      # Original query
    "context": "string",         # Retrieved document chunks (added in this iteration)
    "analysis_1": "string",      # Scene analysis
    "analysis_2": "string",      # Camera settings
    "final_response": "string"   # Final answer
}
```

**Vector Database**:
- Single collection `multi_agent_collection`, persisted to `./chroma_langchain_db/`
- Holds two categories of text, separated by the `type` metadata field:
  - `ingested_document` — chunks from files in `documents/` (retrieved by the supervisor)
  - `user_input`, `agent1_analysis`, `agent2_analysis` — conversation history (written, never retrieved)

---

## Key Features Implemented

✅ **Multi-Agent Orchestration**
- 4 nodes in sequence, each with a specific responsibility
- Clear data flow between nodes

✅ **Vector Database Integration**
- ChromaDB for knowledge storage
- Sentence Transformers for embeddings
- Persistent storage across sessions

✅ **Retrieval-Augmented Generation (RAG)**
- Supervisor retrieves once per query
- Both analysis agents receive the same retrieved context
- Metadata filter keeps chat history out of the retrieved context

✅ **Document Ingestion Pipeline**
- `ingest_documents.py` walks a folder recursively
- Multi-format support with per-file error isolation
- Chunking with overlap, content-hash IDs for idempotent re-runs

✅ **LLM Integration**
- Groq API for fast inference
- Configurable models
- Environment-based API key management

✅ **Interactive Chat Interface**
- Command-line chatbot loop with `exit` support

---

## Project Files

### Core Application Files

1. **multiagent_chatbot.py** (136 lines)
   - Main application: agent definitions, LangGraph setup, chat loop

2. **ingest_documents.py** (148 lines)
   - Document ingestion CLI — folder → chunks → ChromaDB

3. **main.py** (23 lines)
   - Early scratch/prototype file. Superseded by `multiagent_chatbot.py`.
   - Uses a different collection name (`Multi_agent_collection`, capital M) and passes
     `SentenceTransformer.encode` directly as `embedding_function`. Not part of the
     working pipeline — kept only as a reference.

4. **.env**
   - `GROQ_API_KEY`. Not tracked in git.

5. **documents/**
   - Drop-folder for source documents to ingest. Currently empty.

### Configuration Files

6. **requirements.txt** — 11 packages

### Documentation Files (This folder)

7. **README.md** - Project overview and quick start
8. **ARCHITECTURE.md** - System design and data flow
9. **SETUP.md** - Installation and configuration guide
10. **COMPONENTS.md** - Detailed component explanation
11. **USAGE.md** - How to use and customize
12. **IMPLEMENTATION_SUMMARY.md** - This file

---

## Change Log — Document Ingestion + RAG Wiring

This section records every change made during the ingestion/retrieval work.

### 1. Created `ingest_documents.py` (new file)

A standalone CLI that reads a folder of documents and writes them into the same
ChromaDB collection the chatbot uses.

```bash
python ingest_documents.py            # ingests ./documents
python ingest_documents.py /some/dir  # any folder
python ingest_documents.py --reset    # wipe the collection first
```

Implementation details:

| Concern | Decision |
|---|---|
| File discovery | `os.walk` recursive; hidden files and hidden directories skipped |
| Format routing | Extension → loader map: `.pdf` → `PyPDFLoader`, `.docx`/`.doc` → `Docx2txtLoader`, `.csv` → `CSVLoader`, `.html`/`.htm` → `UnstructuredHTMLLoader`, `.txt`/`.md`/`.json`/`.py` → `TextLoader` |
| Unsupported types | Skipped with a printed message, not an error |
| Parse failures | Caught per file and reported; the remaining files still ingest |
| Chunking | `RecursiveCharacterTextSplitter`, `chunk_size=1000`, `chunk_overlap=150`, `add_start_index=True` |
| Metadata | `source` = path relative to the ingest folder; `type` = `"ingested_document"` |
| IDs | `sha256(source + content)` truncated to 32 chars, so re-running overwrites instead of duplicating |
| Batching | Chunks written 100 at a time with progress output |
| Target store | Collection `multi_agent_collection`, `./chroma_langchain_db`, `all-MiniLM-L6-v2` — matched to the chatbot deliberately so no chatbot change was needed to read them |

The `type: "ingested_document"` tag was the deliberate design decision that makes
the retrieval filter in step 3 possible.

### 2. Created `documents/` folder

The default ingest location. Empty; drop files in and run the script.

### 3. Wired the agents to read from the vector store

Edits to `multiagent_chatbot.py`:

**a. Added `context` to the state** (line 34)
```python
class AgentState(TypedDict):
    user_input: str
    context: str          # ← added
    analysis_1: str
    analysis_2: str
    final_response: str
```

**b. Supervisor now retrieves before storing** (lines 40–53)
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
Retrieval happens once per query and is shared by both agents, rather than each
agent searching separately. The `filter` keeps past chat turns and prior agent
outputs — which live in the same collection — out of the retrieved context.

**c. Agent 1 prompt now includes the context** (line 58)
```python
prompt = f"...\n\nReference documents:\n{state['context']}\n\nAnalyze this: {state['user_input']}"
```

**d. Agent 2 prompt now includes context AND `analysis_1`** (line 72)
```python
prompt = f"...\n\nReference documents:\n{state['context']}\n\nAgent 1 analysis:\n{state['analysis_1']}\n\nGive the settings for: {state['user_input']}"
```
This also fixed a pre-existing bug: Agent 2's prompt said *"using the information
you got from agent 1"* but `analysis_1` was never actually interpolated into the
prompt string. Agent 2 was working blind.

**e. `chat()` initialises the new field** (line 119)
```python
initial_state = {
    "user_input": user_input,
    "context": "",        # ← added
    ...
}
```

### 4. Updated `requirements.txt`

Added: `langchain-community`, `langchain-text-splitters`, `pypdf`, `docx2txt`, `unstructured`.

Installed into `venv/`: all except **`unstructured`**, which was left uninstalled
because of its size. HTML ingestion will fail until you run
`./venv/bin/pip install unstructured`. Every other format works now.

### 5. Verification performed

| Test | Result |
|---|---|
| Ingest a sample `.txt` | 1 chunk stored, collection count 5 |
| Re-run ingestion unchanged | Count stayed 5 — content-hash IDs prevent duplicates |
| End-to-end retrieval | Ingested a Canon R5 note (f/11, ISO 100, 1/125, polarizing filter); asked *"settings for a mountain landscape"*; the bot's answer contained exactly those values including the polarizer — confirming document content reached the LLM |
| Retrieval ranking | With a 5-document corpus (2 camera manuals, 3 scene guides), the query *"photo of sunset at beach ... sony camera"* ranked `beach_sunset_guide` first (distance 0.619) and `sony_a7iv_manual` second (0.993), ahead of the forest and bird guides |

Test files were removed afterwards; `documents/` was left empty.

---

## Known Limitations

1. **Stale chunks on edit.** IDs are derived from content, so editing a file
   creates new chunks while the old ones remain. Re-ingest with `--reset` after
   editing source documents.

2. **`response_generator` receives neither `context` nor `user_input`.** It composes
   the final answer from the two analyses alone. It works in practice because both
   analyses restate the question, but the final wording is one step removed from
   what the user typed. Adding `{state['user_input']}` to that prompt is a one-line fix.

3. **HTML ingestion needs `unstructured`**, which is listed but not installed.

4. **Fixed `k=4` retrieval.** Every query pulls exactly four chunks with no relevance
   threshold. With a large corpus, a mixed-intent query (a scene *and* a camera model)
   can have its four slots filled by chunks matching only one half of the question.
   See ARCHITECTURE.md → "Retrieval Behavior" for the options if this becomes a problem.

5. **No retrieval from conversation history.** Chat turns and agent outputs are written
   to the collection but never read back — the filter excludes them by design. The
   system has no conversational memory across turns.

---

## How It Works

### Execution Flow

1. **Ingest** (one time, or after adding documents): `python ingest_documents.py`
2. **Start**: `python multiagent_chatbot.py`
3. **User Input**: Type query
4. **Supervisor**: Retrieves top-4 document chunks, stores input
5. **Agent 1**: Analyzes scene using retrieved context
6. **Agent 2**: Provides settings using context + Agent 1's analysis
7. **Response Generator**: Combines analyses
8. **Output**: Final response returned to user

### State Transformation

```
Initial State:
{ "user_input": "sunset at beach, sony camera",
  "context": "", "analysis_1": "", "analysis_2": "", "final_response": "" }

↓ Supervisor retrieves documents

{ "user_input": "sunset at beach, sony camera",
  "context": "Photographing Sunsets at the Beach... f/11, ISO 100, GND filter...",
  "analysis_1": "", "analysis_2": "", "final_response": "" }

↓ Agent 1 analyzes (sees context + user_input)

{ ..., "analysis_1": "High dynamic range scene, 8-10 stops...", ... }

↓ Agent 2 provides settings (sees context + analysis_1 + user_input)

{ ..., "analysis_2": "Sony A7 IV: Av mode, f/11, ISO 100, WB 7000K...", ... }

↓ Response Generator combines (sees analysis_1 + analysis_2)

{ ..., "final_response": "For a beach sunset on your Sony..." }
```

---

## Learning Concepts Implemented

### 1. Agent Orchestration (LangGraph)
- Creating agent nodes, defining edges, sequential execution, state passing

### 2. Vector Databases (ChromaDB)
- Text storage with metadata, embedding generation, similarity search, persistence
- **Metadata filtering** to partition one collection into logical sub-collections

### 3. Retrieval-Augmented Generation
- Chunking strategy and overlap
- Retrieve-once-share-many vs. per-agent retrieval
- Idempotent ingestion via deterministic IDs

### 4. LLM Integration (LangChain)
- ChatGroq initialization, message formatting, response handling

### 5. State Management
- TypedDict for type safety, state accumulation through the chain

### 6. Environment Management
- .env file usage, API key handling

---

## Customization Points

1. **Agent Prompts**: Modify prompt strings in agent functions
2. **Knowledge Base**: Add files to `documents/`, re-run `ingest_documents.py`
3. **Retrieval depth**: Change `k=4` in `supervisor_agent()`
4. **Chunk size**: `CHUNK_SIZE` / `CHUNK_OVERLAP` in `ingest_documents.py`
5. **Supported formats**: Extend the `LOADERS` dict in `ingest_documents.py`
6. **LLM Model**: Change model in ChatGroq initialization
7. **Workflow**: Modify graph edges for different flow
8. **Number of Agents**: Add/remove agent nodes

---

## Performance Characteristics

- **Startup Time**: ~2-3 seconds (embedding model load)
- **Ingestion**: ~1-2 s per 100 chunks on CPU (embedding is the bottleneck)
- **Retrieval**: milliseconds at this corpus size
- **Response Time**: ~5-10 seconds (three sequential Groq calls)
- **Memory Usage**: ~500MB (embeddings + ChromaDB)
- **Vector DB Size**: Grows with every chat turn (no automatic cleanup)

---

## Security Considerations

✅ **API Key Management**
- Stored in .env (not committed), loaded via python-dotenv

⚠️ **Vector DB**
- Local storage, not encrypted, accessible to any process
- Note that **every user query is written to the collection permanently** —
  do not type sensitive text into the chat loop

⚠️ **Ingested content**
- Document text is inserted into LLM prompts verbatim. Only ingest documents you trust.

---

## Future Enhancements

1. Pass `user_input` (and optionally `context`) to `response_generator`
2. Show retrieved sources in the answer for traceability
3. Delete-by-source before re-ingest, to fix the stale-chunk issue properly
4. Separate collections for documents vs. conversation history
5. Conversation memory across turns
6. Make the supervisor a real router (conditional edges) rather than a fixed chain
7. Parallel execution where agents are independent
8. Web interface (FastAPI + frontend)

---

## Files Modified/Created Timeline

1. **Initial**: `multiagent_chatbot.py` - Basic multi-agent structure
2. **Enhancement**: Added ChromaDB integration
3. **Improvement**: Fixed embedding function error with HuggingFaceEmbeddings
4. **Customization**: Modified for camera use case with Groq API
5. **Documentation**: Created documentation suite
6. **Ingestion**: Added `ingest_documents.py` + `documents/`; expanded `requirements.txt`
7. **RAG wiring**: Supervisor retrieval, `context` in state, both agent prompts updated,
   Agent 2's missing `analysis_1` fixed
8. **Documentation refresh**: All six docs updated to match the code as it now stands

---

## Getting Started Quick Reference

```bash
# 1. Install
pip install -r requirements.txt

# 2. Setup
# Create .env with GROQ_API_KEY

# 3. Add documents
# Copy camera manuals / photography guides into documents/

# 4. Ingest
python ingest_documents.py

# 5. Run
python multiagent_chatbot.py
```

---

## Conclusion

This multi-agent chatbot demonstrates modern LLM orchestration patterns, vector
database integration with metadata filtering, a reusable document ingestion
pipeline, and retrieval-augmented generation across a multi-agent chain. The
system is extensible to domains beyond photography by swapping the contents of
`documents/` and adjusting the agent prompts.
