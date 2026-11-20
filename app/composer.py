"""The input bar: a "+" menu (Doc upload, Image upload) beside the chat input.

Documents are session-wide, as the sidebar uploader was: they apply to every
conversation until removed. The image belongs to one conversation and there is
only ever one: once attached, image upload is disabled for that conversation.
It can be removed until the first question about it is sent; after that it is
locked in, so every later answer in the conversation is about the same photo.
A new conversation starts with image upload enabled again.

With a photo attached, the preview also carries the editing controls:
Auto-improve (the analyst decides every edit) and, once the photo has been
edited, Reset to original. Edits stack, so the preview shows the version the
next edit will start from.
"""

import streamlit as st

from app.attachments import FILE_TYPES, prepare_image, working_preview
from app.image_editing import exists, image_path
from app.settings import IMAGE_TYPES

PLACEHOLDER = "Describe your scene and camera"
IMAGE_PLACEHOLDER = "Ask about your photo, or tell me how to edit it"
AUTO_IMPROVE_PROMPT = "Auto-improve this photo"


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


def _request_auto_improve() -> None:
    st.session_state.auto_improve = st.session_state.current


def _reset_to_original(image: dict) -> None:
    image["current_id"] = image["original_id"]


def is_edited(image: dict) -> bool:
    return bool(image.get("current_id")) and image["current_id"] != image.get("original_id")


def _image_preview(chat: dict) -> None:
    image = chat["image"]
    cid = st.session_state.current
    edited = is_edited(image) and exists(image["edit_dir"], image["current_id"])
    with st.container(key="image-preview", horizontal=True,
                      vertical_alignment="center", gap="small"):
        if edited:
            st.image(working_preview(str(image_path(image["edit_dir"],
                                                    image["current_id"])), 160),
                     width=52)
        else:
            st.image(image["bytes"], width=52)
        name = image["name"] + (" · edited" if edited else "")
        st.markdown(f'<span class="image-preview-name">{name}</span>',
                    unsafe_allow_html=True)
        st.button("Auto-improve", key=f"auto-improve-{cid}",
                  icon=":material/auto_fix_high:", type="tertiary",
                  help="Let the analyst decide the edits and apply them",
                  on_click=_request_auto_improve)
        if edited:
            st.button("Reset to original", key=f"reset-image-{cid}",
                      icon=":material/undo:", type="tertiary",
                      help="The next edit starts from the photo as uploaded",
                      on_click=_reset_to_original, args=(image,))
        if not image["locked"]:
            st.button("Remove image", key=f"rm-image-{cid}",
                      icon=":material/close:", type="tertiary",
                      on_click=_remove_image, args=(chat,))


def render(chat: dict) -> tuple[list, str | None, str]:
    """Draw the input bar pinned to the bottom. Returns (documents, prompt, mode).

    mode is "auto_edit" when the Auto-improve button was pressed (prompt is then
    AUTO_IMPROVE_PROMPT), otherwise "".
    """
    cid = st.session_state.current
    has_image = bool(chat.get("image"))

    with st.bottom:
        if has_image:
            _image_preview(chat)
        if st.session_state.get("image_error"):
            st.warning(st.session_state.image_error, icon=":material/broken_image:")

        with st.container(key="composer", horizontal=True,
                          vertical_alignment="center", gap="small"):
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
                         "One photo to describe, get settings advice on, or edit.",
                    on_change=_take_image, args=(chat, key),
                )
            prompt = st.chat_input(IMAGE_PLACEHOLDER if has_image else PLACEHOLDER)

    # The button only counts for the conversation it was pressed in.
    if has_image and st.session_state.pop("auto_improve", None) == cid and not prompt:
        return docs or [], AUTO_IMPROVE_PROMPT, "auto_edit"
    return docs or [], prompt, ""
