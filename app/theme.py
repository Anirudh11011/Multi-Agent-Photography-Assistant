"""ShutterAide — all presentation lives here.

Palette, CSS, and the small markup helpers (masthead, badges, trace plates).
streamlit_app.py holds no styling.

The look is a night sky behind glass: the aurora photograph sits dimmed behind
everything, and each surface (sidebar, messages, camera pane) is a translucent
panel that blurs what is behind it. One gradient, taken from the aurora, marks
the things you can act on.
"""

import re

import streamlit as st

# ── Palette ──────────────────────────────────────────────────
NIGHT      = "#060A13"                  # page, behind the photograph
GLASS      = "rgba(13, 20, 34, .56)"    # raised surfaces
GLASS_DEEP = "rgba(8, 13, 24, .62)"     # sidebar, camera pane
LINE       = "rgba(255, 255, 255, .10)" # hairlines
TEXT       = "#EAF1F8"                  # primary text
TEXT_SOFT  = "#9FB0C3"                  # secondary text
ACCENT     = "#34E0B4"                  # aurora green
ACCENT_2   = "#8B7CF6"                  # aurora violet
ON_ACCENT  = "#04121A"                  # text on the gradient
GRADIENT   = "linear-gradient(135deg, #2EE6B6 0%, #38BDF8 55%, #8B7CF6 100%)"

# Served by Streamlit's static file server (server.enableStaticServing) from
# static/ beside the app. If it can't load, the gradients under it still read
# as a night sky.
BACKDROP_URL = "app/static/aurora.jpg"
BACKDROP_OPACITY = ".36"

PAGE_TITLE = "ShutterAide"
PAGE_ICON = "📷"

USER_AVATAR = ":material/person:"
BOT_AVATAR = ":material/photo_camera:"

UPLOAD_HINT = "Add your camera manual"

