# Multi-Agent Chatbot Documentation

## Overview
This is a multi-agent chatbot system built with LangGraph, ChromaDB, and Groq API. A supervisor node retrieves relevant material from a document corpus, then two specialized agents analyze the query in sequence and a response generator produces the final answer.

## Project Structure

```
Multi-Agent/
├── multiagent_chatbot.py      # Main chatbot application
├── ingest_documents.py        # Document ingestion script (folder → vector DB)
├── main.py                    # Early prototype, superseded — not part of the pipeline
├── documents/                 # Drop your PDFs / manuals / guides here
├── .env                       # Environment variables (Groq API key)
├── requirements.txt           # Python dependencies
├── chroma_langchain_db/       # Persisted vector database
└── Documentation/             # This folder
    ├── README.md             # Overview
    ├── ARCHITECTURE.md       # System architecture
    ├── SETUP.md              # Installation & setup guide
    ├── COMPONENTS.md         # Detailed component explanation
    ├── USAGE.md              # How to use the system
    └── IMPLEMENTATION_SUMMARY.md  # Full summary + change log
```

## Quick Start

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Setup Environment:**
   - Create `.env` file with your Groq API key
   - See `SETUP.md` for details

3. **Add Documents:**
   Copy camera manuals, photography guides, or any reference files into `documents/`.
   Supported: PDF, DOCX, CSV, HTML, TXT, MD, JSON, PY.

4. **Ingest Documents:**
   ```bash
   python ingest_documents.py
   ```

5. **Run Chatbot:**
   ```bash
   python multiagent_chatbot.py
   ```

## Key Features

✅ **Multi-Agent Architecture** - Sequential chain of specialized agents
✅ **Document Ingestion** - One command loads a whole folder into the vector DB
✅ **Retrieval-Augmented Generation** - Agents answer from your documents, not just model priors
✅ **Vector Database** - ChromaDB stores and retrieves document chunks
✅ **LangGraph** - Orchestrates agent workflow
✅ **Groq API** - Fast LLM inference
✅ **Data Persistence** - Chroma DB persists locally

## Technology Stack

- **LangGraph**: Agent workflow orchestration
- **ChromaDB**: Vector database for knowledge storage
- **Groq API**: LLM backend
- **Sentence Transformers**: Embedding model (all-MiniLM-L6-v2)
- **LangChain**: Core LLM abstractions
- **langchain-community / pypdf / docx2txt**: Document loaders

## Where to Read Next

- New to the project → `SETUP.md`
- Want to understand the flow → `ARCHITECTURE.md`
- Want line-by-line detail → `COMPONENTS.md`
- Want to use or customize it → `USAGE.md`
- Want the full change history → `IMPLEMENTATION_SUMMARY.md`
