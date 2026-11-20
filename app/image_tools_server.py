"""MCP server: the photo-editing tools the image editor agent (Agent 2) calls.

Run over stdio by image_editing.py:

    python -m app.image_tools_server      (PHOTO_EDIT_WORKDIR=<folder>)

A deliberately small set: the standard edits of a raw converter's basic panel.

Images never pass through the model. Each one is a PNG in the working folder,
named by a 12-character id. Every edit reads one id and writes a new one, so
the original is never overwritten and a bad step can be redone from its
parent. Next to each new image goes <id>.json: {parent, label}. That chain is
how the app reports exactly which edits produced the final image, whatever the
model says it did.
"""

import json
import os
import re
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app import image_ops as ops

WORKDIR = Path(os.environ.get("PHOTO_EDIT_WORKDIR", ".")).resolve()
_ID = re.compile(r"^[0-9a-f]{12}$")

# WARNING: otherwise every tool call logs a line to the app's console.
mcp = FastMCP("photo-editor", log_level="WARNING")


def _path(image_id: str) -> Path:
    # Ids are checked against a strict pattern so a tool argument can never
    # reach outside the working folder.
    if not _ID.match(image_id or ""):
        raise ValueError(f"unknown image_id {image_id!r}")
    path = WORKDIR / f"{image_id}.png"
    if not path.exists():
        raise ValueError(f"unknown image_id {image_id!r}")
    return path


def _apply(image_id: str, fn, *args) -> str:
    arr, label = fn(ops.load(_path(image_id)), *args)
    new_id = uuid.uuid4().hex[:12]
    ops.save(arr, WORKDIR / f"{new_id}.png")
    (WORKDIR / f"{new_id}.json").write_text(
        json.dumps({"parent": image_id, "label": label}))
    return f"image_id={new_id} | applied: {label} | {ops.stats(arr)}"


@mcp.tool()
def get_image_info(image_id: str) -> str:
    """Measure an image without changing it: size, mean brightness, contrast,
    clipped shadows/highlights, saturation and per-channel means (a colour cast
    shows as one channel well above the others)."""
    return ops.stats(ops.load(_path(image_id)))


@mcp.tool()
def adjust_brightness(image_id: str, percent: float) -> str:
    """Make the whole image brighter or darker by a percentage (-90 to 200).
    "+10% brightness" → percent=10."""
    return _apply(image_id, ops.brightness, percent)


@mcp.tool()
def adjust_contrast(image_id: str, percent: float) -> str:
    """Increase or decrease global contrast by a percentage (-90 to 200).
    "+20% contrast" → percent=20."""
    return _apply(image_id, ops.contrast, percent)


@mcp.tool()
def adjust_exposure(image_id: str, ev: float) -> str:
    """Change exposure in stops (-3 to 3), like a raw converter's exposure slider.
    Gentler on highlights than brightness. +1 EV doubles the light."""
    return _apply(image_id, ops.exposure, ev)


@mcp.tool()
def adjust_shadows_highlights(image_id: str, shadows: float = 0,
                              highlights: float = 0) -> str:
    """Tone recovery. shadows (-100 to 100): positive lifts dark areas.
    highlights (-100 to 100): negative recovers bright areas, positive brightens
    them. Pure black and pure white stay put."""
    return _apply(image_id, ops.shadows_highlights, shadows, highlights)


@mcp.tool()
def adjust_white_balance(image_id: str, temperature: float = 0, tint: float = 0) -> str:
    """Correct a colour cast. temperature (-100 to 100): positive warmer/amber,
    negative cooler/blue. tint (-100 to 100): positive magenta, negative green.
    Typical corrections are 5 to 30."""
    return _apply(image_id, ops.white_balance, temperature, tint)


@mcp.tool()
def adjust_saturation(image_id: str, percent: float) -> str:
    """Make colours more or less vivid by a percentage (-100 to 200).
    -100 removes all colour (black and white)."""
    return _apply(image_id, ops.saturation, percent)


@mcp.tool()
def sharpen(image_id: str, amount: float = 0.6, radius: float = 1.2) -> str:
    """Unsharp-mask sharpening. amount 0.1–3 (0.3–1 is natural), radius 0.3–5 px.
    Should be the last edit."""
    return _apply(image_id, ops.sharpen, amount, radius)


@mcp.tool()
def crop_to_aspect_ratio(image_id: str, ratio: str, anchor_x: float = 0.5,
                         anchor_y: float = 0.5) -> str:
    """Largest crop with an aspect ratio such as "1:1", "4:5", "3:2", "16:9".
    anchor_x/anchor_y (0–1) position the crop; 0.5/0.5 is centred."""
    return _apply(image_id, ops.crop_to_aspect, ratio, anchor_x, anchor_y)


@mcp.tool()
def rotate(image_id: str, degrees: float) -> str:
    """Rotate; positive is clockwise. 90/180/270 turn the image exactly. Any
    angle within ±45 straightens a tilted horizon and crops the empty corners."""
    return _apply(image_id, ops.rotate, degrees)


if __name__ == "__main__":
    mcp.run()          # stdio