STEP_LABELS = {
    "triage":             ("Intake",    "Worked out what you're asking"),
    "redirect":           ("Replied",   "No search needed for this message"),
    "gather_context":     ("Context",   "Gathered reference material"),
    "supervisor":         ("Review",    "Checked it answers the question"),
    "agent_1":            ("Scene",     "Read light, motion and depth"),
    "agent_2":            ("Answer",    "Wrote advice for your camera"),
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
:root {{
    --night: {NIGHT};
    --glass: {GLASS};
    --glass-deep: {GLASS_DEEP};
    --line: {LINE};
    --text: {TEXT};
    --text-soft: {TEXT_SOFT};
    --accent: {ACCENT};
    --accent-2: {ACCENT_2};
    --on-accent: {ON_ACCENT};
    --gradient: {GRADIENT};
    --blur: blur(22px) saturate(150%);
    --shadow: 0 10px 30px rgba(0,0,0,.24), inset 0 1px 0 rgba(255,255,255,.05);
}}

/* ── Backdrop ─────────────────────────────────────────────── */
/* The photograph is one fixed layer under the whole app, dimmed so it sets the
   mood without competing with the text. Nothing that contains the camera pane
   may take a filter, backdrop-filter or transform: any of them would become
   the pane's containing block and break its position: fixed. */
.stApp {{
    color: var(--text);
    background:
        radial-gradient(60% 50% at 28% 18%, rgba(46,230,182,.16), transparent 70%),
        radial-gradient(50% 45% at 88% 12%, rgba(139,124,246,.18), transparent 70%),
        var(--night);
}}
.stApp::before {{
    content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background:
        linear-gradient(180deg, rgba(6,10,19,.10) 0%, rgba(6,10,19,.55) 100%),
        url("{BACKDROP_URL}") center / cover no-repeat;
    opacity: {BACKDROP_OPACITY};
    filter: blur(2px) saturate(1.15);
    transform: scale(1.03);
}}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stDecoration"] {{ display: none; }}

h1, h2, h3, h4 {{ color: var(--text) !important; letter-spacing: -.01em; }}
a {{ color: var(--accent) !important; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
::selection {{ background: rgba(52,224,180,.30); }}
:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}

* {{ scrollbar-width: thin; scrollbar-color: rgba(255,255,255,.18) transparent; }}
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-thumb {{
    background: rgba(255,255,255,.16); border-radius: 999px;
    border: 3px solid transparent; background-clip: content-box;
}}
::-webkit-scrollbar-thumb:hover {{ background-color: rgba(255,255,255,.28); }}

[data-testid="stMainBlockContainer"] {{ padding-top: 2.2rem; max-width: 860px; }}

/* ── Masthead ─────────────────────────────────────────────── */
.masthead {{ text-align: center; padding: 1.4rem 0 1.5rem; }}
.masthead .logo {{
    position: relative; width: 52px; height: 52px; margin: 0 auto .9rem;
    border-radius: 16px; background: var(--gradient);
    box-shadow: 0 10px 34px rgba(52,224,180,.30), inset 0 1px 0 rgba(255,255,255,.35);
}}
/* A lens, drawn with two rings. */
.masthead .logo::before, .masthead .logo::after {{
    content: ""; position: absolute; border-radius: 50%;
    top: 50%; left: 50%; transform: translate(-50%, -50%);
}}
.masthead .logo::before {{ width: 26px; height: 26px; border: 3px solid var(--on-accent); }}
.masthead .logo::after {{ width: 8px; height: 8px; background: var(--on-accent); }}
.masthead .wordmark {{
    font-size: 2.5rem; font-weight: 700; line-height: 1.15; letter-spacing: -.035em;
    background: linear-gradient(92deg, #FFFFFF 0%, #B9FFEA 45%, #B7BEFF 100%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.masthead .tagline {{
    font-size: 1rem; color: var(--text-soft); margin-top: .45rem;
}}

/* ── Example chip ─────────────────────────────────────────── */
.example-wrap {{ display: flex; justify-content: center; margin: .4rem 0 1.2rem; }}
.example {{
    background: var(--glass);
    border: 1px solid var(--line);
    border-radius: 18px;
    padding: .85rem 1.25rem;
    max-width: 460px;
    text-align: center;
    -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
    box-shadow: var(--shadow);
}}
.example .label {{
    font-size: .68rem; font-weight: 600; letter-spacing: .09em;
    text-transform: uppercase; color: var(--accent);
}}
.example .text {{
    font-size: .95rem; color: var(--text); margin-top: .3rem; line-height: 1.5;
}}

/* ── Sidebar ──────────────────────────────────────────────── */
section[data-testid="stSidebar"] {{
    background: var(--glass-deep);
    -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
    border-right: 1px solid var(--line);
}}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {{
    color: var(--text-soft) !important;
    font-size: .7rem !important; font-weight: 600; letter-spacing: .1em;
    text-transform: uppercase; margin: .6rem 0 .1rem; padding: 0;
}}
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
    color: var(--text-soft) !important; font-size: .76rem !important;
}}

/* File uploader, reduced to a "+" and one line. The whole row opens the file
   picker and still accepts a drop. Once files are attached Streamlit lists
   them in the same box, with its own "add" button for more. */
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {{
    display: flex; flex-direction: row; align-items: center; justify-content: flex-start;
    gap: .7rem; min-height: 0; height: auto;
    padding: .5rem .65rem;
    background: rgba(255,255,255,.04) !important;
    border: 1px dashed rgba(255,255,255,.20) !important;
    border-radius: 16px; cursor: pointer;
    transition: background .2s ease, border-color .2s ease;
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]:hover {{
    background: rgba(52,224,180,.07) !important;
    border-color: rgba(52,224,180,.55) !important;
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzoneInstructions"] {{
    display: none;
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]:not(:has([data-testid="stFileChips"]))::after {{
    content: "{UPLOAD_HINT}"; font-size: .86rem; font-weight: 500; color: var(--text);
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]:has([data-testid="stFileChips"]) > div {{ width: 100%; }}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] :is(button[kind="secondary"], button[kind="borderlessIcon"]) {{
    position: relative; flex: none;
    width: 34px; height: 34px; min-height: 0; padding: 0; margin: 0;
    display: grid; place-items: center;
    border: none !important; border-radius: 50% !important;
    background: var(--gradient) !important;
    box-shadow: 0 4px 14px rgba(52,224,180,.28);
    transition: transform .15s ease, box-shadow .2s ease;
}}
/* The button's own label stays for screen readers; only the "+" is seen. */
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] :is(button[kind="secondary"], button[kind="borderlessIcon"]) > * {{
    position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%);
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] :is(button[kind="secondary"], button[kind="borderlessIcon"])::before {{
    content: "+"; font-size: 1.45rem; font-weight: 400; line-height: 1;
    color: var(--on-accent);
}}
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"]:hover :is(button[kind="secondary"], button[kind="borderlessIcon"]) {{
    transform: scale(1.06); box-shadow: 0 6px 18px rgba(52,224,180,.40);
}}
section[data-testid="stSidebar"] [data-testid="stFileChip"] {{
    background: rgba(255,255,255,.06); border: 1px solid var(--line);
    border-radius: 12px;
}}

