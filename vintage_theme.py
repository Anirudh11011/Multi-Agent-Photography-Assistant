"""Vintage styling for the Streamlit console.

Everything visual lives here: palette, CSS, and the small markup helpers
(masthead, step labels, captions). streamlit_app.py holds no styling.
"""

import streamlit as st

# ── Palette ──────────────────────────────────────────────────
PAPER      = "#F2E8D5"   # aged paper
PAPER_DEEP = "#E7D9BE"   # card stock
INK        = "#3A2E21"   # sepia ink
INK_SOFT   = "#6B5842"   # faded caption ink
SEPIA      = "#8C5A2B"   # toner
RUST       = "#A6402B"   # red accent
BRASS      = "#B99457"   # brass

PAGE_TITLE = "Multi-Agent Desk"
PAGE_ICON = "◈"

USER_AVATAR = "✒️"
BOT_AVATAR = "📖"

STEP_LABELS = {
    "gather_context":     ("I. Context",    "Assembled the reference material"),
    "supervisor":         ("II. Supervisor", "Reviewed whether the material answers the question"),
    "agent_1":            ("III. Analyst",   "Interpreted the request against the sources"),
    "agent_2":            ("IV. Specialist", "Drafted the detailed answer"),
    "response_generator": ("V. Editor",      "Composed the final answer"),
    "refuse":             ("Halted",         "The material did not support an answer"),
}

TRACE_LABEL = "Agent trace — the working behind this answer"

_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,700;1,500&family=Courier+Prime:ital,wght@0,400;0,700;1,400&display=swap');

:root {{
    --paper:      {PAPER};
    --paper-deep: {PAPER_DEEP};
    --ink:        {INK};
    --ink-soft:   {INK_SOFT};
    --sepia:      {SEPIA};
    --rust:       {RUST};
    --brass:      {BRASS};
}}

/* Aged paper with a soft grain wash */
.stApp {{
    background-color: var(--paper);
    background-image:
        radial-gradient(circle at 18% 12%, rgba(185,148,87,.20), transparent 55%),
        radial-gradient(circle at 82% 88%, rgba(140,90,43,.16), transparent 60%),
        url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3'/></filter><rect width='140' height='140' filter='url(%23n)' opacity='0.05'/></svg>");
    color: var(--ink);
}}

html, body, [class*="css"], .stMarkdown, p, li {{
    font-family: 'Courier Prime', 'Courier New', monospace;
}}
h1, h2, h3, h4 {{
    font-family: 'Playfair Display', Georgia, serif !important;
    color: var(--ink) !important;
    letter-spacing: .5px;
}}

/* Masthead */
.masthead {{
    text-align: center;
    border-top: 3px double var(--sepia);
    border-bottom: 3px double var(--sepia);
    padding: 1.1rem 0 .9rem;
    margin-bottom: 1.4rem;
}}
.masthead h1 {{ font-size: 2.7rem; margin: 0; text-transform: uppercase; letter-spacing: 7px; }}
.masthead .sub {{
    font-size: .78rem; letter-spacing: 4px; text-transform: uppercase;
    color: var(--ink-soft); margin-top: .45rem;
}}
.masthead .rule {{ color: var(--brass); letter-spacing: 6px; font-size: .8rem; margin-top: .35rem; }}

