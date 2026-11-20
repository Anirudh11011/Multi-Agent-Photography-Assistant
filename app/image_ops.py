"""Photo edits as plain functions: Pillow for I/O, NumPy/OpenCV for the pixels.

No MCP and no Streamlit here: image_tools_server.py exposes these as MCP tools,
and image_editing.py uses the I/O helpers. Every edit takes and returns an RGB
float32 array in [0, 1], so edits chain without rounding to 8 bits in between.
Each edit also returns a short human label ("Brightness +10%") that is shown to
the user as the record of what was done.
"""

import io
import math

import cv2
import numpy as np
from PIL import Image, ImageOps


# ── I/O ──────────────────────────────────────────────────────
def load(path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0


def save(arr: np.ndarray, path) -> None:
    # PNG at the fastest compression: lossless between steps, quick to write.
    Image.fromarray(to_uint8(arr)).save(path, format="PNG", compress_level=1)


def to_uint8(arr: np.ndarray) -> np.ndarray:
    return (np.clip(arr, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def decode_upload(data: bytes, max_edge: int) -> np.ndarray:
    """An uploaded file → upright RGB array, long edge capped at max_edge."""
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)
        return np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0


def encode_jpeg(path, max_edge: int | None = None, quality: int = 92) -> bytes:
    with Image.open(path) as img:
        img = img.convert("RGB")
        if max_edge:
            img.thumbnail((max_edge, max_edge), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


# ── Helpers ──────────────────────────────────────────────────
def _check(name: str, value: float, lo: float, hi: float) -> float:
    if not (lo <= value <= hi):
        raise ValueError(f"{name} must be between {lo:g} and {hi:g}, got {value:g}")
    return float(value)


def _luminance(arr: np.ndarray) -> np.ndarray:
    return arr @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _srgb_to_linear(a: np.ndarray) -> np.ndarray:
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(a: np.ndarray) -> np.ndarray:
    a = np.clip(a, 0.0, 1.0)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)


def _signed(v: float, unit: str = "") -> str:
    return f"{v:+g}{unit}"


# ── Tone and colour ──────────────────────────────────────────
def brightness(arr, percent: float):
    """Scale every pixel: +10 makes the photo 10% brighter (Pillow's Brightness)."""
    p = _check("percent", percent, -90, 200)
    return arr * (1 + p / 100), f"Brightness {_signed(p, '%')}"


def contrast(arr, percent: float):
    """Spread tones away from the mean grey: +20 is 20% more contrast."""
    p = _check("percent", percent, -90, 200)
    mean = float(_luminance(arr).mean())
    return (arr - mean) * (1 + p / 100) + mean, f"Contrast {_signed(p, '%')}"


def saturation(arr, percent: float):
    """Push colours away from grey: -100 is black and white, +30 is 30% more vivid."""
    p = _check("percent", percent, -100, 200)
    grey = _luminance(arr)[..., None]
    return grey + (arr - grey) * (1 + p / 100), f"Saturation {_signed(p, '%')}"


def exposure(arr, ev: float):
    """Exposure in stops, applied in linear light like a raw converter."""
    e = _check("ev", ev, -3, 3)
    out = _linear_to_srgb(_srgb_to_linear(np.clip(arr, 0, 1)) * (2.0 ** e))
    return out.astype(np.float32), f"Exposure {e:+.2g} EV"


def white_balance(arr, temperature: float = 0, tint: float = 0):
    """temperature: + warmer (more amber), − cooler (more blue).
    tint: + towards magenta, − towards green. Both -100..100."""
    t = _check("temperature", temperature, -100, 100) / 100
    g = _check("tint", tint, -100, 100) / 100
    gains = np.array([1 + 0.2 * t, 1 - 0.15 * g, 1 - 0.2 * t], dtype=np.float32)
    parts = []
    if t:
        parts.append(f"temperature {_signed(round(t * 100))} "
                     f"({'warmer' if t > 0 else 'cooler'})")
    if g:
        parts.append(f"tint {_signed(round(g * 100))} "
                     f"({'magenta' if g > 0 else 'green'})")
    return arr * gains, "White balance: " + (", ".join(parts) or "no change")


def shadows_highlights(arr, shadows: float = 0, highlights: float = 0):
    """shadows: + lifts dark areas. highlights: − recovers bright areas, + brightens
    them. Both -100..100. Black and white points are left where they are."""
    s = _check("shadows", shadows, -100, 100) / 100
    h = _check("highlights", highlights, -100, 100) / 100
    lum = np.clip(_luminance(arr), 0, 1)
    # Curves that are zero at pure black and pure white and peak in the shadows
    # (L≈1/3) or highlights (L≈2/3), so the end points never move.
    delta = 1.5 * s * lum * (1 - lum) ** 2 + 1.5 * h * lum ** 2 * (1 - lum)
    ratio = (lum + delta) / np.maximum(lum, 1e-4)
    parts = [f"shadows {_signed(round(s * 100))}" if s else "",
             f"highlights {_signed(round(h * 100))}" if h else ""]
    label = ", ".join(p for p in parts if p) or "no change"
    return arr * ratio[..., None], "Tone: " + label


# ── Detail ───────────────────────────────────────────────────
def sharpen(arr, amount: float = 0.6, radius: float = 1.2):
    """Unsharp mask. amount 0.1–3, radius 0.3–5 px. Apply last."""
    a = _check("amount", amount, 0.1, 3)
    r = _check("radius", radius, 0.3, 5)
    blurred = cv2.GaussianBlur(arr, (0, 0), sigmaX=r)
    return arr + a * (arr - blurred), f"Sharpen amount {a:g}, radius {r:g} px"


# ── Geometry ─────────────────────────────────────────────────
def crop_to_aspect(arr, ratio: str, anchor_x: float = 0.5, anchor_y: float = 0.5):
    """Largest crop with this aspect ratio ("1:1", "4:5", "16:9", "3:2" …).
    anchor_x/anchor_y (0–1) choose where the crop sits; 0.5 is centred."""
    try:
        rw, rh = (float(p) for p in ratio.split(":"))
        assert rw > 0 and rh > 0
    except Exception:
        raise ValueError(f'ratio must look like "16:9", got {ratio!r}') from None
    ax, ay = _check("anchor_x", anchor_x, 0, 1), _check("anchor_y", anchor_y, 0, 1)
    h, w = arr.shape[:2]
    if w / h > rw / rh:
        nw, nh = round(h * rw / rh), h
    else:
        nw, nh = w, round(w * rh / rw)
    x0, y0 = round((w - nw) * ax), round((h - nh) * ay)
    return arr[y0:y0 + nh, x0:x0 + nw], f"Crop to {ratio}"


def _largest_inner_rect(w: float, h: float, angle: float) -> tuple[float, float]:
    """Largest axis-aligned rectangle inside a w×h rectangle rotated by angle (rad)."""
    long_side, short_side = (w, h) if w >= h else (h, w)
    sin_a, cos_a = abs(math.sin(angle)), abs(math.cos(angle))
    if short_side <= 2 * sin_a * cos_a * long_side or abs(sin_a - cos_a) < 1e-10:
        x = 0.5 * short_side
        return (x / sin_a, x / cos_a) if w >= h else (x / cos_a, x / sin_a)
    cos_2a = cos_a * cos_a - sin_a * sin_a
    return (w * cos_a - h * sin_a) / cos_2a, (h * cos_a - w * sin_a) / cos_2a


def rotate(arr, degrees: float):
    """Positive = clockwise. Multiples of 90 turn the photo exactly; anything
    within ±45 straightens it and crops away the empty corners."""
    d = float(degrees)
    if d % 90 == 0:
        k = int(round(-d / 90)) % 4            # np.rot90 turns counter-clockwise
        return np.ascontiguousarray(np.rot90(arr, k)), f"Rotate {d:g}° clockwise"
    _check("degrees", d, -45, 45)
    h, w = arr.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), -d, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    bw, bh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += bw / 2 - w / 2
    m[1, 2] += bh / 2 - h / 2
    rotated = cv2.warpAffine(arr, m, (bw, bh), flags=cv2.INTER_CUBIC)
    cw, ch = _largest_inner_rect(w, h, math.radians(d))
    x0, y0 = int((bw - cw) / 2) + 1, int((bh - ch) / 2) + 1
    out = rotated[y0:y0 + int(ch) - 2, x0:x0 + int(cw) - 2]
    direction = "clockwise" if d > 0 else "counter-clockwise"
    return out, f"Straighten {abs(d):g}° {direction}"


# ── Measurement ──────────────────────────────────────────────
def stats(arr: np.ndarray) -> str:
    """Numbers that describe exposure, contrast and colour, one line."""
    a = np.clip(arr, 0, 1)
    lum = _luminance(a)
    hsv = cv2.cvtColor(to_uint8(a), cv2.COLOR_RGB2HSV)
    r, g, b = (float(a[..., i].mean()) for i in range(3))
    h, w = a.shape[:2]
    return (f"{w}×{h} px; mean brightness {lum.mean():.2f} (0 black, 1 white; ~0.45 "
            f"is typical); contrast (std) {lum.std():.2f}; clipped shadows "
            f"{(lum < 0.02).mean():.1%}; clipped highlights {(lum > 0.98).mean():.1%}; "
            f"mean saturation {hsv[..., 1].mean() / 255:.2f}; channel means "
            f"R {r:.2f} G {g:.2f} B {b:.2f}")
