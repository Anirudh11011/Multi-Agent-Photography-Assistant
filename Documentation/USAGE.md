# Usage Guide

## Basic Usage

### Starting the Chatbot

```bash
python multiagent_chatbot.py
```

You'll see:
```
You:
```

### Asking Questions

```
You: What are the best camera settings for sunset photography on a Sony camera?
```

The system will:
1. Supervisor retrieves the 4 most relevant document chunks
2. Agent 1 analyzes the scene using those chunks
3. Agent 2 provides camera settings using the chunks + Agent 1's analysis
4. Response Generator combines the answer
5. You get a response

### Exiting

```
You: exit
```

---

## Adding Camera Knowledge

### The workflow

```bash
# 1. Drop files into the folder
cp ~/Downloads/nikon_z6_manual.pdf documents/

# 2. Re-ingest
python ingest_documents.py

# 3. Ask about it
python multiagent_chatbot.py
```

No code changes needed — the ingester writes into the same collection the chatbot reads.

### Ingesting from a different folder

```bash
python ingest_documents.py ~/Documents/camera-manuals
```

### After editing a document

Chunk IDs are content hashes, so an edited file creates *new* chunks while the old
ones linger and can still be retrieved. Rebuild cleanly:

```bash
python ingest_documents.py --reset
```

Note `--reset` wipes the whole collection, including stored chat history.

### Supported formats

`.pdf`, `.docx`, `.doc`, `.csv`, `.html`, `.htm`, `.txt`, `.md`, `.json`, `.py`

To add another format, extend the `LOADERS` dict in `ingest_documents.py`:

```python
LOADERS = {
    ...
    ".epub": UnstructuredEPubLoader,   # remember to import it
}
```

---

## Querying the Vector Database Directly

Useful for debugging what the agents will actually see.

```python
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
vector_store = Chroma(
    collection_name="multi_agent_collection",
    embedding_function=embeddings,
    persist_directory="./chroma_langchain_db",
)

query = "sunset at beach, sony camera"

# Exactly what the supervisor does
for doc in vector_store.similarity_search(query, k=4, filter={"type": "ingested_document"}):
    print(f"- [{doc.metadata['source']}] {doc.page_content[:120]}...")
```

### Seeing relevance scores

```python
for doc, distance in vector_store.similarity_search_with_score(
        query, k=4, filter={"type": "ingested_document"}):
    print(f"{distance:.3f}  {doc.metadata['source']:30}  {doc.page_content[:70]}")
```

Lower distance = closer match. Example output from a 5-document test corpus:

```
0.619  beach_sunset_guide.txt          Photographing Sunsets at the Beach...
0.993  sony_a7iv_manual.txt            Sony Alpha A7 IV Instruction Manual...
1.150  forest_guide.txt                Photographing Forests and Woodland...
1.301  bird_guide.txt                  Wildlife and Bird Photography Settings...
```

Note that ranks 3 and 4 are irrelevant but still get passed to the agents — `k=4`
always returns 4 chunks, with no relevance cutoff.

---

## Tuning Retrieval

### Retrieve more or fewer chunks

`multiagent_chatbot.py`, in `supervisor_agent()`:

```python
docs = vector_store.similarity_search(state["user_input"], k=8,   # was 4
                                      filter={"type": "ingested_document"})
```

Raise `k` when questions span two topics (a scene *and* a camera model) and one
half is getting crowded out. Costs prompt tokens.

### Change chunk size

`ingest_documents.py`:

```python
CHUNK_SIZE = 500      # smaller = more precise matches, less surrounding context
CHUNK_OVERLAP = 100
```

Requires a full re-ingest with `--reset` to take effect.

### Add a relevance cutoff

```python
results = vector_store.similarity_search_with_score(
    state["user_input"], k=6, filter={"type": "ingested_document"})
docs = [d for d, dist in results if dist < 1.2]
state["context"] = "\n\n".join(d.page_content for d in docs)
```

Drops weak matches instead of padding the prompt with them.

### Tag documents by category for filtered retrieval

At ingest time, in `ingest_documents.py`:

```python
doc.metadata["category"] = "manual" if "manual" in path.lower() else "guide"
```

Then retrieve both halves of a mixed question separately:

```python
scene = vector_store.similarity_search(q, k=3, filter={"category": "guide"})
model = vector_store.similarity_search(q, k=3, filter={"category": "manual"})
state["context"] = "\n\n".join(d.page_content for d in scene + model)
```

This guarantees both the scene guidance and the camera manual are represented,
which a single unfiltered `k=4` search does not.

---

## Modifying Agent Behavior

### Changing Agent 1 Behavior

