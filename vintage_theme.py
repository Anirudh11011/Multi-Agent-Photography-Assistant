"""ShutterAide — all presentation lives here.

Palette, CSS, and the small markup helpers (masthead, badges, trace plates).
streamlit_app.py holds no styling.

The look is warm and quiet: paper-toned background, one serif for the wordmark,
a clean sans everywhere else. No ornament that doesn't carry information.
"""

import re

import streamlit as st

# ── Palette ──────────────────────────────────────────────────
PAPER      = "#FAF7F1"   # page
CARD       = "#FFFFFF"   # raised surfaces
LINE       = "#E4DCCD"   # hairlines
INK        = "#2C2621"   # primary text
INK_SOFT   = "#7A6E5F"   # secondary text
ACCENT     = "#9A6534"   # brand accent
ACCENT_DEEP= "#7C4F27"   # accent, pressed
SHELL      = "#241F1A"   # sidebar
SHELL_TEXT = "#E8E1D5"   # sidebar text

PAGE_TITLE = "ShutterAide"
PAGE_ICON = "📷"

USER_AVATAR = "🎞️"
BOT_AVATAR = "📷"

STEP_LABELS = {
    "gather_context":     ("Context",   "Gathered reference material"),
    "supervisor":         ("Review",    "Checked it answers the question"),
    "agent_1":            ("Scene",     "Read light, motion and depth"),
    "agent_2":            ("Answer",    "Matched settings to your camera"),
    "validate":           ("Checked",   "Format, links and credentials"),
    # Retained so traces recorded before agent_2 absorbed this step still render.
    "response_generator": ("Answer",    "Wrote the recommendation"),
    "refuse":             ("Stopped",   "No source supports an answer"),
}

TRACE_LABEL = "How this answer was reached"

# Camera pane on the right: open width, collapsed rail width, and the easing
# shared by every part of the split so the chat and pane move as one.
PANEL_WIDTH = "360px"
RAIL_WIDTH = "40px"
PANE_EASE = ".45s cubic-bezier(.2,.8,.2,1)"

_PANE_TOGGLE = (
    '<input type="checkbox" id="camera-pane-collapsed" class="camera-pane-state" '
    'aria-label="Hide the camera panel">'
    '<label for="camera-pane-collapsed" class="camera-pane-rail" title="Show the camera panel">'
    '<span class="chevron">‹</span><span class="text">{label}</span></label>'
)
_PANE_HEAD = (
    '<div class="camera-pane-head"><span class="camera-label">{label}</span>'
    '<label for="camera-pane-collapsed" class="camera-pane-hide" '
    'title="Hide the camera panel">›</label></div>'
)

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=Inter:wght@400;500;600&display=swap');

:root {{
    --paper: {PAPER};
    --card: {CARD};
    --line: {LINE};
    --ink: {INK};
    --ink-soft: {INK_SOFT};
    --accent: {ACCENT};
    --accent-deep: {ACCENT_DEEP};
    --shell: {SHELL};
    --shell-text: {SHELL_TEXT};
}}

.stApp {{ background: var(--paper); color: var(--ink); }}

html, body, [class*="css"], .stMarkdown, p, li, input, textarea, button {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}}
h1, h2, h3, h4 {{ color: var(--ink) !important; letter-spacing: -.01em; }}

.block-container {{ padding-top: 2.2rem; max-width: 860px; }}

/* ── Masthead ─────────────────────────────────────────────── */
.masthead {{ text-align: center; padding: 1.8rem 0 1.6rem; }}
.masthead h1 {{
    font-family: 'Fraunces', Georgia, serif !important;
    font-size: 2.35rem; font-weight: 600; margin: 0; letter-spacing: -.02em;
}}
.masthead .tagline {{
    font-size: .95rem; color: var(--ink-soft); margin-top: .45rem;
}}

/* ── Example chip ─────────────────────────────────────────── */
.example-wrap {{ display: flex; justify-content: center; margin: .4rem 0 1.2rem; }}
.example {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: .8rem 1.1rem;
    max-width: 460px;
    text-align: center;
    box-shadow: 0 1px 2px rgba(44,38,33,.04);
}}
.example .label {{
    font-size: .68rem; font-weight: 600; letter-spacing: .09em;
    text-transform: uppercase; color: var(--ink-soft);
}}
.example .text {{
    font-size: .93rem; color: var(--ink); margin-top: .3rem; line-height: 1.5;
}}

