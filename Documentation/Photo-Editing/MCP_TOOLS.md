# Photo Editing: MCP Server and Tools

## The server

`app/image_tools_server.py` is a [FastMCP](https://github.com/modelcontextprotocol/python-sdk)
server named `photo-editor`. The app starts it over **stdio** for each edit:

```python
# app/image_editing.py
MultiServerMCPClient({"photo-editor": {
    "transport": "stdio",
    "command": sys.executable,                 # the app's own Python / venv
    "args": ["-m", "app.image_tools_server"],
    "cwd": PROJECT_ROOT,
    "env": {"PHOTO_EDIT_WORKDIR": "<conversation's working folder>"},
}})
```

`langchain-mcp-adapters` turns its tools into LangChain tools that the editor model can
call. The server logs at WARNING, so tool calls don't clutter the app console.

Run it by hand (for example with the MCP Inspector):

```bash
PHOTO_EDIT_WORKDIR=/tmp/edits python -m app.image_tools_server
```

## Conventions shared by every tool

- The first argument is always `image_id`, a 12-character hex id of a PNG in the
  working folder.
- Every **edit** tool writes a new image and returns one line:
  `image_id=<new id> | applied: <label> | <measurements of the result>`.
  The measurements let the editor check its work without seeing the image.
- Out-of-range values raise an error that goes back to the model as a tool error, so it
  can correct the value and retry.
- The input image is never modified.

## Tools

| Tool | Parameters | Effect |
|---|---|---|
| `get_image_info` | — | Measures without changing: size, mean brightness, contrast (std), % clipped shadows/highlights, mean saturation, R/G/B means. |
| `adjust_brightness` | `percent` −90…200 | Scales every pixel. "+10% brightness" → `percent=10`. |
| `adjust_contrast` | `percent` −90…200 | Spreads tones away from the mean grey. "+20% contrast" → `percent=20`. |
| `adjust_exposure` | `ev` −3…3 | Exposure in stops, applied in linear light like a raw converter. Gentler on highlights than brightness. |
| `adjust_shadows_highlights` | `shadows` −100…100, `highlights` −100…100 | Lifts dark areas / recovers or brightens bright areas. Pure black and white don't move. |
| `adjust_white_balance` | `temperature` −100…100, `tint` −100…100 | + warmer / − cooler; + magenta / − green. Typical corrections 5–30. |
| `adjust_saturation` | `percent` −100…200 | −100 is black and white. |
| `sharpen` | `amount` 0.1…3, `radius` 0.3…5 px | Unsharp mask. Meant to be the last edit. |
| `crop_to_aspect_ratio` | `ratio` ("1:1", "4:5", "3:2", "16:9" …), `anchor_x`, `anchor_y` 0…1 | Largest crop at that ratio; anchors place it (0.5/0.5 = centred). |
| `rotate` | `degrees` (+ = clockwise) | 90/180/270 turn exactly; anything within ±45 straightens and crops away the empty corners. |

## How each edit is computed (`app/image_ops.py`)

All edits work on RGB float32 arrays in [0, 1] and are clipped only when saved.

| Edit | Method |
|---|---|
| Brightness | `img × (1 + p/100)` (same as Pillow `ImageEnhance.Brightness`) |
| Contrast | `(img − mean) × (1 + p/100) + mean` around the mean luminance |
| Exposure | sRGB → linear, × 2^EV, → sRGB |
| Saturation | blend each pixel away from its own luminance |
| White balance | per-channel gains: R `1 + 0.2t`, B `1 − 0.2t`, G `1 − 0.15·tint` |
| Shadows/highlights | luminance curves `1.5·s·L(1−L)²` and `1.5·h·L²(1−L)`, zero at black and white, applied as an RGB ratio so colour is kept |
| Sharpen | unsharp mask with `cv2.GaussianBlur` |
| Crop to aspect | largest box of the ratio, positioned by the anchors |
| Rotate | `np.rot90` for right angles; `cv2.warpAffine` + largest inscribed rectangle for straightening |

## Adding a tool

1. Write the edit in `app/image_ops.py`: `def my_edit(arr, ...) -> (arr, label)`, with
   range checks via `_check`.
2. Expose it in `app/image_tools_server.py` with `@mcp.tool()` and `_apply(image_id,
   ops.my_edit, ...)`. The docstring is what both agents read, so put ranges and a
   typical value in it.
3. Nothing else: Agent 1's tool list is read from the server at runtime, and Agent 2
   binds whatever tools the server offers. If the edit belongs at a particular point in
   the order, add it to the ordering line in `EDIT_PLAN_SYSTEM`.