Edit `multiagent_chatbot.py`, function `agent_1()`:

```python
def agent_1(state: AgentState) -> AgentState:
    prompt = (
        f"Your new system prompt here.\n\n"
        f"Reference documents:\n{state['context']}\n\n"
        f"Analyze: {state['user_input']}"
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    state["analysis_1"] = response.content
    # ... rest of code
```

Keep the `{state['context']}` interpolation, or the agent loses access to your documents.

### Grounding the agents more strictly

To stop the model answering from its own priors:

```python
prompt = (
    f"Answer ONLY from the reference documents below. "
    f"If they do not cover it, say so explicitly.\n\n"
    f"Reference documents:\n{state['context']}\n\n"
    f"Question: {state['user_input']}"
)
```

### Giving the Response Generator the original question

Currently it sees only the two analyses. To close that gap, edit `response_generator()`:

```python
prompt = f"""The user asked: {state["user_input"]}

Based on these analyses, generate a response:

Analysis 1: {state["analysis_1"]}
Analysis 2: {state["analysis_2"]}

Provide a final answer."""
```

### Showing sources in the answer

In `supervisor_agent()`, keep the source names:

```python
state["context"] = "\n\n".join(
    f"[{d.metadata.get('source','?')}]\n{d.page_content}" for d in docs
)
```

Then the agents can cite which manual a setting came from.

---

## Changing LLM Model

Edit `multiagent_chatbot.py`:

```python
llm = ChatGroq(
    model="openai/gpt-oss-120b",  # change this
    api_key=groq_api_key
)
```

Check https://console.groq.com/docs/models for the current model list — available
model IDs change over time.

---

## Debugging

### View What's in the Vector DB

```python
# Save as debug_db.py
from collections import Counter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
vector_store = Chroma(
    collection_name="multi_agent_collection",
    embedding_function=embeddings,
    persist_directory="./chroma_langchain_db",
)

all_docs = vector_store.get()
print(f"Total entries: {len(all_docs['ids'])}")
print(Counter(m.get("type", "?") for m in all_docs["metadatas"]))
print(Counter(m.get("source", "-") for m in all_docs["metadatas"]
              if m.get("type") == "ingested_document"))
```

Run:
```bash
python debug_db.py
```

This tells you how many chunks came from each source file — the fastest way to
confirm a particular manual actually made it in.

### Print the retrieved context each turn

Add to `supervisor_agent()`:

```python
print(f"\n[retrieved {len(docs)} chunks: "
      f"{[d.metadata.get('source') for d in docs]}]\n")
```

### Enable Verbose Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Examples

### Example 1: Beach Sunset

```
You: I have to take a photo of sunset at beach, give camera settings for sony camera
```

What happens internally:
- Supervisor retrieves the beach sunset guide (closest match) and the Sony manual
  section (second closest), plus two weaker matches
- Agent 1 analyzes: high dynamic range, sky 8-10 stops brighter than foreground
- Agent 2 combines the scene analysis with the Sony-specific menu paths
- Response Generator produces the final settings list

### Example 2: Adding a New Camera

```bash
cp ~/Downloads/nikon_z8_manual.pdf documents/
python ingest_documents.py
python multiagent_chatbot.py
```
```
You: settings for astrophotography on a nikon z8
```

---

## Performance Tips

1. **Vector DB Size**: More data = slower searches, and more competition for the
   `k` retrieval slots. Keep only relevant documents.
2. **Chat history accumulates**: every query and both agent outputs are written to
   the collection on every turn. They're filtered out of retrieval, but the DB grows.
   Periodic `--reset` + re-ingest keeps it lean.
3. **Embedding Model**: larger models are more accurate but slower
4. **Ingestion is CPU-bound** on embedding — a large PDF corpus takes a few minutes
5. **Three LLM calls per query**: response time is dominated by these

---

## Troubleshooting

### Agents giving generic responses
- Confirm documents are actually ingested (`debug_db.py` above)
- Raise `k` in `supervisor_agent()`
- Use a stricter grounding prompt (see "Grounding the agents more strictly")
- Check the retrieved chunks are on-topic by printing them

### Bot cites outdated information
Old chunks from an edited document are still in the DB. Run
`python ingest_documents.py --reset`.

### Slow responses
- Check Groq API rate limits
- Try a smaller/faster model

### Vector DB errors
```bash
rm -rf ./chroma_langchain_db/
python ingest_documents.py
```

---

## Next Steps

1. Fill `documents/` with your real manuals and guides
2. Tune `k` and chunk size for your corpus
3. Modify agent prompts for your use case
4. Add category metadata for filtered retrieval
5. Add more agents for different specialties