/* ── Sidebar ──────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{ background: var(--shell); border-right: none; }}
section[data-testid="stSidebar"] * {{ color: var(--shell-text) !important; }}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {{
    color: #FFFFFF !important; font-family: 'Inter', sans-serif !important;
    font-size: .78rem !important; font-weight: 600; letter-spacing: .09em;
    text-transform: uppercase; margin-bottom: .3rem;
}}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
section[data-testid="stSidebar"] .stCaption, section[data-testid="stSidebar"] small {{
    color: rgba(232,225,213,.62) !important; font-size: .78rem !important;
}}
section[data-testid="stSidebar"] hr {{ border-color: rgba(232,225,213,.15); }}

/* File uploader — legible on the dark shell */
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {{
    background: rgba(255,255,255,.06) !important;
    border: 1px dashed rgba(232,225,213,.35) !important;
    border-radius: 10px; padding: 1rem .9rem;
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]:hover {{
    background: rgba(255,255,255,.10) !important;
    border-color: rgba(232,225,213,.55) !important;
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] span,
section[data-testid="stSidebar"] [data-testid="stFileDropzoneInstructions"] span {{
    color: var(--shell-text) !important; font-size: .84rem !important;
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] small,
section[data-testid="stSidebar"] [data-testid="stFileDropzoneInstructions"] small {{
    color: rgba(232,225,213,.60) !important; font-size: .72rem !important;
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] svg {{
    fill: rgba(232,225,213,.75) !important; color: rgba(232,225,213,.75) !important;
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {{
    background: rgba(255,255,255,.10) !important; color: var(--shell-text) !important;
    border: 1px solid rgba(232,225,213,.35) !important; border-radius: 7px !important;
    text-transform: none !important; letter-spacing: 0 !important;
    font-size: .8rem !important; box-shadow: none !important;
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button:hover {{
    background: rgba(255,255,255,.18) !important; border-color: rgba(232,225,213,.6) !important;
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderFile"] {{
    background: rgba(255,255,255,.06); border-radius: 8px; padding: .35rem .5rem;
}}

/* ── Chat ─────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 1.05rem 1.2rem;
    margin-bottom: .9rem;
    box-shadow: 0 1px 2px rgba(44,38,33,.04);
}}
[data-testid="stChatMessage"] p {{ line-height: 1.62; }}

/* Settings table: the first thing read, so give it weight */
[data-testid="stChatMessage"] table {{
    width: 100%; border-collapse: collapse; margin: .5rem 0 1.1rem;
    font-size: .92rem;
}}
[data-testid="stChatMessage"] th {{
    text-align: left; font-size: .68rem; font-weight: 600;
    letter-spacing: .08em; text-transform: uppercase; color: var(--ink-soft);
    border-bottom: 1px solid var(--line); padding: .35rem .6rem .35rem 0;
}}
[data-testid="stChatMessage"] td {{
    padding: .42rem .6rem .42rem 0;
    border-bottom: 1px solid rgba(228,220,205,.5);
}}
[data-testid="stChatMessage"] td:first-child {{
    color: var(--ink-soft); width: 38%;
}}
[data-testid="stChatMessage"] td:last-child {{
    font-variant-numeric: tabular-nums; font-weight: 500; color: var(--ink);
}}

/* ── Source badge ─────────────────────────────────────────── */
.badge {{
    display: inline-block;
    font-size: .72rem; font-weight: 500;
    border: 1px solid var(--line);
    background: rgba(154,101,52,.07);
    color: var(--ink-soft);
    padding: .22rem .6rem; margin-bottom: .75rem; border-radius: 999px;
}}

/* ── Trace steps ──────────────────────────────────────────── */
.plate {{
    border-left: 2px solid var(--accent);
    padding: .1rem 0 .1rem .8rem;
    margin: .9rem 0 .5rem;
}}
.plate-label {{ font-size: .8rem; font-weight: 600; color: var(--ink); }}
.plate-blurb {{ font-size: .78rem; color: var(--ink-soft); margin-top: .1rem; }}

/* ── Buttons ──────────────────────────────────────────────── */
.stButton > button {{
    background: var(--accent); color: #FFFFFF !important;
    border: none; border-radius: 8px;
    font-size: .85rem; font-weight: 500; padding: .45rem .9rem;
    box-shadow: none; transition: background .12s ease;
}}
.stButton > button:hover {{ background: var(--accent-deep); }}

/* Conversation list: quiet rows, not buttons */
section[data-testid="stSidebar"] .stButton > button[kind="tertiary"] {{
    background: transparent !important; color: var(--shell-text) !important;
    border: none; border-radius: 7px; text-align: left;
    padding: .42rem .55rem; width: 100%; font-weight: 400;
}}
section[data-testid="stSidebar"] .stButton > button[kind="tertiary"]:hover {{
    background: rgba(255,255,255,.09) !important;
}}

/* ── Inputs ───────────────────────────────────────────────── */
.stTextInput input, .stTextArea textarea, [data-testid="stChatInput"] textarea {{
    background: var(--card) !important; color: var(--ink) !important;
    border: 1px solid var(--line) !important; border-radius: 10px !important;
}}
[data-testid="stChatInput"] {{ border-top: none; }}
[data-testid="stChatInput"] textarea:focus {{ border-color: var(--accent) !important; }}

/* ── Expander ─────────────────────────────────────────────── */
[data-testid="stExpander"] {{
    background: var(--card); border: 1px solid var(--line) !important;
    border-radius: 10px !important; box-shadow: none;
}}
[data-testid="stExpander"] summary {{ font-size: .84rem; color: var(--ink-soft); }}

/* ── Camera pane ──────────────────────────────────────────── */
/* A split pane. When a camera is found the whole app (chat, input, header)
   narrows from the right, and the pane fills the strip that frees up.

   camera-dock         always rendered, so the chat after it never shifts
                       position (which would rebuild it); fixed, so it takes
                       no room.
   camera-split-*      keyed on the cameras shown: a new camera is a new
                       element, so it slides in fresh and starts expanded.
   camera-pane         the pane itself, with a full-height divider.
   #camera-pane-collapsed  a checkbox, flipped by the pane's hide button and by
                       the rail. Pure CSS on purpose: a Streamlit button would
                       rerun the script, and a rerun mid-answer discards it. */
.st-key-camera-dock {{ position: fixed; top: 0; right: 0; width: 0; height: 0; }}

.stAppViewContainer {{ transition: right {PANE_EASE}; }}
.stApp:has(.st-key-camera-pane) .stAppViewContainer {{ right: {PANEL_WIDTH}; }}
.stApp:has(#camera-pane-collapsed:checked) .stAppViewContainer {{ right: {RAIL_WIDTH}; }}

.st-key-camera-pane {{
    position: fixed; top: 0; right: 0; width: {PANEL_WIDTH};
    height: 100vh; height: 100dvh; overflow-y: auto;
    z-index: 100;
    background: var(--card);
    border-left: 1px solid var(--line);
    padding: 1.25rem 1.25rem 1rem;
    gap: .9rem;
    transition: transform {PANE_EASE};
    animation: camera-pane-in {PANE_EASE};
}}
@keyframes camera-pane-in {{ from {{ transform: translateX(100%); }} }}
.stApp:has(#camera-pane-collapsed:checked) .st-key-camera-pane {{
    transform: translateX(100%);
}}
.st-key-camera-pane img {{ border-radius: 10px; max-height: 38vh; object-fit: contain; }}
.st-key-camera-pane [data-testid="stImageCaption"] {{
    color: var(--ink); font-size: .84rem; font-weight: 500;
}}
/* Comparing two cameras: a hairline between them. */
.st-key-camera-pane [data-testid="stElementContainer"]:has([data-testid="stImage"])
    ~ [data-testid="stElementContainer"]:has([data-testid="stImage"]) {{
    border-top: 1px solid var(--line);
    padding-top: .9rem;
}}

.camera-pane-head {{
    display: flex; align-items: center; justify-content: space-between;
}}
.camera-label {{
    font-size: .68rem; font-weight: 600; letter-spacing: .09em;
    text-transform: uppercase; color: var(--ink-soft);
}}
.camera-pane-hide {{
    display: grid; place-items: center; width: 28px; height: 28px;
    border-radius: 7px; cursor: pointer;
    color: var(--ink-soft); font-size: 1.35rem; line-height: 1;
}}
.camera-pane-hide:hover {{ background: rgba(154,101,52,.08); color: var(--ink); }}

/* Visually hidden but still reachable by keyboard: Tab to it, Space toggles. */
.camera-pane-state {{
    position: fixed; width: 1px; height: 1px; opacity: 0; pointer-events: none;
}}
.stApp:has(.camera-pane-state:focus-visible) :is(.camera-pane-hide, .camera-pane-rail) {{
    outline: 2px solid var(--accent); outline-offset: -2px;
}}

/* The rail: a slim strip at the right edge while the pane is collapsed. */
.camera-pane-rail {{
    position: fixed; top: 0; right: 0; width: {RAIL_WIDTH};
    height: 100vh; height: 100dvh; z-index: 100;
    display: flex; flex-direction: column; align-items: center; gap: .5rem;
    padding-top: 1.1rem;
    background: var(--card); border-left: 1px solid var(--line);
    cursor: pointer; color: var(--ink-soft);
    font-size: .68rem; font-weight: 600; letter-spacing: .09em; text-transform: uppercase;
    transform: translateX(100%);
    transition: transform {PANE_EASE};
}}
.camera-pane-rail .chevron {{ font-size: 1.35rem; line-height: 1; letter-spacing: 0; }}
.camera-pane-rail .text {{ writing-mode: vertical-rl; }}
.camera-pane-rail:hover {{ color: var(--ink); background: var(--paper); }}
.stApp:has(#camera-pane-collapsed:checked) .camera-pane-rail {{ transform: none; }}

/* Too narrow to split: the pane opens over the chat instead of beside it. */
@media (max-width: 1100px) {{
    .stApp:has(.st-key-camera-pane) .stAppViewContainer {{ right: {RAIL_WIDTH}; }}
    .st-key-camera-pane {{
        width: min({PANEL_WIDTH}, 88vw);
        box-shadow: -12px 0 32px rgba(44,38,33,.14);
    }}
}}
@media (prefers-reduced-motion: reduce) {{
    .stAppViewContainer, .st-key-camera-pane, .camera-pane-rail {{
        transition: none; animation: none;
    }}
}}

hr {{ border-color: var(--line); }}
footer, #MainMenu {{ visibility: hidden; }}
.caption {{ color: var(--ink-soft); font-size: .87rem; line-height: 1.6; }}
</style>
"""

TAGLINE = "Camera settings for the scene in front of you."
EXAMPLE = "What settings for a mountain landscape on a Canon R5?"


def configure_page() -> None:
    """st.set_page_config — must run before any other Streamlit call."""
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="centered",
        initial_sidebar_state="expanded",
    )


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def masthead(title: str = PAGE_TITLE, tagline: str = TAGLINE) -> None:
    """Centred wordmark: icon plate, name, one line of tagline."""
    st.markdown(
        f'<div class="masthead"><h1>{title}</h1>'
        f'<div class="tagline">{tagline}</div></div>',
        unsafe_allow_html=True,
    )


def example_card(text: str = EXAMPLE) -> None:
    """Rounded card showing one sample question."""
    st.markdown(
        f'<div class="example-wrap"><div class="example">'
        f'<div class="label">Try asking</div>'
        f'<div class="text">{text}</div></div></div>',
        unsafe_allow_html=True,
    )


def plate_header(node: str) -> None:
    title, blurb = STEP_LABELS.get(node, (node, ""))
    st.markdown(
        f'<div class="plate"><div class="plate-label">{title}</div>'
        f'<div class="plate-blurb">{blurb}</div></div>',
        unsafe_allow_html=True,
    )


def badge(text: str) -> None:
    st.markdown(f'<span class="badge">{text}</span>', unsafe_allow_html=True)


def caption(text: str) -> None:
    st.markdown(f'<p class="caption">{text}</p>', unsafe_allow_html=True)


def step_status_label(node: str) -> str:
    title, blurb = STEP_LABELS.get(node, (node, ""))
    return f"{title}: {blurb}"


def camera_panel(cameras) -> None:
    """Split pane on the right with the camera(s) the conversation is about.

    cameras: list of (name, image path), at most two, stacked in order. With
    none, the chat stays full width. See the camera pane CSS for how the pieces
    fit together.
    """
    with st.container(key="camera-dock"):
        if not cameras:
            # Something must take the pane's slot: Streamlit leaves a dropped
            # element on screen until the run ends — the whole agent run.
            st.empty()
            return
        key = "camera-split-" + "-".join(re.sub(r"[^a-z0-9]+", "-", path.name.lower())
                                         for _, path in cameras)
        label = "Camera" if len(cameras) == 1 else "Cameras"
        with st.container(key=key):
            st.html(_PANE_TOGGLE.format(label=label))
            with st.container(key="camera-pane"):
                st.html(_PANE_HEAD.format(label=label))
                for name, path in cameras:
                    st.image(str(path), caption=name, width="stretch")


def render_trace(steps) -> None:
    """steps: list of (node_name, text)."""
    with st.expander(TRACE_LABEL):
        for node, body in steps:
            plate_header(node)
            st.markdown(body or "_(nothing recorded)_")
