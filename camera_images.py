"""Camera pictures — which camera a question is about, and the image to show.

Images live in assets/cameras/, and cameras.json beside them names each one.
The rules, applied to the question only (never the answer):

    names no camera   →  keep what the previous turn showed
    names cameras     →  show the ones that have an image, at most two, in the
                         order named; if none has one, show nothing

"Names a camera" is deliberately wider than "has an image": asking about a
Canon R6 must clear a Sony a6700 picture even when there is no R6 picture. So a
mention is anything in the registry, or anything the brand/model patterns below
recognise. Those patterns are a heuristic — a model they miss, and that isn't
in the registry, reads as "names no camera" and keeps the previous picture.
"""

import functools
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ASSET_DIR = Path(__file__).parent / "assets" / "cameras"
REGISTRY = ASSET_DIR / "cameras.json"
MAX_SHOWN = 2

BRANDS = ("sony", "canon", "nikon", "fujifilm", "fuji", "panasonic", "olympus",
          "om system", "leica", "pentax", "ricoh", "sigma", "hasselblad", "dji",
          "gopro", "insta360", "apple", "google", "samsung", "blackmagic")
# Line names that sit between brand and model: "Canon EOS R5", "Lumix GH7".
SERIES = ("eos", "lumix", "alpha")

ROMAN = {"1": "i", "2": "ii", "3": "iii", "4": "iv", "5": "v", "6": "vi"}

_START = r"(?<![a-z0-9])"
_END = r"(?![a-z0-9])"
_BRAND_RE = "|".join(b.replace(" ", r"[\s\-]?") for b in BRANDS)
_PREFIX_RE = re.compile(rf"(?:{_BRAND_RE}|{'|'.join(SERIES)})[\s\-]+")
# A trailing generation makes it a different camera: "r6 ii" is not the "r6".
_NOT_NEWER = r"(?![\s\-_]*(?:ii|iii|iv|v|vi)" + _END + ")"

GENERIC = (
    # Brand, optional line name, then a model: letters-then-digits ("a6700",
    # "r6", "x-t5", "gh7") or Canon's digits-then-d ("90d"). Lens and exposure
    # tokens ("50mm", "24-70", "f1.8", "iso400", "rf24-105") are excluded.
    re.compile(_START + rf"(?:{_BRAND_RE})(?:[\s\-]+(?:{'|'.join(SERIES)}))?[\s\-]+"
               r"(?:(?!f\d|iso|ev|nd|ef|rf|fe|xf|xc|sel|dt)[a-z][a-z\-]*\d[a-z0-9]*"
               r"|\d{1,4}d)" + _END),
    # The model codes people type without a brand.
    re.compile(_START + "(?:" + "|".join((
        r"a(?:[179][a-z0-9]*|[3-6]\d{3}[a-z]*)",       # Sony a1, a7 / a7iv / a7s3, a9, a6700
        r"(?:zv[\s\-]?e?|fx|rx)\d{1,3}[a-z]*",         # Sony zv-e10, fx3, rx100vii
        r"r\d{1,3}[a-z]*", r"(?:[5-7]|\d{2,4})d",      # Canon r6, r50; 5d, 90d
        r"z[\s\-]?\d{1,2}[a-z]*", r"zfc?", r"d\d{3,4}[a-z]*",   # Nikon z6ii, zf; d850
        r"x[\s\-]?(?:t|h|s|e|pro)\d{1,2}[a-z]*", r"x100[a-z]*",  # Fujifilm x-t5, x100vi
        r"gfx[\s\-]?\d{2,3}[a-z]*",
        r"gh?\d{1,3}[a-z]*", r"s[159][a-z]*",          # Panasonic gh7, g9, s5ii
        r"om[\s\-]?[135][a-z]*", r"e[\s\-]?m\d{1,2}[a-z]*",     # OM System, Olympus
        r"iphone[\s\-]?\d{1,2}", r"pixel[\s\-]?\d{1,2}a?", r"galaxy[\s\-]?s\d{2}",
        r"hero[\s\-]?\d{1,2}",
    )) + ")" + _END),
)


@dataclass(frozen=True)
class Camera:
    file: str   # image file name, relative to ASSET_DIR — what a turn stores
    name: str   # caption under the picture


def _normalise(text: str) -> str:
    """Lowercase, and fold the spellings of one model together:
    'α6700' / 'Alpha 6700' → 'a6700', 'Mark II' / 'mk2' → 'ii'."""
    text = unicodedata.normalize("NFKC", text).lower().replace("α", "a")
    text = re.sub(_START + r"alpha[\s\-]*(?=\d)", "a", text)
    return re.sub(r"(?<![a-z])(?:mark|mk)[\s\-_]*([1-6]|iv|vi|v|i{1,3})" + _END,
                  lambda m: ROMAN.get(m.group(1), m.group(1)), text)


