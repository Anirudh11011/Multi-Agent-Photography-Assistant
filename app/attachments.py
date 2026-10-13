"""Attached files → session context."""

import os
import tempfile

import numpy as np
import streamlit as st
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.loaders import load_file, CHUNK_SIZE, CHUNK_OVERLAP
from app.resources import get_embeddings
from app.settings import MAX_CONTEXT_CHARS, MAX_ATTACHED_CHUNKS

FILE_TYPES = ["pdf", "docx", "doc", "csv", "html", "htm", "txt", "md", "json", "py"]


@st.cache_data(show_spinner=False)
def extract_chunks(file_bytes: bytes, filename: str) -> list[str]:
    """Parse an uploaded file into text chunks. Cached on content + name."""
    suffix = os.path.splitext(filename)[1] or ".txt"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        path = tmp.name
    try:
        docs = load_file(path)
    finally:
        os.unlink(path)
    if not docs:
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    return [c.page_content for c in splitter.split_documents(docs)]


def build_attached_context(files, question: str) -> str:
    """Rank the attached files' chunks against the question, within a budget.

    Session-scoped: nothing here is written to the persistent vector store.
    """
    chunks, labels = [], []
    for up in files:
        for text in extract_chunks(up.getvalue(), up.name):
            chunks.append(text)
            labels.append(up.name)
    if not chunks:
        return ""

    joined = "\n\n".join(f"[attached file: {lab}]\n{c}" for lab, c in zip(labels, chunks))
    if len(joined) <= MAX_CONTEXT_CHARS:
        return joined

    emb = get_embeddings()
    doc_vecs = np.array(emb.embed_documents(chunks), dtype=np.float32)
    q_vec = np.array(emb.embed_query(question), dtype=np.float32)
    doc_vecs /= np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-9
    q_vec /= np.linalg.norm(q_vec) + 1e-9
    order = np.argsort(-(doc_vecs @ q_vec))[:MAX_ATTACHED_CHUNKS]

    picked, used = [], 0
    for i in order:
        block = f"[attached file: {labels[i]}]\n{chunks[i]}"
        if used + len(block) > MAX_CONTEXT_CHARS:
            break
        picked.append(block)
        used += len(block)
    return "\n\n".join(picked)
