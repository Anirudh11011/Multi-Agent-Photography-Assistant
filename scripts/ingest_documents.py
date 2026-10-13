"""Ingest every document in a folder into the Chroma vector store.

Usage:
    python scripts/ingest_documents.py                 # ingests ./documents
    python scripts/ingest_documents.py path/to/folder
    python scripts/ingest_documents.py --reset         # wipe the collection first

Run from the project folder: the vector store path is relative to it.
"""

import argparse
import hashlib
import os
import sys

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Make the app package importable when run as `python scripts/ingest_documents.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.loaders import (  # noqa: E402  (after the path fix)
    load_file, COLLECTION, PERSIST_DIR, CHUNK_SIZE, CHUNK_OVERLAP,
)

DOCS_DIR = "./documents"


def collect_files(folder: str):
    """Every file under folder, recursively, ignoring hidden files."""
    found = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in sorted(files):
            if not name.startswith("."):
                found.append(os.path.join(root, name))
    return found


def chunk_id(chunk) -> str:
    """Stable id from source + content, so re-running does not duplicate."""
    source = chunk.metadata.get("source", "")
    digest = hashlib.sha256(f"{source}::{chunk.page_content}".encode()).hexdigest()
    return digest[:32]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="?", default=DOCS_DIR,
                        help=f"folder holding the documents (default: {DOCS_DIR})")
    parser.add_argument("--reset", action="store_true",
                        help="delete the existing collection before ingesting")
    args = parser.parse_args()

    folder = os.path.abspath(args.folder)
    if not os.path.isdir(folder):
        sys.exit(f"Folder not found: {folder}")

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )
    vector_store = Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings,
        persist_directory=PERSIST_DIR,
    )

    if args.reset:
        vector_store.reset_collection()
        print(f"Reset collection '{COLLECTION}'.")

    files = collect_files(folder)
    if not files:
        sys.exit(f"No files found in {folder}")
    print(f"Found {len(files)} file(s) in {folder}\n")

    documents = []
    for path in files:
        docs = load_file(path)
        if docs:
            print(f"  loaded {len(docs):>3} page(s)/section(s): {os.path.relpath(path, folder)}")
            for doc in docs:
                doc.metadata["source"] = os.path.relpath(path, folder)
                doc.metadata["type"] = "ingested_document"
            documents.extend(docs)

    if not documents:
        sys.exit("\nNothing could be loaded.")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        add_start_index=True,
    )
    chunks = splitter.split_documents(documents)

    # Deduplicate within this run, then let matching ids overwrite prior runs.
    unique = {}
    for chunk in chunks:
        unique[chunk_id(chunk)] = chunk

    ids = list(unique.keys())
    payload = list(unique.values())
    print(f"\nEmbedding {len(payload)} chunk(s)...")

    batch = 100
    for i in range(0, len(payload), batch):
        vector_store.add_documents(documents=payload[i:i + batch], ids=ids[i:i + batch])
        print(f"  stored {min(i + batch, len(payload))}/{len(payload)}")

    print(f"\nDone. Collection '{COLLECTION}' now holds "
          f"{vector_store._collection.count()} chunk(s) in {PERSIST_DIR}")


if __name__ == "__main__":
    main()
