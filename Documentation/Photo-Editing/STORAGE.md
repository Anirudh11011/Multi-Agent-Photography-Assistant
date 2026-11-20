# Photo Editing: Storage

Where conversations and images live, what changed in this update, and what is planned
next.

## Summary

| Data | Where it is stored | Lifetime |
|---|---|---|
| Chat as shown in the UI (questions, answers, traces) | Server memory: `st.session_state.chats[<id>]["history"]` | The browser session |
| Uploaded photo (original bytes) | Server memory: `chat["image"]["bytes"]` | The browser session |
| **Conversation transcript** | **Postgres (Neon)** via `DATABASE_URL`; SQLite `./conversations.db` if unset | **Permanent** |
| Image working copies (original + edited results) | Disk: `<system temp>/shutteraide-edits/<conversation id>/` | Until the temp folder is cleared or the server restarts |

Images are **never** written to the database. The transcript records only the image's
file name and, for edit turns, the text of the edit plan.

## 1. Conversation transcript (database)

Unchanged by this feature. `app/conversation_store.py` writes every turn:

| Table | One row per | Holds |
|---|---|---|
| `conversations` | chat session | title, user id (anonymous), environment, turn count |
| `messages` | turn | question, answer, source, model, timing, LangSmith run, `meta` (JSON) |
| `agent_steps` | pipeline node per turn | the node's trace text (including the edit plan and tool calls) |
| `feedback` | thumbs up/down | rating |

For edit turns, `messages.meta` also carries `"image": "<file name>"`, `"edit_mode"`
(`"auto_edit"` or null) and `"edit_plan"` (Agent 1's full plan).

**Neon setup.** Set `DATABASE_URL` in `.env` (local) or in Streamlit secrets (deployed),
for example `postgresql://user:pass@ep-xxx.neon.tech/dbname?sslmode=require`. The store
rewrites `postgres://` and `postgresql://` onto the psycopg 3 driver itself. That driver
(`psycopg[binary]`) is in `requirements.txt`, so run `pip install -r requirements.txt` in
every environment that uses Neon. Writes are best-effort: if the database is
unreachable, the failure is logged and the user still gets their answer.

## 2. Image working copies (disk)

Each conversation gets a folder `<system temp>/shutteraide-edits/<conversation id>/`:

| OS / host | `<system temp>` |
|---|---|
| macOS (local) | `/var/folders/…/T` |
| Linux / Streamlit Community Cloud | `/tmp` |

Each image is a PNG named by a 12-character id. An edited image also has a sidecar
`<id>.json` = `{"parent": "<id it was made from>", "label": "<edits applied>"}`.

## 3. Intermediate images: before and after this change

An edit request often needs several tool calls ("brightness +10%, contrast +20%,
saturation +10%" is three). Every tool call writes a **new** image and never overwrites
its input. That stays the same: the editor may create as many intermediate images as it
needs.

### Before

Every intermediate image was kept forever:

```
a1b2…png                 original
3bba…png  + .json        after brightness      ← intermediate, kept
1e61…png  + .json        after contrast        ← intermediate, kept
9f00…png  + .json        after saturation      = final
```

At up to 4096 px, each PNG is about 15–40 MB, so one multi-step request could leave
100+ MB behind.

### Now

When the editor finishes, `image_editing.run_editor` calls `prune_intermediates`. It
deletes every image **this run created** except the final one, and rewrites the final
image's sidecar to point straight at the image the run started from:

```
a1b2…png                 original
9f00…png  + .json        final   {"parent": "a1b2…", "label": "Brightness +10%; Contrast +20%; Saturation +10%"}
```

Rules:
- **Kept:** the original, plus the **final image of each edit request** in the
  conversation. Earlier finals are kept because the chat shows each turn's before/after,
  and the next edit starts from the latest final.
- **Deleted:** everything the run created in between, including partial results of a
  run that failed (a failed run keeps nothing new).
- **Never touched:** anything that existed before the run started. Pruning compares the
  folder's contents before and after the run, so it doesn't depend on the model naming
  every image it made.
- The "Edits applied" list is still accurate: it is built from the full chain *before*
  the intermediates are deleted.

Example: two requests, three tool calls then two. The folder ends with exactly three
images: the original, final 1 and final 2.

## 4. Deployed (Streamlit Community Cloud)

- **Transcripts** go to Neon and survive restarts and redeploys.
- **Image working copies** go to the container's `/tmp`. They are wiped whenever the
  app restarts, redeploys (every push) or sleeps. After that, older edit turns show
  "This edit's images are no longer on the server".
- While the container runs, a conversation's images stay after the user closes the
  tab (see below).

## 5. Not done yet: deleting images when the user leaves

Deferred for now. Today, closing the website does **not** delete that conversation's
image folder; it stays until the temp folder is cleared or the server restarts.

Streamlit has no reliable "tab closed" event: a disconnected session is parked for 2
minutes in case the user comes back, then freed lazily. The planned design:

1. Group each browser session's conversation folders under one session folder.
2. While a tab is open, a hidden `st.fragment(run_every="60s")` touches a marker file in
   that session folder.
3. A sweep (on each heartbeat and at app start) deletes any session folder whose marker
   is older than 5 minutes.

Five minutes is longer than Streamlit's 2-minute reconnect window, so a phone that
briefly locks or loses signal never loses a live session's images. Transcripts in Neon
are not affected by any of this.
