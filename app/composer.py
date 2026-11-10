"""The input bar: a "+" menu (Doc upload, Image upload) beside the chat input.

Documents are session-wide, as the sidebar uploader was: they apply to every
conversation until removed. The image belongs to one conversation and there is
only ever one: once attached, image upload is disabled for that conversation.
It can be removed until the first question about it is sent; after that it is
locked in, so every later answer in the conversation is about the same photo.
A new conversation starts with image upload enabled again.
"""

import streamlit as st

from app.attachments import FILE_TYPES, prepare_image
from app.settings import IMAGE_TYPES

PLACEHOLDER = "Describe your scene and camera"
IMAGE_PLACEHOLDER = "Ask about your photo"


def _uploader_key(cid: str) -> str:
    # A fresh key gives an empty uploader: used after the image is taken out of
    # it, and after the image is removed so the same file can be picked again.
    nonce = st.session_state.setdefault("image_upload_nonce", 0)
    return f"image-upload-{cid}-{nonce}"


def _take_image(chat: dict, key: str) -> None:
    """Move a newly uploaded image from the uploader onto the conversation."""
    up = st.session_state.get(key)
    if up is None:
        return
    data = up.getvalue()
    try:
        prepare_image(data)            # reject anything that isn't a readable image
    except ValueError:
        st.session_state.image_error = f"{up.name} couldn't be read as an image."
        return
    chat["image"] = {"name": up.name, "bytes": data, "locked": False}
    st.session_state.image_error = None
    st.session_state.image_upload_nonce += 1


def _remove_image(chat: dict) -> None:
    chat.pop("image", None)
    st.session_state.image_upload_nonce += 1


def _image_preview(chat: dict) -> None:
    image = chat["image"]
    with st.container(key="image-preview", horizontal=True,
                      vertical_alignment="center", gap="small"):
        st.image(image["bytes"], width=52)
        st.markdown(f'<span class="image-preview-name">{image["name"]}</span>',
                    unsafe_allow_html=True)
        if not image["locked"]:
            st.button("Remove image", key=f"rm-image-{st.session_state.current}",
                      icon=":material/close:", type="tertiary",
                      on_click=_remove_image, args=(chat,))


def render(chat: dict) -> tuple[list, str | None]:
    """Draw the input bar pinned to the bottom. Returns (documents, prompt)."""
    cid = st.session_state.current
    has_image = bool(chat.get("image"))

    with st.bottom:
        if has_image:
            _image_preview(chat)
        if st.session_state.get("image_error"):
            st.warning(st.session_state.image_error, icon=":material/broken_image:")

        with st.container(key="composer", horizontal=True,
                          vertical_alignment="bottom", gap="small"):
            with st.popover("+", key="composer-add", help="Add a document or an image"):
                docs = st.file_uploader(
                    "Doc upload", type=FILE_TYPES, accept_multiple_files=True,
                    key="docs-upload",
                    help="Your camera manual or notes. Answered from these first. "
                         "Used for this session only, never stored.",
                )
                key = _uploader_key(cid)
                st.file_uploader(
                    "Image upload", type=IMAGE_TYPES, key=key,
                    disabled=has_image,
                    help=("One image per conversation. Start a new conversation "
                          "to analyse another photo.") if has_image else
                         "One photo to describe or get settings advice on.",
                    on_change=_take_image, args=(chat, key),
                )
            prompt = st.chat_input(IMAGE_PLACEHOLDER if has_image else PLACEHOLDER)

    return docs or [], prompt
