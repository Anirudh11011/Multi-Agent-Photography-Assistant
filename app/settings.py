"""Fixed settings (previously sidebar controls)."""

MODEL_NAME = "openai/gpt-oss-120b"
# The supervisor only emits one line of YES/NO, so it runs on a smaller model at
# temperature 0 — a routing gate should not be a sampled generation.
SUPERVISOR_MODEL = "openai/gpt-oss-20b"
# Low: the answer is numbers someone acts on, not creative writing. Prompts are
# calibrated to model + temperature — re-check answers if you change either.
TEMPERATURE = 0.3

# ── Image analysis ───────────────────────────────────────────
# PLACEHOLDER: set this to a Groq model that accepts image input before using the
# image feature. Until it is replaced, an image turn fails with a clear message
# instead of reaching Groq with a bad model name.
VISION_MODEL = "qwen/qwen3.8-27b"
VISION_TEMPERATURE = 0.3
IMAGE_TYPES = ["jpg", "jpeg", "png", "webp"]
# Photos are downscaled to this long edge (px) and re-encoded as JPEG before they
# are sent: enough detail to judge focus, noise and exposure, and well inside the
# request-size limits of hosted vision APIs.
IMAGE_MAX_EDGE = 1568
IMAGE_JPEG_QUALITY = 88

TOP_K = 4
RELEVANCE_FLOOR = 0.25      # below this, retrieval is treated as a miss
MAX_CONTEXT_CHARS = 12000   # budget for attached-file context
MAX_ATTACHED_CHUNKS = 12
RECENT_CHAT_LIMIT = 12
WEB_RESULTS = 5             # DuckDuckGo hits pulled on the final fallback
# Short-term memory: the most recent whole turns that fit this token budget are
# shown to triage and the answer writer (see sessions.format_history).
HISTORY_MAX_TOKENS = 1500
# Each earlier answer is clipped to this first, so one long answer can't use up
# the whole budget and push every other turn out.
HISTORY_ANSWER_CHARS = 2000
REFUSAL = ("I couldn't find a reliable source for this in your attached manual, the "
           "built-in guides, or a web search. Rather than guess at settings you'd act "
           "on, I'll say so. Try attaching your camera's manual.")