/* ── Chat ─────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {{
    background: var(--glass);
    border: 1px solid var(--line);
    border-radius: 20px;
    padding: 1.05rem 1.2rem;
    margin-bottom: .9rem;
    -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
    box-shadow: var(--shadow);
    animation: message-in .35s ease both;
}}
@keyframes message-in {{ from {{ opacity: 0; transform: translateY(6px); }} }}
[data-testid="stChatMessage"] p {{ line-height: 1.62; }}
/* The question: tinted with the accent so the two voices read apart. */
[data-testid="stChatMessage"]:has(.from-user) {{
    background: linear-gradient(135deg, rgba(46,230,182,.13), rgba(139,124,246,.13)),
                var(--glass);
    border-color: rgba(52,224,180,.22);
}}
[data-testid="stElementContainer"]:has(.from-user) {{ display: none; }}
[data-testid="stChatMessage"] [data-testid^="stChatMessageAvatar"] {{
    border-radius: 12px;
    background: rgba(255,255,255,.08); color: var(--text);
}}
[data-testid="stChatMessage"]:not(:has(.from-user)) [data-testid^="stChatMessageAvatar"] {{
    background: var(--gradient); color: var(--on-accent);
}}
[data-testid="stChatMessage"] code {{
    background: rgba(255,255,255,.08); color: #C9F7EA; border-radius: 6px;
}}

/* Settings table: the first thing read, so give it weight */
[data-testid="stChatMessage"] table {{
    width: 100%; border-collapse: collapse; margin: .5rem 0 1.1rem;
    font-size: .92rem;
}}
[data-testid="stChatMessage"] th {{
    text-align: left; font-size: .68rem; font-weight: 600;
    letter-spacing: .08em; text-transform: uppercase; color: var(--text-soft);
    border: none; border-bottom: 1px solid rgba(255,255,255,.16);
    padding: .35rem .6rem .45rem 0;
}}
[data-testid="stChatMessage"] td {{
    padding: .48rem .6rem .48rem 0;
    border: none; border-bottom: 1px solid rgba(255,255,255,.07);
}}
[data-testid="stChatMessage"] tr:last-child td {{ border-bottom: none; }}
[data-testid="stChatMessage"] td:first-child {{
    color: var(--text-soft); width: 38%;
}}
[data-testid="stChatMessage"] td:last-child {{
    font-variant-numeric: tabular-nums; font-weight: 600; color: var(--text);
}}

/* ── Source badge ─────────────────────────────────────────── */
.badge {{
    display: inline-flex; align-items: center; gap: .4rem;
    font-size: .72rem; font-weight: 500;
    border: 1px solid rgba(52,224,180,.28);
    background: rgba(52,224,180,.10);
    color: #A6F4DF;
    padding: .22rem .65rem; margin-bottom: .75rem; border-radius: 999px;
}}
.badge::before {{
    content: ""; width: 6px; height: 6px; border-radius: 50%;
    background: var(--accent); box-shadow: 0 0 8px var(--accent);
}}

/* ── Trace steps ──────────────────────────────────────────── */
.plate {{
    border-left: 2px solid var(--accent);
    padding: .1rem 0 .1rem .8rem;
    margin: .9rem 0 .5rem;
}}
.plate-label {{ font-size: .8rem; font-weight: 600; color: var(--text); }}
.plate-blurb {{ font-size: .78rem; color: var(--text-soft); margin-top: .1rem; }}

