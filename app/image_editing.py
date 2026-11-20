"""Photo editing: the working copies on disk, and Agent 2's tool-calling loop.

The editing tools live in an MCP server (image_tools_server.py) that this module
starts as a stdio subprocess. Agent 2 reaches them through langchain-mcp-adapters
and passes image ids, never pixels, so a 4096-px photo costs no tokens.

Each conversation gets its own working folder in the system temp directory. The
original photo is copied in once; every edit adds a new file next to it, so an
earlier version (and the original) is always still there to go back to.

No Streamlit here: pipeline.py calls into this, and the UI only reads files.
"""

import asyncio
import base64
import json
import re
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

from app import image_ops as ops
from app import prompts as P

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORK_ROOT = Path(tempfile.gettempdir()) / "shutteraide-edits"
SERVER = "photo-editor"
_ID = re.compile(r"[0-9a-f]{12}")


# ── Working copies ───────────────────────────────────────────
def workdir(conversation_id: str) -> Path:
    folder = WORK_ROOT / re.sub(r"[^A-Za-z0-9_-]", "", conversation_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def image_path(folder: str | Path, image_id: str) -> Path:
    return Path(folder) / f"{image_id}.png"


def exists(folder: str | Path, image_id: str) -> bool:
    return bool(image_id) and image_path(folder, image_id).exists()


def import_original(folder: Path, data: bytes, max_edge: int) -> str:
    """Copy the uploaded photo in as the first working image; returns its id."""
    image_id = uuid.uuid4().hex[:12]
    ops.save(ops.decode_upload(data, max_edge), image_path(folder, image_id))
    return image_id


def data_url(folder: str | Path, image_id: str, max_edge: int, quality: int) -> str:
    """The working image as a small JPEG data: URL, for the vision model."""
    jpeg = ops.encode_jpeg(image_path(folder, image_id), max_edge, quality)
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def measure(folder: str | Path, image_id: str) -> str:
    return ops.stats(ops.load(image_path(folder, image_id)))


def applied_edits(folder: str | Path, final_id: str, start_id: str) -> list[str]:
    """Labels of the edits between start_id and final_id, oldest first.

    Read from the sidecars the MCP server writes, so this is what was actually
    done to the pixels, not what the model says it did.
    """
    labels, current = [], final_id
    while current and current != start_id:
        meta = Path(folder) / f"{current}.json"
        if not meta.exists():
            break
        record = json.loads(meta.read_text())
        labels.append(record["label"])
        current = record.get("parent")
    return labels[::-1]


# ── MCP ──────────────────────────────────────────────────────
def _client(folder: str | Path) -> MultiServerMCPClient:
    return MultiServerMCPClient({SERVER: {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "app.image_tools_server"],
        "cwd": str(PROJECT_ROOT),
        "env": {"PHOTO_EDIT_WORKDIR": str(folder)},
    }})


@lru_cache(maxsize=1)
def tool_catalog() -> str:
    """The editing tools, as Agent 1 is shown them: name, arguments, description.

    Read from the MCP server itself, so the analyst can only plan edits the
    server can actually make. Cached for the life of the process.
    """
    async def _list() -> list:
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        async with _client(WORK_ROOT).session(SERVER) as session:
            return await load_mcp_tools(session)

    lines = []
    for tool in asyncio.run(_list()):
        if tool.name == "get_image_info":
            continue
        props = (tool.args_schema or {}).get("properties", {}) if isinstance(
            tool.args_schema, dict) else {}
        args = ", ".join(a for a in props if a != "image_id")
        desc = " ".join((tool.description or "").split())
        lines.append(f"- {tool.name}({args}): {desc}")
    return "\n".join(lines)


# ── Agent 2: the editor ──────────────────────────────────────
@dataclass
class EditResult:
    image_id: str                       # the final image; the start id if nothing ran
    edits: list = field(default_factory=list)    # labels of what was applied
    calls: list = field(default_factory=list)    # tool-call log, for the trace
    notes: str = ""
    error: str = ""


def _text(message) -> str:
    content = message.content
    if isinstance(content, list):
        content = " ".join(b.get("text", "") if isinstance(b, dict) else str(b)
                           for b in content)
    return str(content)


async def _edit(llm, plan: str, folder: Path, start_id: str, max_steps: int) -> EditResult:
    calls, last_created, final_text = [], None, ""
    async with _client(folder).session(SERVER) as session:
        tools = await load_mcp_tools(session)
        by_name = {t.name: t for t in tools}
        model = llm.bind_tools(tools)
        messages = P.editor_messages(plan, start_id)
        for _ in range(max_steps):
            reply = await model.ainvoke(messages)
            messages.append(reply)
            if not reply.tool_calls:
                final_text = _text(reply)
                break
            for call in reply.tool_calls:
                tool = by_name.get(call["name"])
                if tool is None:
                    result = ToolMessage(content=f"Error: no tool named {call['name']}",
                                         tool_call_id=call["id"], status="error")
                else:
                    result = await tool.ainvoke(call)
                messages.append(result)
                text = _text(result)
                args = ", ".join(f"{k}={v}" for k, v in call["args"].items()
                                 if k != "image_id")
                calls.append(f"{call['name']}({args}) → {text[:160]}")
                created = re.search(r"image_id=([0-9a-f]{12})", text)
                if created:
                    last_created = created.group(1)

    # Trust the editor's FINAL_IMAGE_ID only if it names a real image; otherwise
    # the last image any tool created is the result.
    claimed = re.search(r"FINAL_IMAGE_ID:\s*([0-9a-f]{12})", final_text)
    final_id = (claimed.group(1) if claimed and exists(folder, claimed.group(1))
                else last_created or start_id)
    notes = re.search(r"NOTES:\s*(.+)", final_text)
    notes = notes.group(1).strip() if notes else ""
    return EditResult(image_id=final_id,
                      edits=applied_edits(folder, final_id, start_id),
                      calls=calls,
                      notes="" if notes.lower().startswith("none") else notes)


def _image_ids(folder: Path) -> set[str]:
    return {p.stem for p in folder.glob("*.png") if _ID.fullmatch(p.stem)}


def prune_intermediates(folder: Path, before: set[str], keep: str) -> list[str]:
    """Delete every image this run created except `keep`; returns the deleted ids.

    `before` is the set of ids that existed when the run started, so the original,
    earlier turns' results and the image this run started from are never touched.
    """
    deleted = []
    for image_id in _image_ids(folder) - before - {keep}:
        for suffix in (".png", ".json"):
            (folder / f"{image_id}{suffix}").unlink(missing_ok=True)
        deleted.append(image_id)
    return deleted


def run_editor(llm, plan: str, folder: str | Path, start_id: str,
               max_steps: int) -> EditResult:
    """Carry out an edit plan with the MCP tools. Never raises.

    The editor may create as many intermediate images as it needs; once the run
    is over only the final image is kept (plus everything that existed before).
    """
    folder = Path(folder)
    before = _image_ids(folder)
    try:
        result = asyncio.run(_edit(llm, plan, folder, start_id, max_steps))
    except Exception as exc:                      # MCP start-up, model or API errors
        result = EditResult(image_id=start_id, error=f"{type(exc).__name__}: {exc}")
    # On an error the final image is the start image, which is in `before`, so
    # every partial result of the failed run is removed.
    keep = result.image_id
    prune_intermediates(folder, before, keep)
    if keep not in before:
        (folder / f"{keep}.json").write_text(json.dumps(
            {"parent": start_id, "label": "; ".join(result.edits)}))
    return result
