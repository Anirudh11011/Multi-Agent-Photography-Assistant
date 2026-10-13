"""Document loading shared by the ingestion CLI and the app's file attachments."""

import os

from langchain_community.document_loaders import (
    CSVLoader,
    Docx2txtLoader,
    PyPDFLoader,
    TextLoader,
    UnstructuredHTMLLoader,
)

PERSIST_DIR = "./chroma_langchain_db"
COLLECTION = "multi_agent_collection"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

LOADERS = {
    ".pdf": PyPDFLoader,
    ".docx": Docx2txtLoader,
    ".doc": Docx2txtLoader,
    ".csv": CSVLoader,
    ".html": UnstructuredHTMLLoader,
    ".htm": UnstructuredHTMLLoader,
    ".txt": TextLoader,
    ".md": TextLoader,
    ".json": TextLoader,
    ".py": TextLoader,
}


def load_file(path: str):
    """Load one file into LangChain Documents, or return [] if unsupported."""
    ext = os.path.splitext(path)[1].lower()
    loader_cls = LOADERS.get(ext)
    if loader_cls is None:
        print(f"  skipped (unsupported type): {path}")
        return []

    kwargs = {"encoding": "utf-8"} if loader_cls is TextLoader else {}
    try:
        return loader_cls(path, **kwargs).load()
    except Exception as exc:
        print(f"  failed: {path} -> {exc}")
        return []