/* ── Buttons ──────────────────────────────────────────────── */
.stButton > button {{
    background: rgba(255,255,255,.06); color: var(--text) !important;
    border: 1px solid var(--line); border-radius: 999px;
    font-size: .85rem; font-weight: 500; padding: .45rem 1rem;
    transition: transform .15s ease, box-shadow .2s ease,
                background .2s ease, border-color .2s ease;
}}
.stButton > button:hover {{
    background: rgba(255,255,255,.11); border-color: rgba(255,255,255,.22);
    transform: translateY(-1px);
}}
.stButton > button:active {{ transform: translateY(0); }}

.stButton > button[kind="primary"] {{
    background: var(--gradient); border: none; font-weight: 600;
    box-shadow: 0 6px 20px rgba(52,224,180,.26), inset 0 1px 0 rgba(255,255,255,.30);
}}
.stButton > button[kind="primary"], .stButton > button[kind="primary"] * {{
    color: var(--on-accent) !important;
}}
.stButton > button[kind="primary"]:hover {{
    background: var(--gradient); filter: brightness(1.07);
    box-shadow: 0 10px 28px rgba(52,224,180,.38), inset 0 1px 0 rgba(255,255,255,.30);
}}

.stButton > button[kind="tertiary"] {{
    background: transparent; border: 1px solid transparent;
    color: var(--text-soft) !important;
}}
.stButton > button[kind="tertiary"]:hover {{
    background: rgba(255,255,255,.08); color: var(--text) !important;
}}

