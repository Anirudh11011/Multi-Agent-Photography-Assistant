"""Output checks run by the pipeline's validate node.

All three are deterministic: regex and set membership, no model call, so the
validate node adds no measurable latency and cannot itself hallucinate.
"""

import re

REQUIRED_SECTIONS = ("**Start here**", "**Then adjust**", "**Why these settings**")
REQUIRED_ROWS = ("Mode", "Aperture", "Shutter", "ISO", "White balance",
                 "Focus", "Metering", "Drive")

URL_RE = re.compile(r'https?://[^\s\)\]>"\',]+')

# Each entry redacts group 1 where the pattern isolates the value, else the whole
# match. Known key shapes only — this is a safety net, not a guarantee.
SECRET_PATTERNS = (
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'), "AWS access key id"),
    (re.compile(r'\bgsk_[A-Za-z0-9]{20,}\b'), "Groq API key"),
    (re.compile(r'\bsk-[A-Za-z0-9_\-]{20,}\b'), "OpenAI-style secret key"),
    (re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b'), "GitHub token"),
    (re.compile(r'\bxox[baprs]-[A-Za-z0-9-]{10,}\b'), "Slack token"),
    (re.compile(r'\bey[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b'), "JWT"),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'), "private key block"),
    (re.compile(r'(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*'
                r'["\']?([A-Za-z0-9_\-/+]{16,})'), "credential assignment"),
)

# A key with no recognisable prefix can only be judged on shape: a long opaque
# run mixing case and digits. Measured against every answer and context block in
# conversations.db, this matches nothing legitimate — prose and setting values
# never look like this. URLs are exempt; their path segments often do.
OPAQUE_TOKEN_RE = re.compile(
    r'(?<![/\w])(?=[A-Za-z0-9_\-]{24,}(?![A-Za-z0-9_\-]))'
    r'(?=[A-Za-z0-9_\-]*[a-z])(?=[A-Za-z0-9_\-]*[A-Z])'
    r'(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{24,}'
)


def _normalise_url(url: str) -> str:
    """Strip what varies between a link in prose and the same link in a source."""
    url = url.rstrip('.,;:)]}>"\'').rstrip('/').lower()
    return re.sub(r'^https?://(www\.)?', '', url)


def check_format(answer: str) -> list[str]:
    """The four-section contract. 'On your camera' is optional by design."""
    issues = []
    missing = [s.strip("*") for s in REQUIRED_SECTIONS if s not in answer]
    if missing:
        issues.append("missing section(s): " + ", ".join(missing))
    absent = [r for r in REQUIRED_ROWS
              if not re.search(rf'^\|\s*{re.escape(r)}\s*\|', answer, re.M | re.I)]
    if absent:
        issues.append("missing table row(s): " + ", ".join(absent))
    return issues


def strip_invented_urls(answer: str, context: str) -> tuple[str, list[str]]:
    """Remove links that never appeared in the retrieved material.

    The model is asked to cite only what it was given; anything else was
    invented, so it is cut rather than shown to someone who might click it.
    """
    allowed = {_normalise_url(u) for u in URL_RE.findall(context)}
    invented = [u for u in URL_RE.findall(answer)
                if _normalise_url(u) not in allowed]
    for url in invented:
        answer = answer.replace(url, "[source link removed — not in the retrieved material]")
    return answer, invented


def redact_secrets(answer: str) -> tuple[str, list[str]]:
    """Mask anything shaped like a credential that reached the answer."""
    found: list[str] = []

    def _mask(match: re.Match, label: str) -> str:
        found.append(label)
        if match.groups() and match.group(1):
            return match.group(0).replace(match.group(1), "[redacted]")
        return "[redacted]"

    for pattern, label in SECRET_PATTERNS:
        answer = pattern.sub(lambda m, _l=label: _mask(m, _l), answer)

    # Anything left that merely looks like a key. Match offsets are positions in
    # the string handed to sub(), so the URL spans stay valid throughout.
    url_spans = [m.span() for m in URL_RE.finditer(answer)]

    def _mask_opaque(match: re.Match) -> str:
        if any(start <= match.start() < end for start, end in url_spans):
            return match.group(0)
        found.append("opaque high-entropy token")
        return "[redacted]"

    answer = OPAQUE_TOKEN_RE.sub(_mask_opaque, answer)
    return answer, sorted(set(found))
