# AI Note

**Did I use AI?** Yes, Claude Code, as an assistant on a project I designed and drove.

## The split

**Mine:** the idea and the framing, that the real gap for a hobbyist is *scene reading* plus
*this specific body's controls*, and that neither manuals nor forums cover both. The
architecture followed from that: two agents in sequence (scene, then settings) rather than
one, because the second needs the first's output as input. I chose the escalation ladder,
decided where the guardrails sit, wrote the agent prompts and the retrieval and ingestion
code, and set the constants. I also decided what to remove. The model, temperature and `k`
sliders went, because a first-time photographer has no basis to tune them and they cluttered
the screen.

**AI's:** the Streamlit UI and CSS, the LangGraph wiring for the routing I'd specified, the
DuckDuckGo fallback, and documentation drafts.

## Where it helped most

Two ways.

**Laying out options with trade-offs.** When I was deciding how attached files should behave,
I asked for the choices rather than an answer. It gave me: ingest them permanently into
ChromaDB (searchable later, but pollutes the archive with one-off files and needs a delete
path) versus keep them session-scoped in memory (clean, disposable, but re-parsed each
session). I picked session-scoped, because someone testing a rented camera's manual shouldn't
permanently alter their archive. Same pattern for embeddings, chunk size, and the web
fallback. Having the pros and cons written out made those decisions faster; the decisions
were still mine.

**UI.** I described the interface I wanted, a clean page with two sidebar panels and a source
badge and trace under every answer, and it produced the CSS and layout, isolated in
`vintage_theme.py` so the application file emits no HTML. That's real time saved on work I'd
have done slowly.

## What I verified myself

**The relevance floor.** AI suggested a threshold on Chroma's similarity score with a
confident-looking default. I measured it against the real corpus instead:

| Query | Top score |
|---|---|
| "Sony A7 IV landscape settings" | 0.433 |
| "Nikon Z9 autofocus menu" | −0.096 |
| "how do I bake sourdough bread" | −0.264 |

Scores go **negative**, outside the `[0, 1]` range the default assumed. I set the floor at
0.25 in the observed gap, and flagged in the README that it's corpus-specific.

**One suggestion I rejected.** The first version let attached files skip the supervisor: if
the user attached it, trust it. That was wrong, since someone can attach a Fuji X-T5 manual
and ask about a Nikon Z9. I tested exactly that; ungraded, it answered confidently from the
wrong manual. Every rung is graded now.

**Testing was mine.** Six end-to-end runs, one per path. The one that mattered: *"exact
battery life in shots for the A7 IV?"* cleared the numeric floor at 0.41, but the supervisor
said NO. A threshold alone would have passed it and the model would have invented a figure,
which is precisely the failure a beginner can't catch. That case is why there are two gates.
