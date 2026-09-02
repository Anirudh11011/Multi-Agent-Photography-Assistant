# Tracing & Conversation Recording

Two things are captured on every turn, in every environment:

| What | Where | Module |
|---|---|---|
| Full agent trace — each node, each LLM call, prompts, tokens, latency | LangSmith | `observability.py` |
| The transcript — question, answer, provenance, agent steps, feedback | SQL database | `conversation_store.py` |

They are independent. LangSmith is for debugging and evaluation and needs an API key.
The database is the durable training corpus and runs with no key at all. If either is
unavailable the assistant still answers — every write is best effort and a failure is
logged rather than raised.

---

## LangSmith

### Setup

Get a key from https://smith.langchain.com → **Settings → API Keys**, then put it in
`.env`:

```
LANGSMITH_API_KEY="lsv2_pt_..."
LANGSMITH_PROJECT="multi-agent-photography-assistant"
```

That is the whole setup. `observability.configure_langsmith()` runs at the top of
`streamlit_app.py`, before any chain is constructed, and sets the environment variables
LangChain reads. Because the entire pipeline is LangChain/LangGraph, every node, every
Groq call and every retrieval is traced automatically — no per-call instrumentation.

Leave `LANGSMITH_API_KEY` blank and tracing turns off cleanly; the sidebar says
`LangSmith tracing: off`.

Both the new `LANGSMITH_*` and the older `LANGCHAIN_*` variable names are accepted, and
both are set, so any library still reading the legacy names agrees with the new ones.

### What each trace carries

`observability.run_config()` builds the config passed to `graph.stream()`:

- **`thread_id`** — the conversation id. This is what groups a multi-turn chat into one
  LangSmith thread, so you can read a whole session end to end rather than isolated runs.
- **metadata** — `conversation_id`, `conversation_turn`, `user_id`, `environment`
  (`local` / `deploy`), `model`, `attached_files`, and the escalation `stages` tried.
- **tags** — `photography-assistant` and the environment, so deployed traffic can be
  filtered apart from local experiments in the LangSmith UI.

### Linking a trace to a transcript

`observability.traced_run()` wraps the turn and captures the root run via LangChain's
`collect_runs`. The resulting `langsmith_run_id` and `langsmith_run_url` are stored on
the `messages` row, and the answer gets a **view trace** link in the UI. So a suspicious
answer in the exported training data can always be traced back to the exact prompts that
produced it.

### Feedback

The thumbs up/down under each answer writes to the `feedback` table **and** calls
`create_feedback` on the LangSmith run under the key `user_rating` (1.0 / 0.0). Rated
runs can then be filtered in LangSmith and used to build evaluation sets.

---

## Conversation recording

### Where the rows go

```
DATABASE_URL set    →  that database (Postgres, MySQL, anything SQLAlchemy speaks)
DATABASE_URL unset  →  ./conversations.db (SQLite)
```

Nothing else changes between the two — same schema, same code path. The sidebar prints
which one is active, with the password stripped out of the connection string.

### Deploy mode

**A deployment needs `DATABASE_URL`.** Streamlit Community Cloud, and most container
hosts, give the app an ephemeral filesystem: the SQLite file is deleted on every restart
and redeploy, which would take the training corpus with it. When the app detects it is
running deployed (`APP_ENV=deploy`, or a Streamlit Cloud runtime) without a
`DATABASE_URL`, the sidebar shows a warning.

Any managed Postgres works — Supabase, Neon, RDS. Add the driver to the environment:

```bash
pip install "psycopg[binary]"
```

then set the secret. On Streamlit Cloud, **Manage app → Settings → Secrets**:

```toml
GROQ_API_KEY = "gsk_..."
LANGSMITH_API_KEY = "lsv2_pt_..."
DATABASE_URL = "postgresql://user:password@host:5432/dbname"
APP_ENV = "deploy"
```

`.streamlit/secrets.toml.example` is a copy of this block. Both `observability.py` and
`conversation_store.py` read the environment first and Streamlit secrets second, so the
same code runs locally off `.env` and deployed off secrets with no branching.

`postgres://` and `postgresql://` URLs are both rewritten to `postgresql+psycopg://`,
since managed providers hand out the first form and SQLAlchemy 2 rejects it.

### Schema

```
conversations   id, title, app, environment, user_id, created_at, updated_at,
                turn_count, meta
messages        id, conversation_id, turn_index, question, answer, source, model,
                elapsed_seconds, langsmith_run_id, langsmith_run_url, environment,
                created_at, meta
agent_steps     id, message_id, step_index, node, content, created_at
feedback        id, message_id, rating, comment, created_at
```

`agent_steps` holds the same per-node payloads the Agent trace expander shows — the
supervisor's verdict on each rung, the retrieved passages, both analyses. That is what
makes the export useful for more than plain input/output pairs: you can train or
evaluate on the intermediate reasoning, not only the final answer.

`source` records which rung of the ladder actually answered (`attached`, `retrieved`,
`web`, `none`), so refusals and web fallbacks can be separated out of the corpus.

Tables are created on first use. There are no migrations — adding a column means
altering the table by hand.

---

## Exporting for training

```bash
# what's recorded so far
python export_conversations.py

# every turn with agent steps and provenance
python export_conversations.py --out data.jsonl

# fine-tuning shape: {"messages": [user, assistant], "metadata": {...}}
python export_conversations.py --out sft.jsonl --format sft

# production traffic only
python export_conversations.py --out deploy.jsonl --environment deploy

# push the turns to LangSmith as an evaluation dataset
python export_conversations.py --to-langsmith photography-assistant-v1
```

Exports read whichever database `DATABASE_URL` points at, so pointing the tool at the
production database pulls the deployed transcripts:

```bash
DATABASE_URL="postgresql://…" python export_conversations.py --out prod.jsonl --format sft
```

Filter before training. Turns where `source` is `none` are refusals, and turns with a
`down` rating in `feedback` are ones the user rejected — neither belongs in a supervised
fine-tuning set as a positive example.

---

## Privacy note

Every question users type is now stored, along with the filenames of anything they
attach. Attached file *contents* are not stored — they stay session-scoped as before,
and only the ranked context reaches the LLM (and therefore LangSmith). If this is
deployed to real users, tell them their conversations are recorded.
