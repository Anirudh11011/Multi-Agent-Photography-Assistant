# Usage Guide

## Basic Usage

### Starting the App

```bash
streamlit run streamlit_app.py
```

Opens at `http://localhost:8501`. Stop it with `Ctrl+C` in the terminal.

### Asking Questions

Type into the chat box at the bottom:

```
What are the best camera settings for sunset photography on a Sony camera?
```

What happens internally:

1. **gather_context** loads the first rung — your attached files if any, otherwise a
   similarity search over the archive
2. **supervisor** grades that material: does it actually answer the question?
3. If **rejected**, the next rung is tried (archive, then web) and graded again
4. If **approved**, Agent 1 analyzes the scene, Agent 2 produces settings, and the
   Response Generator combines them
5. If every rung is rejected, you get an explicit "I don't have relevant information"

### Reading an Answer

Each answer carries two pieces of provenance:

- **The badge** — `Context · attached files`, `Context · archive search`,
  `Context · web search`, or `Context · none found`
- **The Agent trace** expander — every rung tried, the passages it produced with their
  relevance scores, the supervisor's verdict at each rung, and each agent's output

When a rung is rejected the trace shows why, in the supervisor's own words. This is the
fastest way to understand any surprising answer.

### The Sidebar

**Context** — drag files in to answer from them. They are tried *before* the archive,
graded like any other source, and discarded when the session ends. Nothing is written
to the vector database.

**Recent chats** — conversations from this browser session, newest first, titled from
their first question. `›` marks the current one. "New conversation" starts a fresh
thread. Chats do not survive a server restart.

---

## Adding Camera Knowledge

### Permanently (into the archive)

```bash
# 1. Drop files into the folder
cp ~/Downloads/nikon_z6_manual.pdf documents/

# 2. Re-ingest
python ingest_documents.py

# 3. Ask about it in the app
```

No code changes needed — the ingester writes into the same collection the app reads.
If the app is already running, restart it so the vector store handle is rebuilt.

### Temporarily (for one conversation)

Drop the file into the sidebar **Context** box. Nothing is ingested, nothing persists.
Use this for a one-off manual you don't want permanently in your corpus.

### Ingesting from a different folder

```bash
python ingest_documents.py ~/Documents/camera-manuals
```

### After editing a document

Chunk IDs are content hashes, so an edited file creates *new* chunks while the old ones
linger and can still be retrieved. Rebuild cleanly:

```bash
python ingest_documents.py --reset
```

Note `--reset` wipes the whole collection, including any legacy chat entries.

### Supported formats

`.pdf`, `.docx`, `.doc`, `.csv`, `.html`, `.htm`, `.txt`, `.md`, `.json`, `.py`

The sidebar accepts exactly the same list — it reuses `load_file` from
`ingest_documents.py`. To add another format, extend the `LOADERS` dict there and both
paths gain it at once:

```python
LOADERS = {
    ...
    ".epub": UnstructuredEPubLoader,   # remember to import it
}
```

---

## Testing the Three Paths

A quick way to confirm everything works. Adjust the questions to your own corpus.

**Should answer from the archive** — ask about something you know is in your documents:
```
What aperture should I use for mountain landscapes with the Canon R5?
```
Expect: `Context · archive search`, supervisor verdict `YES`.

**Should escalate to the web** — same subject, a detail your documents omit:
```
How many megapixels is the Canon R5 sensor?
```
Expect: the archive rung rejected in the trace, then `Context · web search`. This is the
most informative test — it exercises the supervisor *and* the fallback.

**Should refuse instantly** — completely off-topic:
```
How do I bake sourdough bread at home?
```
Expect: `Context · none found` in well under a second. Nothing scores above the
relevance floor, so no LLM call is made at all. If this takes ten seconds, your floor is
too low.

**Should use attachments** — save a file about a camera *not* in your archive, drop it
in the Context box, and ask about it. Expect `Context · attached files` and no
supervisor step for the archive. Then remove the file and ask again — it should
escalate to web or refuse.

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

# Exactly what the retrieved rung does
hits = vector_store.similarity_search_with_relevance_scores(
    query, k=4, filter={"type": "ingested_document"})
