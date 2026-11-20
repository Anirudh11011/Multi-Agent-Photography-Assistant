# Photo Editing: Architecture

## The graph

The editing branch hangs off the existing image branch in `app/pipeline.py`. A text-only
turn still goes to `triage` and the escalation ladder, untouched.

```
START ─ photo attached? ─no──► triage → … (escalation ladder, unchanged)
            │ yes
            ▼
      image_router ──ask──► image_agent ───────────────────────► validate → END
            │ edit
            ▼
      image_analyst ──no edits / error──────────────────────────► validate
            │ plan has edits
            ▼
      image_editor ─────────────────────────────────────────────► validate
```

| Node | Model | Job |
|---|---|---|
| `image_router` | `SUPERVISOR_MODEL` (gpt-oss-20b, temp 0) | One word: EDIT or ASK. Skipped (always EDIT) when Auto-improve was pressed. Anything unreadable becomes ASK, so a misread never changes the photo. |
| `image_analyst` | `VISION_MODEL` | **Agent 1.** Sees the current version of the photo, its measurements, its EXIF and the tool list. Writes the edit plan. |
| `image_editor` | `EDITOR_MODEL` (gpt-oss-120b, temp 0) | **Agent 2.** Reads the plan, calls the MCP tools, one per edit. |
| `image_agent` | `VISION_MODEL` | Unchanged: answers questions about the photo. |
| `validate` | none | Unchanged: redacts secrets and strips invented links. |

## The two agents

### Agent 1: image analyst (thinks, never edits)

Input:
- the **current** version of the photo (so a second edit sees the first one's result)
- `<image_stats>`: mean brightness, contrast, clipped shadows/highlights, saturation,
  per-channel means, measured by the same code the tools use
- `<available_tools>`: the tool list **read from the MCP server at runtime**, so the
  analyst can only plan edits the server can actually make
- EXIF, recent conversation, and the user's message (or "Auto-improve")

Two modes:
- **requested**: plan exactly what the user asked, with exactly their numbers. Vague
  words become concrete amounts judged from the photo ("a bit warmer" → temperature +10).
  Nothing is added.
- **auto**: fix what is visibly wrong first, then modest enhancement, 2 to 6 edits, aiming
  for a natural result. "No edits" is a valid answer for a photo that is already good.

Output (parsed by `prompts.parse_edit_plan`):
```
EDITS:
1. Brightness +10% — user asked
2. Contrast +20% — user asked
CANNOT: none
SUMMARY: Brightened the image by 10% and raised contrast by 20%, as asked.
```

Requests the tools cannot do (remove an object, replace the sky) go under `CANNOT` and
are told to the user; they are never pretended.

### Agent 2: image editor (acts, never sees)

A tool-calling loop in `app/image_editing.py` (`_edit`), written by hand rather than
with a prebuilt agent so every call can be logged for the trace:

1. Start the MCP server, load its tools, `bind_tools` them to the editor model.
2. Loop (at most `EDIT_MAX_STEPS` model turns): the model calls tools; each result goes
   back to it as a `ToolMessage`. Tool errors (a value out of range) come back as error
   messages, so it can correct and retry.
3. It finishes with `FINAL_IMAGE_ID: <id>` and `NOTES: …`.

## Decisions taken

These were decided with the project owner before implementation.

| Question | Decision | Why |
|---|---|---|
| How specific is the hand-off from Agent 1 to Agent 2? | **Specific edits**: Agent 1 names each edit and amount in words; Agent 2 picks the tool and maps the arguments | Keeps "what the photo needs" (vision) separate from "how to run the tools" (tool calling). If Agent 1 wrote exact JSON, Agent 2 would only be a script. |
| A second edit in the same conversation applies to… | **The latest edited version**, with a **Reset to original** button | Edits stack the way they do in any editor ("now crop it square"). |
| How does the MCP server run? | **Local stdio subprocess**, started by the app | Nothing extra to deploy; works on Streamlit Cloud. |
| Where is the Auto-improve button? | **Beside the attached-photo preview** | Always one click away above the input bar. |
| Which tools? | **A small, standard set** (the basic panel of a raw converter) | Fewer tools, fewer wrong choices; easy to extend later. |

## How images move: by id, never by value

Sending pixels through a language model would cost thousands of tokens per call, and
the editor doesn't need to see them. So:

- Each conversation gets a **working folder**: `<system temp>/shutteraide-edits/<conversation id>/`.
- On the first turn with a photo, the upload is copied in once as a PNG: EXIF rotation
  applied, long edge capped at `EDIT_MAX_EDGE` (4096 px). That is the **original id**.
- Every tool call reads one id and writes a **new** PNG with a new 12-character id, plus
  a sidecar `<id>.json` = `{"parent": "<previous id>", "label": "Brightness +10%"}`.
  Nothing is ever overwritten.
- The conversation remembers `original_id` and `current_id`. The next edit starts from
  `current_id`; **Reset to original** sets `current_id = original_id`.
- When a run ends, its intermediate images are deleted: only the original and each
  request's final image are kept (see [STORAGE.md](STORAGE.md)).

Consequences:
- **Honest reporting.** The "Edits applied" list the user reads is rebuilt by walking the
  sidecar chain from the final image back to the start (`applied_edits`). It reports what
  was done to the pixels, not what the model says it did.
- **Full resolution.** The vision model sees a 1568-px JPEG (enough to judge); the edits
  run on the up-to-4096-px copy; the download is a quality-92 JPEG of that.
- **No quality loss between steps.** Steps are stored as lossless PNG and computed in
  float32, so five edits don't mean five rounds of JPEG compression.
- **Safety.** Tools accept only ids matching `^[0-9a-f]{12}$` that exist in the working
  folder, so a tool argument cannot read or write outside it.

## Where the code lives

| File | Role |
|---|---|
| `app/image_ops.py` | The edits as plain functions on float32 RGB arrays, plus I/O and measurement. No MCP, no Streamlit; easy to unit-test. |
| `app/image_tools_server.py` | The MCP server (FastMCP, stdio). Thin wrappers over `image_ops`, the id/sidecar bookkeeping. |
| `app/image_editing.py` | Working folders, the MCP client, the tool catalog for Agent 1, and Agent 2's tool-calling loop. No Streamlit. |
| `app/pipeline.py` | The `image_router`, `image_analyst` and `image_editor` nodes and their routing; `edit_answer` builds the user-facing reply. |
| `app/prompts.py` | `IMAGE_ROUTER_SYSTEM`, `EDIT_PLAN_SYSTEM`, `EDITOR_SYSTEM` and their builders/parsers. |
| `app/composer.py` | Auto-improve and Reset-to-original buttons, edited-version thumbnail. |
| `app/chat.py` | Creates the working copy, passes it to the graph, shows before/after and the download. |

## Async inside a sync graph

The MCP client is async; the LangGraph graph is run synchronously from Streamlit.
`run_editor` and `tool_catalog` wrap their work in `asyncio.run(...)`. Streamlit's script
thread has no running event loop, so this is safe. Each edit starts a fresh MCP server
process (about a second, mostly importing OpenCV) and closes it when done; the tool
catalog is fetched once per process and cached.
