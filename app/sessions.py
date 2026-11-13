"""Chat sessions. Each conversation's history is a LangChain chat message history.

A conversation's turns live in an ``InMemoryChatMessageHistory`` as
HumanMessage / AIMessage pairs. Everything the UI needs to redraw a turn (the
trace steps, source, timing, feedback ids, cameras) rides on the messages'
``additional_kwargs``. Streamlit's session_state is only the per-browser
container that holds the conversations between reruns; the transcript store
still records every turn.
"""

import time
import uuid

import streamlit as st
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages

from app import conversation_store as store
from app import observability as obs
from app.settings import HISTORY_ANSWER_CHARS, HISTORY_MAX_TOKENS


def init() -> None:
    """Open a first conversation for a new browser session. A no-op on reruns."""
    if "chats" not in st.session_state:
        st.session_state.chats = {}
        st.session_state.current = None
        new_chat()


def new_chat() -> str:
    cid = uuid.uuid4().hex[:8]
    st.session_state.chats[cid] = {"title": "New conversation",
                                   "history": InMemoryChatMessageHistory(),
                                   "created": time.time()}
    st.session_state.current = cid
    store.ensure_conversation(cid, title="New conversation", app="streamlit",
                              environment=obs.environment(), user_id=session_user_id())
    return cid


def session_user_id() -> str:
    """A stable anonymous id per browser session, to group one user's chats."""
    if "user_id" not in st.session_state:
        st.session_state.user_id = f"anon-{uuid.uuid4().hex[:12]}"
    return st.session_state.user_id


def current_chat() -> dict:
    if not st.session_state.chats or st.session_state.current not in st.session_state.chats:
        new_chat()
    return st.session_state.chats[st.session_state.current]


def get_session_history(conversation_id: str) -> BaseChatMessageHistory:
    """The message history for one conversation (LangChain's session-history hook)."""
    return st.session_state.chats[conversation_id]["history"]


# ── Turns ────────────────────────────────────────────────────
# A turn is one HumanMessage followed by one AIMessage.

def add_turn(chat: dict, question: str, answer: str, *, image_shown: bool = False,
             **meta) -> None:
    """Append a question/answer pair; ``meta`` is kept on the AI message."""
    chat["history"].add_messages([
        HumanMessage(content=question, additional_kwargs={"image_shown": image_shown}),
        AIMessage(content=answer, additional_kwargs=meta),
    ])


def turns(chat: dict) -> list[dict]:
    """The conversation as turn dicts, for rendering: question, answer and metadata."""
    messages = chat["history"].messages
    out = []
    for human, ai in zip(messages[0::2], messages[1::2]):
        out.append({"question": human.content, "answer": ai.content,
                    "image_shown": human.additional_kwargs.get("image_shown", False),
                    **ai.additional_kwargs})
    return out


def turn_count(chat: dict) -> int:
    return len(chat["history"].messages) // 2


def last_turn(chat: dict) -> dict | None:
    all_turns = turns(chat)
    return all_turns[-1] if all_turns else None


def _clip(message: BaseMessage) -> BaseMessage:
    """A copy of an AI message with its answer clipped to HISTORY_ANSWER_CHARS."""
    if isinstance(message, AIMessage) and len(message.content) > HISTORY_ANSWER_CHARS:
        return AIMessage(content=message.content[:HISTORY_ANSWER_CHARS].rstrip() + " …")
    return message


def trimmed_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """The most recent whole turns that fit in HISTORY_MAX_TOKENS.

    Trimming, not summarising or deleting: the stored history is never changed (the
    chat view replays all of it); only what the model is shown is cut. Turns are
    kept whole — the kept slice starts on a question and ends on an answer — and
    the latest turn is always kept so a short follow-up never loses its context.
    """
    clipped = [_clip(m) for m in messages]
    kept = trim_messages(
        clipped,
        max_tokens=HISTORY_MAX_TOKENS,
        token_counter=count_tokens_approximately,
        strategy="last",
        start_on="human",
        end_on="ai",
        allow_partial=False,
    )
    if not kept and len(clipped) >= 2:
        kept = clipped[-2:]
    return kept


def format_history(history: BaseChatMessageHistory) -> str:
    """Recent turns as plain text, for follow-ups like "what about at night?"."""
    lines = []
    for message in trimmed_messages(history.messages):
        if isinstance(message, HumanMessage):
            lines.append(f"User: {message.content}")
        elif isinstance(message, AIMessage):
            lines.append(f"ShutterAide: {message.content}")
    # "User: …\nShutterAide: …" per turn, turns separated by a blank line.
    return "\n\n".join("\n".join(lines[i:i + 2]) for i in range(0, len(lines), 2))