/* Conversation list: quiet rows; the open one (kind="secondary") is lit. */
section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]) {{
    justify-content: flex-start; text-align: left;
    width: 100%; border-radius: 12px; padding: .46rem .7rem; font-weight: 400;
}}
section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]) > div,
section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]) > div > span {{
    justify-content: flex-start; width: 100%; min-width: 0;
}}
section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]):hover {{
    transform: none;
}}
.st-key-chat-list {{ gap: .2rem; }}
/* Feedback: two small buttons side by side, never wrapping. */
[class*="st-key-feedback-"] {{ gap: .25rem; }}
[class*="st-key-feedback-"] button {{ white-space: nowrap; padding: .3rem .7rem; font-size: .8rem; }}
section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]) p {{
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
section[data-testid="stSidebar"] .stButton > button[kind="secondary"] {{
    background: rgba(52,224,180,.11); border-color: rgba(52,224,180,.26);
    color: var(--text) !important; font-weight: 500;
}}

/* ── Inputs ───────────────────────────────────────────────── */
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {{
    background: transparent;
}}
/* The answer scrolls under the input: blur it out, fading in from the top. */
[data-testid="stBottom"]::before {{
    content: ""; position: absolute; inset: -1.5rem 0 0; z-index: -1; pointer-events: none;
    background: linear-gradient(180deg, rgba(6,10,19,0) 0%, rgba(6,10,19,.82) 55%);
    -webkit-backdrop-filter: blur(14px); backdrop-filter: blur(14px);
    -webkit-mask-image: linear-gradient(180deg, transparent 0%, #000 45%);
    mask-image: linear-gradient(180deg, transparent 0%, #000 45%);
}}
[data-testid="stChatInput"] > div {{
    background: rgba(13,20,34,.72); border: 1px solid rgba(255,255,255,.14);
    border-radius: 22px;
    box-shadow: 0 12px 36px rgba(0,0,0,.34), inset 0 1px 0 rgba(255,255,255,.06);
    transition: border-color .2s ease, box-shadow .2s ease;
}}
[data-testid="stChatInput"] > div:focus-within {{
    border-color: rgba(52,224,180,.60);
    box-shadow: 0 12px 36px rgba(0,0,0,.34), 0 0 0 4px rgba(52,224,180,.14);
}}
[data-testid="stChatInput"] textarea {{
    background: transparent !important; color: var(--text) !important;
    caret-color: var(--accent);
    outline: none;   /* the rounded box around it shows focus */
}}
[data-testid="stChatInput"] textarea::placeholder {{ color: var(--text-soft); opacity: .85; }}
[data-testid="stChatInputSubmitButton"] {{
    border-radius: 50% !important;
    transition: transform .15s ease, background .2s ease;
}}
[data-testid="stChatInputSubmitButton"]:not(:disabled) {{
    background: var(--gradient) !important; color: var(--on-accent) !important;
}}
[data-testid="stChatInputSubmitButton"]:not(:disabled):hover {{ transform: scale(1.07); }}

/* ── Expander, status, alerts ─────────────────────────────── */
[data-testid="stExpander"] details {{
    background: rgba(255,255,255,.035); border: 1px solid var(--line);
    border-radius: 14px; overflow: hidden;
}}
[data-testid="stExpander"] summary {{ font-size: .84rem; color: var(--text-soft); }}
[data-testid="stExpander"] summary:hover {{ color: var(--text); }}
[data-testid="stAlertContainer"] {{ border-radius: 14px; }}

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
    background: var(--glass-deep);
    -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
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
.st-key-camera-pane img {{
    border-radius: 16px; max-height: 38vh; object-fit: contain;
    box-shadow: 0 12px 32px rgba(0,0,0,.35);
}}
.st-key-camera-pane [data-testid="stImageCaption"] {{
    color: var(--text); font-size: .86rem; font-weight: 500;
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
    font-size: .7rem; font-weight: 600; letter-spacing: .1em;
    text-transform: uppercase; color: var(--text-soft);
}}
.camera-pane-hide {{
    display: grid; place-items: center; width: 30px; height: 30px;
    border-radius: 10px; cursor: pointer;
    color: var(--text-soft); font-size: 1.35rem; line-height: 1;
    transition: background .2s ease, color .2s ease;
}}
.camera-pane-hide:hover {{ background: rgba(255,255,255,.09); color: var(--text); }}

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
    background: var(--glass-deep);
    -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
    border-left: 1px solid var(--line);
    cursor: pointer; color: var(--text-soft);
    font-size: .7rem; font-weight: 600; letter-spacing: .1em; text-transform: uppercase;
    transform: translateX(100%);
    transition: transform {PANE_EASE}, color .2s ease, background .2s ease;
}}
.camera-pane-rail .chevron {{ font-size: 1.35rem; line-height: 1; letter-spacing: 0; }}
.camera-pane-rail .text {{ writing-mode: vertical-rl; }}
.camera-pane-rail:hover {{ color: var(--accent); background: rgba(13,20,34,.80); }}
.stApp:has(#camera-pane-collapsed:checked) .camera-pane-rail {{ transform: none; }}

/* Too narrow to split: the pane opens over the chat instead of beside it. */
@media (max-width: 1100px) {{
    .stApp:has(.st-key-camera-pane) .stAppViewContainer {{ right: {RAIL_WIDTH}; }}
    .st-key-camera-pane {{
        width: min({PANEL_WIDTH}, 88vw);
        box-shadow: -16px 0 40px rgba(0,0,0,.45);
    }}
}}
@media (prefers-reduced-motion: reduce) {{
    .stAppViewContainer, .st-key-camera-pane, .camera-pane-rail,
    [data-testid="stChatMessage"], .stButton > button {{
        transition: none; animation: none;
    }}
}}

hr {{ border-color: var(--line); }}
footer {{ visibility: hidden; }}
.caption {{ color: var(--text-soft); font-size: .84rem; line-height: 1.6; }}
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
        initial_sidebar_state="auto",   # open on desktop, closed on phones
    )


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def masthead(title: str = PAGE_TITLE, tagline: str = TAGLINE) -> None:
    """Centred wordmark: logo, name, one line of tagline."""
    st.markdown(
        f'<div class="masthead"><div class="logo"></div>'
        f'<div class="wordmark" role="heading" aria-level="1">{title}</div>'
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


def user_message():
    """A chat bubble for the person asking, tinted apart from the answers."""
    bubble = st.chat_message("user", avatar=USER_AVATAR)
    # Streamlit gives both roles the same markup once the avatar is custom, so
    # the CSS finds the question by this marker.
    bubble.html('<span class="from-user"></span>')
    return bubble


def assistant_message():
    return st.chat_message("assistant", avatar=BOT_AVATAR)


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
