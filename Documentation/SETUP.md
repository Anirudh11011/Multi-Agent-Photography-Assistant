# Setup & Installation Guide

## Prerequisites
- Python 3.8 or higher
- pip package manager
- Groq API key (free signup at https://console.groq.com)

## Step 1: Install Dependencies

```bash
pip install -r requirements.txt
```

### Required Packages:

**Core:**
- `langchain-groq` - Groq LLM integration
- `langgraph` - Agent workflow orchestration
- `sentence-transformers` - Embedding model
- `langchain-chroma` - ChromaDB vector store
- `langchain-huggingface` - HuggingFace embeddings
- `python-dotenv` - Environment variable management

**Document ingestion:**
- `langchain-community` - Document loaders
- `langchain-text-splitters` - Chunking
- `pypdf` - PDF parsing
- `docx2txt` - Word document parsing
- `unstructured` - HTML parsing (large; see note below)

> **Note on `unstructured`**: it is listed in `requirements.txt` but is a large
> dependency and is **not installed** in the project's `venv/`. Everything except
> HTML ingestion works without it. Install it only if you need `.html`/`.htm` support:
> ```bash
> pip install unstructured
> ```

## Step 2: Setup Environment Variables

Create a `.env` file in the project root:

```bash
touch .env
```

Add your Groq API key:

```
GROQ_API_KEY=your_groq_api_key_here
```

**How to get Groq API key:**
1. Go to https://console.groq.com
2. Sign up for a free account
3. Generate an API key
4. Copy and paste it in `.env`

## Step 3: Add Your Documents

Put your source material into the `documents/` folder:

```bash
cp ~/Downloads/sony_a7iv_manual.pdf documents/
cp ~/Downloads/beach_sunset_guide.pdf documents/
```

Subfolders are supported — the ingester walks the tree recursively.
Hidden files and hidden directories are skipped.

**Supported formats**: `.pdf`, `.docx`, `.doc`, `.csv`, `.html`, `.htm`, `.txt`,
`.md`, `.json`, `.py`. Anything else is skipped with a message.

## Step 4: Ingest Documents into the Vector Database

```bash
python ingest_documents.py
```

Output looks like:
```
Found 3 file(s) in /Users/you/Multi-Agent/documents

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

Re-running on an unchanged folder is safe — chunk IDs are content hashes, so
nothing is duplicated. **However**, if you *edit* a document, the old chunks stay
behind. Use `--reset` after editing source files.

## Step 5: Verify Installation

```bash
python multiagent_chatbot.py
```

Then input a test query:
```
You: What are the best camera settings for sunset photography?
```

Expected output:
```
Bot: [Multi-agent response with analysis and camera settings]
```

To confirm the answer is actually coming from *your* documents, ask about a detail
that only appears in one of your files. If it comes back correctly, retrieval is working.

## Troubleshooting

### ModuleNotFoundError
```bash
pip install --upgrade -r requirements.txt
```

### "No module named 'langchain_groq'"
```bash
pip install langchain-groq
```

### Bot ignores your documents / gives generic answers
1. Confirm the collection actually has document chunks:
   ```python
   from langchain_chroma import Chroma
   from langchain_huggingface import HuggingFaceEmbeddings
   emb = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
   vs = Chroma(collection_name="multi_agent_collection",
               embedding_function=emb, persist_directory="./chroma_langchain_db")
   print(vs.get(where={"type": "ingested_document"})["ids"][:5])
   ```
   An empty list means ingestion never ran or wrote elsewhere.
2. Check the collection name and persist directory match between
   `ingest_documents.py` and `multiagent_chatbot.py`.
3. Check the embedding model matches in both files — mismatched models produce
   incomparable vectors and garbage retrieval.

### PDF loads as 0 pages
Scanned/image-only PDFs have no text layer. `pypdf` extracts nothing from them.
You'd need OCR (e.g. `unstructured` with OCR extras, or a separate OCR pass).

### ChromaDB errors
```bash
# Delete old database and recreate
rm -rf ./chroma_langchain_db/
python ingest_documents.py
```

### Groq API authentication error
- Verify `.env` file has correct API key
- Check API key is valid at https://console.groq.com
- Ensure no trailing spaces in API key

## Directory Structure After Setup

```
Multi-Agent/
├── multiagent_chatbot.py
├── ingest_documents.py
├── main.py                   # early prototype, unused
├── documents/                # ← your source files here
│   └── sony_a7iv_manual.pdf
├── .env                      # ← your Groq API key here
├── requirements.txt
├── chroma_langchain_db/      # ← created/populated by ingest_documents.py
│   └── (vector database files)
├── venv/
└── Documentation/
```

## Optional: Virtual Environment

Recommended for project isolation:

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

This project already has a `venv/`. To use it without activating:

```bash
./venv/bin/python ingest_documents.py
./venv/bin/python multiagent_chatbot.py
```

## Next Steps

- See `COMPONENTS.md` to understand each component
- See `ARCHITECTURE.md` for how retrieval behaves and its limits
- See `USAGE.md` for advanced usage and customization
