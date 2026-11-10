"""Attached files → session context, and an attached photo → model-ready image."""

import base64
import io
import os
import tempfile

import numpy as np
import streamlit as st
from langchain_text_splitters import RecursiveCharacterTextSplitter
from PIL import ExifTags, Image, ImageOps

from app.loaders import load_file, CHUNK_SIZE, CHUNK_OVERLAP
from app.resources import get_embeddings
from app.settings import (MAX_CONTEXT_CHARS, MAX_ATTACHED_CHUNKS,
                          IMAGE_MAX_EDGE, IMAGE_JPEG_QUALITY)

FILE_TYPES = ["pdf", "docx", "doc", "csv", "html", "htm", "txt", "md", "json", "py"]

# EXIF fields that describe how the photo was taken. Everything else, GPS above
# all, is dropped: the photo is re-encoded without metadata before it is sent.
_EXIF_FIELDS = {
    "Make": "Camera make", "Model": "Camera", "LensModel": "Lens",
    "FocalLength": "Focal length", "FNumber": "Aperture", "ExposureTime": "Shutter",
    "ISOSpeedRatings": "ISO", "PhotographicSensitivity": "ISO",
    "ExposureBiasValue": "Exposure compensation", "ExposureProgram": "Mode",
    "MeteringMode": "Metering", "Flash": "Flash", "WhiteBalance": "White balance",
}
_EXPOSURE_PROGRAMS = {1: "Manual", 2: "Program", 3: "Aperture priority",
                      4: "Shutter priority"}
_METERING = {1: "Average", 2: "Center-weighted", 3: "Spot", 5: "Multi-segment",
             6: "Partial"}


def _format_exif(name: str, value) -> str:
    try:
        if name == "FNumber":
            return f"f/{float(value):g}"
        if name == "ExposureTime":
            t = float(value)
            return f"1/{round(1 / t)} s" if 0 < t < 1 else f"{t:g} s"
        if name == "FocalLength":
            return f"{float(value):g} mm"
        if name == "ExposureBiasValue":
            return f"{float(value):+.1f} EV"
        if name == "ExposureProgram":
            return _EXPOSURE_PROGRAMS.get(int(value), str(value))
        if name == "MeteringMode":
            return _METERING.get(int(value), str(value))
        if name == "Flash":
            return "Fired" if int(value) & 1 else "Did not fire"
        if name == "WhiteBalance":
            return "Manual" if int(value) == 1 else "Auto"
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return str(value).strip("\x00 ")


def _exif_summary(img: Image.Image) -> str:
    """The shooting settings recorded in the file, one per line, or ''."""
    exif = img.getexif()
    if not exif:
        return ""
    tags = dict(exif)
    tags.update(exif.get_ifd(ExifTags.IFD.Exif))   # aperture, shutter, ISO live here
    lines, seen = [], set()
    for tag_id, value in tags.items():
        name = ExifTags.TAGS.get(tag_id)
        label = _EXIF_FIELDS.get(name)
        if not label or label in seen or value in (None, ""):
            continue
        seen.add(label)
        lines.append(f"{label}: {_format_exif(name, value)}")
    return "\n".join(lines)


@st.cache_data(show_spinner=False)
def prepare_image(image_bytes: bytes) -> tuple[str, str]:
    """(data: URL of a downscaled, metadata-free JPEG, EXIF settings summary).

    Raises ValueError if the bytes are not an image Pillow can read.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        exif = _exif_summary(img)
        img = ImageOps.exif_transpose(img)        # honour the camera's rotation
    except Exception as exc:
        raise ValueError(f"Could not read the image: {exc}") from exc
    img.thumbnail((IMAGE_MAX_EDGE, IMAGE_MAX_EDGE))
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=IMAGE_JPEG_QUALITY)
    data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    return data_url, exif


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
