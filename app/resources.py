"""Process-wide resources, built once and cached by Streamlit."""

import logging

import streamlit as st
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from app import camera_images as cams
from app import conversation_store as store
from app import observability as obs
from app.loaders import COLLECTION, PERSIST_DIR
from app.pipeline import build_graph

log = logging.getLogger(__name__)


@st.cache_resource(show_spinner="Loading the embedding model")
def get_embeddings():
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


@st.cache_resource(show_spinner=False)
def get_vector_store():
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=PERSIST_DIR,
    )


@st.cache_resource(show_spinner=False)
def get_graph():
    return build_graph(get_vector_store())


@st.cache_resource(show_spinner=False)
def log_operator_notices() -> None:
    """Deployment problems go to the server log, once — never to the reader."""
    if not store.is_durable() and obs.environment() != "local":
        log.warning("Transcripts are on ephemeral storage. Set DATABASE_URL to keep them.")
    for problem in cams.problems():
        log.warning(problem)