for doc, score in hits:
    print(f"{score:.3f}  {doc.metadata['source']:30}  {doc.page_content[:70]}")
```

**Higher score = closer match** (note this is the inverse of raw distance). Measured
against a two-document corpus:

```
 0.433  sample_notes.txt        The Sony A7 IV is a full-frame mirrorless camera...
 0.203  canon_r5_notes.txt      Canon EOS R5 landscape guide...
-0.264  (off-topic query)       …scores go negative for unrelated text
```

Scores below `RELEVANCE_FLOOR` (0.25) are dropped before the supervisor ever sees them.

### Seeing what is actually retrievable

The raw collection count is misleading — it includes chat entries written by the legacy
CLI, which are filtered out of retrieval. Count only real documents:

```python
import chromadb
col = chromadb.PersistentClient(path="./chroma_langchain_db") \
              .get_collection("multi_agent_collection")
r = col.get(where={"type": "ingested_document"}, include=["metadatas", "documents"])
print(len(r["documents"]), "retrievable chunks")
for m, d in zip(r["metadatas"], r["documents"]):
    print(f"[{m['source']}] {d[:80]}")
```

---

## Tuning the Gates

The two gates catch different failures. Tune them separately.

### The relevance floor (cheap gate)

`streamlit_app.py`, line 51:

```python
RELEVANCE_FLOOR = 0.25
```

- **Too high** → good chunks are discarded and everything escalates to the web
- **Too low** → junk reaches the supervisor, costing an LLM call to reject it

This value is **corpus-specific and embedding-specific**. Re-calibrate by running a few
known-good and known-bad queries through the snippet above and picking a number that
separates them. Do this again after a large ingest or an embedding-model change.

### The supervisor prompt (smart gate)

`streamlit_app.py`, lines ~155–163. The key sentence controls strictness:

```python
"Partial but genuinely on-topic material counts as sufficient; material that is "
"merely on a related subject does not."
```

- **Too strict** → useful partial answers get rejected and escalate unnecessarily
- **Too lenient** → the agents answer from material that doesn't really cover the
  question, which is the failure the gate exists to prevent

If you loosen this, watch the "battery life" style of question — on-topic document,
missing detail — since that is exactly what a lenient grader lets through.

### Retrieve more or fewer chunks

```python
TOP_K = 4        # line 50
```

Raise it when questions span two topics (a scene *and* a camera model) and one half is
getting crowded out. Costs prompt tokens.

### Change chunk size

`ingest_documents.py`:

```python
CHUNK_SIZE = 500      # smaller = more precise matches, less surrounding context
CHUNK_OVERLAP = 100
```

Requires a full re-ingest with `--reset` to take effect. The app imports these constants,
so attachment chunking follows automatically.

### Tag documents by category for filtered retrieval

At ingest time, in `ingest_documents.py`:

```python
doc.metadata["category"] = "manual" if "manual" in path.lower() else "guide"
```

Then retrieve both halves of a mixed question separately, in `gather_context`:

```python
scene = store.similarity_search(q, k=3, filter={"category": "guide"})
model = store.similarity_search(q, k=3, filter={"category": "manual"})
```

This guarantees both the scene guidance and the camera manual are represented, which a
single unfiltered `k=4` search does not.

---

## Tuning the Web Fallback

### More or fewer results

```python
WEB_RESULTS = 5        # line 55
```

### Disabling the web rung entirely

In the main column, drop `"web"` from the ladder:

```python
stages = (["attached"] if attached_context else []) + ["retrieved"]
```

Questions your documents can't answer will then refuse instead of searching — the
behaviour before the fallback was added.

### Always searching the web alongside your documents

The ladder is deliberately ordered so your own documents win when they are sufficient.
If you want the web consulted every time, put it first (`["web", "retrieved"]`) or merge
both into one context in `gather_context`. Be aware that merging removes the clean
provenance the badge and source note currently give you.

### Swapping the search engine

Replace the body of `web_search()` (line 76). Anything returning title/URL/snippet text
works — the supervisor grades whatever comes back. Keep the `__SEARCH_FAILED__` sentinel
on error so a failure degrades to a refusal instead of crashing.

---

## Modifying Agent Behavior

### Changing Agent 1

Edit `streamlit_app.py`, function `agent_1()` (line 181):

```python
def agent_1(state: AgentState) -> AgentState:
    prompt = (
        f"Your new system prompt here.\n\n"
        f"Reference documents:\n{state['context']}\n\n"
        f"Analyze: {state['user_input']}"
    )
    state["analysis_1"] = llm.invoke([HumanMessage(content=prompt)]).content
    return state
