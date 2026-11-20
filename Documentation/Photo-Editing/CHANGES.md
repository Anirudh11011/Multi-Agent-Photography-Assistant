# Photo Editing: Changes

Branch: `Image-Analysis`. `main` is untouched.

## New files

| File | Purpose |
|---|---|
| `app/image_ops.py` | Pillow/OpenCV edit functions, I/O, measurements |
| `app/image_tools_server.py` | FastMCP server exposing the edits as tools (stdio) |
| `app/image_editing.py` | Working folders, MCP client, tool catalog, Agent 2's tool-calling loop |
| `Documentation/Photo-Editing/*` | This documentation |

## Changed files

| File | Change |
|---|---|
| `app/pipeline.py` | New nodes `image_router`, `image_analyst`, `image_editor`; `route_start` now goes to `image_router` for photo turns; new state fields `mode`, `edit_dir`, `edit_source_id`, `image_intent`, `edit_plan`, `edited_image_id`, `edit_log`; `initial_state` takes `mode`, `edit_dir`, `edit_source_id`; new `edit_answer`. |
| `app/prompts.py` | `IMAGE_ROUTER_SYSTEM`, `EDIT_PLAN_SYSTEM`, `EDITOR_SYSTEM`; builders `image_router_messages`, `edit_plan_messages`, `editor_messages`; parsers `parse_image_route`, `parse_edit_plan`. `PROMPT_VERSION` → `2026-11-19.1`. |
| `app/settings.py` | `EDITOR_MODEL`, `EDIT_MAX_EDGE`, `EDIT_DOWNLOAD_QUALITY`, `EDIT_MAX_STEPS`. |
| `app/composer.py` | Auto-improve and Reset-to-original buttons; edited thumbnail; `render()` now returns `(docs, prompt, mode)`. |
| `app/chat.py` | `_working_copy`, `_show_edit` (before/after + download); `answer_turn(..., mode=)`; trace entries for the new nodes; the turn records `edit`, `edit_mode`, `edit_plan`. |
| `app/attachments.py` | Cached `working_preview` and `working_download`. |
| `app/theme.py` | Trace labels for the three new nodes. |
| `streamlit_app.py` | Passes `mode` from the composer to `answer_turn`. |
| `requirements.txt` | `mcp`, `langchain-mcp-adapters`, `pillow`, `numpy`, `opencv-python-headless`. |

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `EDITOR_MODEL` | `MODEL_NAME` (gpt-oss-120b) | Agent 2; needs tool calling, not vision |
| `EDIT_MAX_EDGE` | 4096 | Long edge (px) edits run at and the download is saved at |
| `EDIT_DOWNLOAD_QUALITY` | 92 | JPEG quality of the download |
| `EDIT_MAX_STEPS` | 12 | Cap on Agent 2's model turns |

Agent 1 uses the existing `VISION_MODEL`; the router uses the existing `SUPERVISOR_MODEL`.

## Data recorded

The transcript store gets the turn as before, plus `edit_mode` and the full `edit_plan`
in its metadata. The images themselves are never written to the store; they live only
in the temporary working folder.

## How it was tested

- **Edit functions**: each run on a synthetic image (shape, dtype, effect direction) and
  an out-of-range value checked to raise.
- **MCP server**: started over stdio; tools listed; two edits chained; the sidecar
  lineage gives `['Brightness +10%', 'Contrast +20%']`; an id of `../../etc/x` rejected.
- **Agent 2 alone** (Groq, fixed plan "brightness +10%, contrast +20%"): two tool calls
  with the exact numbers, 1.8 s.
- **Full graph** on `static/aurora.jpg`:
  - "increase the brightness by 10% and contrast by 20%" → EDIT, plan kept the numbers, 2 tools, 3.3 s
  - Auto-improve → 4-edit plan from the stats (shadows, white balance, saturation, sharpen last), all applied, 30.8 s
  - "what's in this photo?" → ASK → existing `image_agent` answer
- **Streamlit (AppTest)**: page loads; with a photo attached the preview shows
  Auto-improve and Remove image; clicking Auto-improve produces an edit, before/after,
  one download button, and Reset to original; no exceptions.

## Update 2: pruning intermediate images

| File | Change |
|---|---|
| `app/image_editing.py` | New `prune_intermediates`; `run_editor` snapshots the folder before the run, deletes every image the run created except the final one, and rewrites the final image's sidecar to point at the run's start image. |
| `Documentation/Photo-Editing/STORAGE.md` | New: storage map, before/after of pruning, cloud behaviour, planned cleanup on leave. |

Tested against Groq with two requests in a row (3 tool calls, then 2): after each run
only the original and the final image(s) remain (3 PNGs in total), and "Edits applied"
still lists every step.

## Known limits

- **Temporary storage.** Working folders are in the system temp directory. When it is
  cleared (a server restart on Streamlit Cloud), older edit turns show "This edit's
  images are no longer on the server" instead of the before/after. Folders are **not**
  deleted when the user closes the website yet; the planned design is in
  [STORAGE.md](STORAGE.md#5-not-done-yet-deleting-images-when-the-user-leaves).
- **Questions use the original.** "What's in this photo?" and settings advice still
  look at the photo as uploaded, not the edited version, because the camera advice is
  about the shot as taken.
- **Global edits only.** No masks, selections, object removal or generative fill; the
  analyst reports those as not possible.
- **Auto-improve varies.** The analyst runs at the vision temperature (0.3), so two
  presses can give slightly different plans.
- **Server start-up.** Each edit starts a fresh MCP process (~1 s).
- `evals/pipeline_copy.py` is a frozen copy of the old pipeline and does not include the
  editing branch.