def _pattern(alias: str) -> re.Pattern | None:
    """'a6700' matches 'a6700', 'a 6700' and 'a-6700' as a whole token."""
    parts = re.findall(r"[a-z]+|\d+", _normalise(alias))
    if not parts:
        return None
    return re.compile(_START + r"[\s\-_]*".join(parts) + _END + _NOT_NEWER)


def _short_names(name: str) -> list[str]:
    """'Canon EOS R5' → ['canon eos r5', 'eos r5', 'r5']: the forms people type."""
    forms = [_normalise(name).strip()]
    while m := _PREFIX_RE.match(forms[-1]):
        forms.append(forms[-1][m.end():])
    # A bare brand or line word ("eos"), or a single letter ("Leica M" → "m"),
    # would match far too much on its own.
    return [f for f in forms if len(re.sub(r"[^a-z0-9]", "", f)) >= 2
            and not _PREFIX_RE.fullmatch(f + " ")]


@functools.lru_cache(maxsize=4)
def _parse(path: str, mtime: float) -> tuple[tuple, tuple[str, ...]]:
    """Read cameras.json into (aliases, problems), longest alias first.

    Re-read whenever the file changes. A bad entry is skipped and reported, never
    fatal — without a usable registry the app simply shows no pictures.
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return (), (f"cameras.json could not be read: {exc}",)
    if not isinstance(raw, list):
        return (), ("cameras.json should be a list of cameras — see assets/cameras/README.md.",)

    aliases, problems = [], []
    for number, item in enumerate(raw, 1):
        item = item if isinstance(item, dict) else {}
        name, file, extra = item.get("name"), item.get("file"), item.get("aliases", [])
        if not (isinstance(name, str) and name.strip() and isinstance(file, str)
                and file.strip() and isinstance(extra, list)):
            problems.append(f'cameras.json entry {number} needs a "name" and a "file".')
            continue
        camera = Camera(file=file.strip(), name=name.strip())
        forms = _short_names(name) + [a for a in extra if isinstance(a, str)]
        seen = set()
        for form in forms:
            pattern = _pattern(form)
            if pattern and pattern.pattern not in seen:
                seen.add(pattern.pattern)
                aliases.append((len(re.sub(r"[^a-z0-9]", "", _normalise(form))),
                                pattern, camera))
    aliases.sort(key=lambda a: -a[0])
    return tuple(aliases), tuple(problems)


def _registry() -> tuple[tuple, tuple[str, ...]]:
    try:
        mtime = REGISTRY.stat().st_mtime
    except OSError:
        return (), ()
    return _parse(str(REGISTRY), mtime)


def _image(file: str) -> Path | None:
    """The image on disk, forgiving letter case — macOS doesn't care, Linux does."""
    exact = ASSET_DIR / file
    if exact.is_file():
        return exact
    if ASSET_DIR.is_dir():
        for candidate in ASSET_DIR.iterdir():
            if candidate.name.lower() == file.lower() and candidate.is_file():
                return candidate
    return None


def _mentions(question: str) -> list[Camera | None]:
    """Cameras named in the question, in the order named. None stands for a
    camera the registry doesn't know."""
    text = _normalise(question)
    aliases, _ = _registry()
    taken: list[tuple[int, int, Camera | None]] = []

    def claim(match: re.Match, camera: Camera | None) -> None:
        if all(match.end() <= start or match.start() >= end for start, end, _ in taken):
            taken.append((match.start(), match.end(), camera))

    # Registry first, longest alias first, so "sony a7 iv" claims its span before
    # "a7 iv" can, and before the generic patterns see it as an unknown camera.
    for _, pattern, camera in aliases:
        for match in pattern.finditer(text):
            claim(match, camera)
    for pattern in GENERIC:
        for match in pattern.finditer(text):
            claim(match, None)
    return [camera for _, _, camera in sorted(taken, key=lambda t: t[0])]


def for_turn(question: str, previous: list[str]) -> list[str]:
    """Image files to show for this turn — see the module docstring for the rules."""
    named = _mentions(question)
    if not named:
        return list(previous)
    shown = []
    for camera in named:
        if camera and camera.file not in shown and _image(camera.file):
            shown.append(camera.file)
    return shown[:MAX_SHOWN]


def resolve(files: list[str]) -> list[tuple[str, Path]]:
    """(caption, image path) for each stored file whose image is still on disk."""
    aliases, _ = _registry()
    names = {camera.file: camera.name for _, _, camera in aliases}
    shown = []
    for file in files:
        path = _image(file)
        if path and file in names:
            shown.append((names[file], path))
    return shown


def problems() -> list[str]:
    """What's wrong with cameras.json, if anything — shown in the sidebar."""
    return list(_registry()[1])