```

Keep the `{state['context']}` interpolation, or the agent loses access to the material
the supervisor just approved.

> The same prompts also exist in `multiagent_chatbot.py`. Editing one does **not**
> change the other.

### Grounding the agents more strictly

The supervisor already blocks unsupported questions, so the agents rarely see irrelevant
material. To also stop them padding from model priors:

```python
prompt = (
    f"Answer ONLY from the reference documents below. "
    f"If they do not cover part of the question, say so explicitly.\n\n"
    f"Reference documents:\n{state['context']}\n\n"
    f"Question: {state['user_input']}"
)
```

### Giving the Response Generator the original question

It currently sees only the two analyses plus the source note. To close that gap, edit
`response_generator()` (line 202):

```python
prompt = (
    f"The user asked: {state['user_input']}\n\n"
    "Based on these analyses, generate a response:\n\n"
    f"Analysis 1: {state['analysis_1']}\n\n"
    f"Analysis 2: {state['analysis_2']}\n\n"
    f"{note}\n\nProvide a final answer."
)
```

### Showing document sources in the answer

Retrieved chunks are currently prefixed with their relevance score. To carry filenames
through as well, in `gather_context`:

```python
state["context"] = "\n\n".join(
    f"[{d.metadata.get('source','?')} · relevance {s:.2f}]\n{d.page_content}"
    for d, s in kept
)
```

Then the agents can cite which manual a setting came from. Attached files and web
results already carry `[filename]` and `[web]` labels.

---

## Changing the LLM Model

`streamlit_app.py`, line 48:

```python
MODEL_NAME = "openai/gpt-oss-120b"
TEMPERATURE = 0.7
```

Check https://console.groq.com/docs/models for the current list — available model IDs
change over time. The supervisor uses the same model as the agents; if you want a
cheaper grader, build a second `ChatGroq` instance inside `get_graph()` and use it in
`supervisor()` only.

---

## Customizing the Look

All styling lives in `vintage_theme.py`. `streamlit_app.py` emits no HTML.

| To change | Edit |
|---|---|
| Colors | The palette constants at the top (lines 10–16) |
| Fonts, spacing, borders | The `_CSS` block (line 35) |
| Title and subtitle | `masthead()` (line 200) |
| Step names in the trace | `STEP_LABELS` (line 24) |
| Chat avatars | `USER_AVATAR` / `BOT_AVATAR` (lines 21–22) |
| Widget chrome before CSS loads | `.streamlit/config.toml` |

The palette is defined once as Python constants and interpolated into the CSS, so
changing `SEPIA` updates every element that uses it.

---

## Debugging

### Read the Agent trace first

Almost every "why did it answer that?" question is answered by the trace: which rungs
were tried, what each returned, and the supervisor's verdict on each. Start there before
adding print statements.

### Run the pipeline headlessly

Streamlit's test harness runs the whole app without a browser — useful for scripted
checks:

```python
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("streamlit_app.py", default_timeout=600)
at.run()
at.chat_input[0].set_value("What are the landscape settings for the Sony A7 IV?").run()

turn = at.session_state.chats[at.session_state.current]["history"][0]
print("source:", turn["source"])
print("path:", " → ".join(n for n, _ in turn["steps"]))
print("answer:", turn["answer"][:200])
```

`turn["steps"]` is the same data the trace expander renders, so you can assert on the
routing directly.

### Inspect the graph without the UI

```python
import importlib.util
spec = importlib.util.spec_from_file_location("app", "streamlit_app.py")
app = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(app)
except Exception:
    pass   # Streamlit calls fail outside `streamlit run`; the functions still load

