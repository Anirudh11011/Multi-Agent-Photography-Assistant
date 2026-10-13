"""Fixed settings (previously sidebar controls)."""

MODEL_NAME = "openai/gpt-oss-120b"
# The supervisor only emits one line of YES/NO, so it runs on a smaller model at
# temperature 0 — a routing gate should not be a sampled generation.
SUPERVISOR_MODEL = "openai/gpt-oss-20b"
# Low: the answer is numbers someone acts on, not creative writing. Prompts are
# calibrated to model + temperature — re-check answers if you change either.
TEMPERATURE = 0.3
TOP_K = 4
RELEVANCE_FLOOR = 0.25      # below this, retrieval is treated as a miss
MAX_CONTEXT_CHARS = 12000   # budget for attached-file context
MAX_ATTACHED_CHUNKS = 12
RECENT_CHAT_LIMIT = 12
WEB_RESULTS = 5             # DuckDuckGo hits pulled on the final fallback
HISTORY_TURNS = 3           # earlier turns shown to intake and the answer writer
HISTORY_ANSWER_CHARS = 700  # each earlier answer is trimmed to this
REFUSAL = ("I couldn't find a reliable source for this in your attached manual, the "
           "built-in guides, or a web search. Rather than guess at settings you'd act "
           "on, I'll say so. Try attaching your camera's manual.")
