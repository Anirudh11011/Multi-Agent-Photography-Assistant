"""Durable conversation logging — every question, answer and agent step.

Everything the assistant says is recorded here so the transcripts can later be
used for evaluation and training. Recording runs in local *and* deployed mode;
the only difference is where the rows land:

    DATABASE_URL set    →  that database (Postgres/MySQL/… via SQLAlchemy)
    DATABASE_URL unset  →  ./conversations.db (SQLite)

On an ephemeral host — Streamlit Community Cloud, a container without a mounted
volume — SQLite is wiped whenever the app restarts, so a deployment that must
keep its transcripts needs `DATABASE_URL` pointing at a managed database.
`storage_notice()` says which of the two is in effect so the app can show it.

Writes are best effort by design: a logging failure is swallowed and logged, it
never takes the user's answer down with it.

Schema
    conversations  one row per chat session
    messages       one row per turn (question + answer + provenance)
    agent_steps    one row per pipeline node that ran for a turn
    feedback       optional thumbs up/down against a turn
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, BigInteger, Column, DateTime, Float, ForeignKey, Integer, MetaData,
    String, Table, Text, create_engine, func, select,
)

log = logging.getLogger(__name__)

DEFAULT_SQLITE_PATH = os.getenv("CONVERSATION_DB_PATH", "./conversations.db")

metadata = MetaData()

conversations = Table(
    "conversations", metadata,
    Column("id", String(64), primary_key=True),
    Column("title", Text),
    Column("app", String(64)),
    Column("environment", String(32)),
    Column("user_id", String(128)),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    Column("turn_count", Integer, default=0),
    Column("meta", JSON),
)

messages = Table(
    "messages", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True,
           autoincrement=True),
    Column("conversation_id", String(64), ForeignKey("conversations.id"), index=True),
    Column("turn_index", Integer),
    Column("question", Text),
    Column("answer", Text),
    Column("source", String(32)),
    Column("model", String(128)),
    Column("elapsed_seconds", Float),
    Column("langsmith_run_id", String(64)),
    Column("langsmith_run_url", Text),
    Column("environment", String(32)),
    Column("created_at", DateTime(timezone=True)),
    Column("meta", JSON),
)

agent_steps = Table(
    "agent_steps", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True,
           autoincrement=True),
    Column("message_id", BigInteger().with_variant(Integer, "sqlite"),
           ForeignKey("messages.id"), index=True),
    Column("step_index", Integer),
    Column("node", String(64)),
    Column("content", Text),
    Column("created_at", DateTime(timezone=True)),
)

feedback = Table(
    "feedback", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True,
           autoincrement=True),
    Column("message_id", BigInteger().with_variant(Integer, "sqlite"),
           ForeignKey("messages.id"), index=True),
    Column("rating", String(16)),
    Column("comment", Text),
    Column("created_at", DateTime(timezone=True)),
)

_engine = None
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _setting(name: str) -> str | None:
    """Environment first, then Streamlit secrets (the deploy-mode equivalent)."""
    value = os.getenv(name)
    if value:
        return value.strip().strip('"').strip("'")
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        pass
    return None


def database_url() -> str:
    """Resolved connection string. Falls back to a local SQLite file."""
    url = _setting("DATABASE_URL")
    if not url:
        return f"sqlite:///{DEFAULT_SQLITE_PATH}"
    # Managed providers hand out `postgres://`, which SQLAlchemy 2 rejects, and
    # `postgresql://` picks a driver that may not be installed. Normalise both
    # onto psycopg 3, which is what requirements.txt pins.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def get_engine():
    """Create the engine and tables once per process."""
    global _engine
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        url = database_url()
        kwargs: dict = {"pool_pre_ping": True, "future": True}
        if url.startswith("sqlite"):
            # Streamlit runs each session on its own thread.
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs.pop("pool_pre_ping")
        engine = create_engine(url, **kwargs)
        metadata.create_all(engine)
        _engine = engine
        log.info("Conversation store ready: %s", _safe_url(url))
        return _engine


def _safe_url(url: str) -> str:
    """Connection string with any password removed, safe to log or display."""
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def is_durable() -> bool:
    """True when rows go to a real database rather than a local SQLite file."""
    return not database_url().startswith("sqlite")


def storage_notice() -> str:
    """One line describing where transcripts are being written."""
    url = database_url()
    if url.startswith("sqlite"):
        return (f"Conversations → local SQLite file ({DEFAULT_SQLITE_PATH}). "
                "Set DATABASE_URL to keep them across deploys.")
    return f"Conversations → {_safe_url(url)}"


def healthy() -> bool:
    """Whether the store can actually be reached. Never raises."""
    try:
        with get_engine().connect() as conn:
            conn.execute(select(func.count()).select_from(conversations))
        return True
    except Exception as exc:
        log.warning("Conversation store unavailable: %s", exc)
        return False


# ── Writes ───────────────────────────────────────────────────
def ensure_conversation(conversation_id: str, *, title: str = "", app: str = "streamlit",
                        environment: str = "local", user_id: str | None = None,
                        meta: dict | None = None) -> None:
    """Insert the conversation row if it is new; refresh the title if it changed."""
    try:
        engine = get_engine()
        with engine.begin() as conn:
            existing = conn.execute(
                select(conversations.c.id, conversations.c.title)
                .where(conversations.c.id == conversation_id)
            ).first()
            if existing is None:
                conn.execute(conversations.insert().values(
                    id=conversation_id, title=title or "New conversation", app=app,
                    environment=environment, user_id=user_id, created_at=_now(),
                    updated_at=_now(), turn_count=0, meta=meta or {},
                ))
            elif title and title != existing.title:
                conn.execute(conversations.update()
                             .where(conversations.c.id == conversation_id)
                             .values(title=title, updated_at=_now()))
    except Exception as exc:
        log.warning("Could not record conversation %s: %s", conversation_id, exc)


def record_turn(conversation_id: str, *, turn_index: int, question: str, answer: str,
                source: str = "", model: str = "", elapsed_seconds: float | None = None,
                steps: list | None = None, langsmith_run_id: str | None = None,
                langsmith_run_url: str | None = None, environment: str = "local",
                title: str = "", app: str = "streamlit", user_id: str | None = None,
                meta: dict | None = None) -> int | None:
    """Persist one full turn — question, answer, provenance and pipeline steps.

    Returns the message id, or None if the write failed (the caller carries on).
    """
    try:
        ensure_conversation(conversation_id, title=title, app=app,
                            environment=environment, user_id=user_id)
        engine = get_engine()
        with engine.begin() as conn:
            result = conn.execute(messages.insert().values(
                conversation_id=conversation_id, turn_index=turn_index,
                question=question, answer=answer, source=source, model=model,
                elapsed_seconds=elapsed_seconds, langsmith_run_id=langsmith_run_id,
                langsmith_run_url=langsmith_run_url, environment=environment,
                created_at=_now(), meta=meta or {},
            ))
            message_id = result.inserted_primary_key[0]

            rows = []
            for i, step in enumerate(steps or []):
                node, content = (step if isinstance(step, (list, tuple)) and len(step) == 2
                                 else ("unknown", str(step)))
                rows.append({"message_id": message_id, "step_index": i, "node": str(node),
                             "content": str(content), "created_at": _now()})
            if rows:
                conn.execute(agent_steps.insert(), rows)

            conn.execute(conversations.update()
                         .where(conversations.c.id == conversation_id)
                         .values(updated_at=_now(), turn_count=turn_index + 1))
        return int(message_id)
    except Exception as exc:
        log.warning("Could not record turn for %s: %s", conversation_id, exc)
        return None


def record_feedback(message_id: int, rating: str, comment: str | None = None) -> bool:
    """Store a thumbs up/down against a turn."""
    try:
        with get_engine().begin() as conn:
            conn.execute(feedback.insert().values(
                message_id=message_id, rating=rating, comment=comment, created_at=_now()))
        return True
    except Exception as exc:
        log.warning("Could not record feedback: %s", exc)
        return False


# ── Reads ────────────────────────────────────────────────────
def stats() -> dict:
    """Row counts, for the sidebar and the export tool."""
    try:
        with get_engine().connect() as conn:
            return {
                "conversations": conn.execute(
                    select(func.count()).select_from(conversations)).scalar_one(),
                "turns": conn.execute(
                    select(func.count()).select_from(messages)).scalar_one(),
            }
    except Exception as exc:
        log.warning("Could not read store stats: %s", exc)
        return {"conversations": 0, "turns": 0}


def iter_turns(limit: int | None = None, environment: str | None = None):
    """Every recorded turn, oldest first, with its agent steps attached."""
    engine = get_engine()
    with engine.connect() as conn:
        query = (select(messages, conversations.c.title, conversations.c.app)
                 .join(conversations, messages.c.conversation_id == conversations.c.id)
                 .order_by(messages.c.created_at.asc(), messages.c.id.asc()))
        if environment:
            query = query.where(messages.c.environment == environment)
        if limit:
            query = query.limit(limit)

        for row in conn.execute(query).mappings():
            steps = conn.execute(
                select(agent_steps.c.node, agent_steps.c.content)
                .where(agent_steps.c.message_id == row["id"])
                .order_by(agent_steps.c.step_index.asc())
            ).all()
            record = dict(row)
            record["created_at"] = (record["created_at"].isoformat()
                                    if record.get("created_at") else None)
            record["steps"] = [{"node": n, "content": c} for n, c in steps]
            yield record


def export_jsonl(path: str, limit: int | None = None, environment: str | None = None) -> int:
    """Write every turn to a JSONL file for training. Returns the row count."""
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        for record in iter_turns(limit=limit, environment=environment):
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            count += 1
    return count