/* Sidebar */
section[data-testid="stSidebar"] {{
    background: linear-gradient(175deg, #3A2E21 0%, #2A2117 100%);
    border-right: 4px double var(--brass);
}}
section[data-testid="stSidebar"] * {{ color: #EADFC8 !important; }}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {{ color: var(--brass) !important; }}

/* Chat bubbles as bordered cards */
[data-testid="stChatMessage"] {{
    background: var(--paper-deep);
    border: 1px solid rgba(140,90,43,.45);
    box-shadow: 4px 4px 0 rgba(58,46,33,.13);
    border-radius: 2px;
    padding: 1rem 1.15rem;
    margin-bottom: 1rem;
}}

/* Step header inside the agent trace */
.plate {{
    background: var(--paper-deep);
    border: 1px solid rgba(140,90,43,.4);
    border-left: 5px solid var(--sepia);
    padding: .85rem 1.1rem;
    margin: .5rem 0 1rem;
    box-shadow: 3px 3px 0 rgba(58,46,33,.10);
}}
.plate-label {{
    font-size: .68rem; letter-spacing: 3px; text-transform: uppercase;
    color: var(--rust); margin-bottom: .4rem;
}}

/* Source banner: where this answer's context came from */
.badge {{
    display: inline-block;
    font-size: .66rem; letter-spacing: 2.5px; text-transform: uppercase;
    border: 1px solid rgba(140,90,43,.55);
    background: rgba(185,148,87,.18);
    color: var(--ink-soft);
    padding: .2rem .6rem; margin-bottom: .7rem; border-radius: 2px;
}}

/* Buttons stamped in brass */
.stButton > button, .stDownloadButton > button {{
    background: var(--sepia); color: var(--paper) !important;
    border: 1px solid var(--ink); border-radius: 2px;
    font-family: 'Courier Prime', monospace; text-transform: uppercase;
    letter-spacing: 2px; font-size: .75rem;
    box-shadow: 3px 3px 0 rgba(58,46,33,.35);
    transition: all .12s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    background: var(--rust); transform: translate(1px, 1px);
    box-shadow: 2px 2px 0 rgba(58,46,33,.35);
}}

/* Recent-chat entries: flat ledger lines, not stamped buttons */
section[data-testid="stSidebar"] .stButton > button[kind="tertiary"] {{
    background: transparent !important;
    color: #EADFC8 !important;
    border: none;
    border-bottom: 1px dotted rgba(185,148,87,.35);
    border-radius: 0;
    box-shadow: none;
    text-transform: none;
    letter-spacing: .5px;
    text-align: left;
    padding: .4rem .2rem;
    width: 100%;
}}
section[data-testid="stSidebar"] .stButton > button[kind="tertiary"]:hover {{
    background: rgba(185,148,87,.14) !important;
    color: #FFF3DC !important;
    transform: none;
}}

/* Inputs on ledger paper */
.stTextInput input, .stTextArea textarea, [data-testid="stChatInput"] textarea {{
    background: #FBF4E4 !important; color: var(--ink) !important;
    border: 1px solid rgba(140,90,43,.55) !important; border-radius: 2px !important;
    font-family: 'Courier Prime', monospace !important;
}}
[data-testid="stChatInput"] {{ border-top: 2px solid rgba(140,90,43,.35); }}

/* Expanders */
[data-testid="stExpander"] {{
    background: var(--paper-deep);
    border: 1px solid rgba(140,90,43,.4) !important;
    border-radius: 2px !important;
}}

[data-testid="stMetricValue"] {{ font-family: 'Playfair Display', serif; color: var(--brass) !important; }}
[data-testid="stMetricLabel"] {{ letter-spacing: 2px; text-transform: uppercase; font-size: .7rem; }}

hr {{ border-color: rgba(140,90,43,.4); }}
footer, #MainMenu {{ visibility: hidden; }}
.caption {{ font-style: italic; color: var(--ink-soft); font-size: .82rem; }}
</style>
"""


def configure_page() -> None:
    """st.set_page_config — must run before any other Streamlit call."""
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon=PAGE_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def masthead(title: str = "Multi-Agent Desk",
             subtitle: str = "Answers Drawn From Your Own Documents") -> None:
    st.markdown(
        f'<div class="masthead"><h1>{title}</h1>'
        f'<div class="sub">{subtitle}</div>'
        f'<div class="rule">✦ ✦ ✦</div></div>',
        unsafe_allow_html=True,
    )


def plate_header(node: str) -> None:
    title, blurb = STEP_LABELS.get(node, (node, ""))
    st.markdown(
        f'<div class="plate"><div class="plate-label">{title} · {blurb}</div></div>',
        unsafe_allow_html=True,
    )


def badge(text: str) -> None:
    st.markdown(f'<span class="badge">{text}</span>', unsafe_allow_html=True)


def caption(text: str) -> None:
    st.markdown(f'<p class="caption">{text}</p>', unsafe_allow_html=True)


def step_status_label(node: str) -> str:
    title, blurb = STEP_LABELS.get(node, (node, ""))
    return f"{title} — {blurb}"


def render_trace(steps) -> None:
    """steps: list of (node_name, text)."""
    with st.expander(TRACE_LABEL):
        for node, body in steps:
            plate_header(node)
            st.markdown(body or "_(nothing recorded)_")