out = app.get_graph().invoke({
    "user_input": "astro settings for the X-T5", "attached_context": "",
    "context": "", "source": "", "stages": ["retrieved", "web"], "stage": 0,
    "approved": False, "verdict": "", "attempts": [],
    "analysis_1": "", "analysis_2": "", "final_response": "",
})
print(out["source"])
for src, verdict in out["attempts"]:
    print(f"{src}: {verdict}")
```

`attempts` gives the full ladder history in one place. You can also pass a custom
`stages` list to test a single rung in isolation.

### Enable verbose logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Examples

### Example 1: Answered from your documents

```
What aperture should I use for mountain landscapes with the Canon R5?
```

- `gather_context` retrieves the Canon R5 note (relevance 0.43)
- `supervisor`: *YES — the passage gives specific landscape settings*
- Agent 1 analyzes the scene; Agent 2 produces the settings; the Editor combines them
- Badge: **Context · archive search**, ~11 s

### Example 2: Escalated to the web

```
How many megapixels is the Canon R5 sensor?
```

- `gather_context` finds nothing above the floor
- `supervisor`: rejected without an LLM call → next rung
- `gather_context` searches DuckDuckGo; `supervisor`: *YES*
- Answer states it came from a web search and cites URLs
- Badge: **Context · web search**, ~45 s

### Example 3: Attachment rejected, escalated

A file about the Fujifilm X-T5 is attached, but the question is about a Nikon:

```
What is the battery life of the Nikon Z9?
```

- `attached` rung: *NO — the passage discusses the Fujifilm X-T5 and contains no
  information about the Nikon Z9's battery life*
- `retrieved` rung: nothing above the floor
- `web` rung: approved → answered

The attachment being present did not force an answer out of the wrong document.

### Example 4: Honest refusal

```
How do I bake sourdough bread at home?
```

Nothing above the floor, nothing from the web → "I don't have relevant information to
answer that — not in the attached files, not in the archive, and not from a web search."

---

## Performance Tips

1. **The first question is slow** — the embedding model loads on demand, then is cached
   for the life of the server.
2. **Escalation costs time.** An archive hit is ~11 s; a full escalation to the web is
   ~45 s, because each rung adds a supervisor call and the winning rung still runs the
   full three-agent chain.
3. **Off-topic questions are free.** The relevance floor rejects them with no LLM call.
4. **Attachments are parsed once** — `@st.cache_data` keys on file content, so follow-up
   questions against the same files skip parsing.
5. **Large attachments are ranked, not truncated** — only the 12 most relevant chunks,
   within 12000 characters, reach the model.
6. **The database no longer grows per turn.** The app writes nothing back to ChromaDB;
   only `ingest_documents.py` adds to it.
7. **Keep the corpus relevant.** More documents means more competition for the `k`
   retrieval slots.

---

## Troubleshooting

### Everything escalates to the web
Your archive is probably smaller than you think, or the relevance floor is too high.
Count retrievable chunks (see "Seeing what is actually retrievable") and check the
scores in the trace.

### The supervisor rejects things it shouldn't
Loosen the wording in the supervisor prompt, or lower `RELEVANCE_FLOOR` if good chunks
are being dropped before it ever sees them. The trace tells you which of the two is
happening.

### Answers cite outdated information
Old chunks from an edited document are still in the DB. Run
`python ingest_documents.py --reset`.

### Slow responses
- Check whether the trace shows a full escalation (three rungs = six LLM calls)
- Check Groq API rate limits
- Try a smaller/faster model

### Recent chats disappeared
They live in the browser session only. A server restart or a fresh session clears them.

### Vector DB errors
```bash
rm -rf ./chroma_langchain_db/
python ingest_documents.py
```

---

## Next Steps

1. Fill `documents/` with your real manuals and guides
2. Re-calibrate `RELEVANCE_FLOOR` against that larger corpus
3. Tune the supervisor prompt for how strict you want the gate
4. Modify agent prompts for your use case
5. Add category metadata for filtered retrieval
6. Consider persisting recent chats to disk if you want them across restarts
