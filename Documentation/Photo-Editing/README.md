# Photo Editing

ShutterAide can now edit the photo a user attaches, not just talk about it. There are two
ways to ask:

| | How the user asks | Who decides the edits |
|---|---|---|
| **AI edit (Auto-improve)** | Clicks **Auto-improve** beside the attached photo | The image analyst decides everything |
| **Instructed edit** | Types an instruction, e.g. *"increase the brightness by 10% and contrast by 20%"* | The user; the analyst turns their words into exact amounts |

Questions about the photo ("what's in this photo?", "how could I shoot this better?") work
exactly as before.

## Documents in this folder

| File | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | The two agents, the graph, how images move, design decisions |
| [MCP_TOOLS.md](MCP_TOOLS.md) | The MCP server and every editing tool, with parameters |
| [PROMPTS.md](PROMPTS.md) | The router, analyst and editor prompts and why they read as they do |
| [USAGE.md](USAGE.md) | What the user sees, with examples |
| [STORAGE.md](STORAGE.md) | Where conversations and images are stored, intermediate-image pruning, cloud behaviour, planned cleanup |
| [CHANGES.md](CHANGES.md) | Every file added or changed, settings, dependencies, how it was tested, known limits |

## At a glance

```
                     ┌─────────────────────── image turn ───────────────────────┐
 typed message ──►  image_router ──ask──► image_agent ─────────────────────────┐ │
                        │                                                      │ │
                        edit                                                   ▼ │
 Auto-improve ──────────┴──► image_analyst ──plan──► image_editor ──► validate ──► answer
                             (Agent 1, vision)       (Agent 2, tools)            + before/after
                                                          │                      + download
                                                          ▼
                                               MCP server (stdio)
                                       Pillow + OpenCV editing tools
```

- **Agent 1, the image analyst** looks at the photo and writes an edit plan. It never
  edits pixels.
- **Agent 2, the image editor** never sees the photo. It carries out the plan by calling
  the editing tools on an MCP server.
- **The MCP server** wraps a small, standard set of Pillow/OpenCV edits: brightness,
  contrast, exposure, shadows/highlights, white balance, saturation, sharpen, crop to
  aspect ratio, rotate/straighten.

## Quick start

```bash
pip install -r requirements.txt     # adds mcp, langchain-mcp-adapters, opencv-python-headless
streamlit run streamlit_app.py
```

Attach a photo with **+ → Image upload**, then either type an edit or press
**Auto-improve**. Nothing else needs to run: the app starts the MCP server itself.
