# Technical Challenges

A record of the problems hit while building the pipeline, the evidence used to
diagnose each one, and why each decision was made — including the two that were
wrong and had to be walked back.

The recurring method is worth stating up front: **every diagnosis in this document
came from querying `conversations.db`, not from reading the code and guessing.**
The transcript store was built for training exports, but it turned out to be the
project's measurement instrument. `agent_steps` records the output of every node on
every turn, so the cost of each stage is a `length(content)` away.

---

## 1. Answers took 80 seconds

### The problem

A representative question — *"Give me camera settings to capture an F1 race car on a
Sony α6700 at the Red Bull Ring"* — took **80.3 seconds**. The answer itself was
good; the wait made the app unusable.

The instinct was to blame the LLM provider. That was wrong.

### The evidence

Querying the step sizes for that turn:

```sql
select node, length(content) from agent_steps where message_id = 5;
```

| Node | Output |
|---|---|
| gather_context (archive) | 148 chars |
| supervisor | rejected |
| gather_context (web) | 2,014 chars |
| supervisor | approved |
| **agent_1** | **9,346 chars** (~2,400 tokens) |
| **agent_2** | **9,154 chars** (~2,350 tokens) |
| response_generator | 1,685 chars |

**~20,200 characters were generated; 1,685 reached the user — a yield of 8%.**

The two analyst agents were writing multi-thousand-word briefing documents, which
`response_generator` then compressed into an eight-row table. Since `gpt-oss-120b` is
a reasoning model, hidden reasoning tokens sat on top of every one of those figures.

The bottleneck was never inference speed. It was five sequential calls, two of which
produced output that was thrown away.

### Root causes identified

1. **No output bound on `agent_1` or `agent_2`.** Neither prompt said how long to be,
   so the model defaulted to exhaustive.
2. **`agent_2` and `response_generator` did the same job twice.** `agent_2` produced a
   settings table; `response_generator` re-read ~4,700 tokens and rewrote it shorter.
   An entire round trip spent on formatting.
3. **The web search waited behind an LLM call it did not depend on.** `web_search` is
   pure I/O but could not start until the supervisor finished rejecting the archive.
4. **The supervisor used the 120B model to emit one line**, with no token bound.
5. **Nothing streamed.** `stream_mode="updates"` only yields when a node *finishes*, so
   the first visible word appeared at second 80.

### Decision

Fix 1 and 2 first, since the measurement showed that is where the time was. Defer 3
and 5. That ordering came directly from the data — items 3 and 4 are worth seconds,
items 1 and 2 were worth tens of seconds.

---

## 2. The supervisor was a routing gate running as a creative generation

### The problem

One `ChatGroq` instance served all five nodes:

```python
llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0.7)
```

So a node whose entire job is emitting `YES - the passages cover it` ran on a 120B
reasoning model at temperature 0.7. And the routing decision reads exactly one word:

```python
state["approved"] = verdict.upper().lstrip("*# ").startswith("YES")
```

The `148 chars` in the table above is the *recorded step body*, which includes a
`**Source:**` header and a `[relevance 0.31]` tag. The real retrieved text was roughly
**100 characters** — a single chunk that scraped past the relevance floor. A full
reasoning-model round trip was spent deciding whether 100 characters could answer a
question about a specific camera body.

### The subtler issue

`temperature=0.7` is a *generation* temperature applied to a *classification*. The same
question against the same passages could grade differently between runs, making the
escalation ladder nondeterministic — sometimes answering from the archive, sometimes
falling through to web. That is harder to debug than slowness, and it undermines the
evaluation corpus the transcript store exists to build.

### Decision

Split one LLM into two roles rather than sharing one:

| Role | Model | Temperature | Rationale |
|---|---|---|---|
| `grader_llm` | `openai/gpt-oss-20b` | 0 | One-line classification; must be deterministic |
| `llm` | `openai/gpt-oss-120b` | 0.7 | Analysis and prose, where quality shows |

The one-line reason was kept rather than reduced to a bare YES/NO, because
`render_trace` displays it and that transparency is a feature of the UI.

---

## 3. Merging `response_generator` into `agent_2` also fixed fabricated citations

### The problem

The pipeline was `supervisor → agent_1 → agent_2 → response_generator → END`. Removing
the third call was a pure latency change — or so it appeared.

Then the F1 answer was audited and found to cite:

```
https://www.sony.com/electronics/support/articles/00012345
```

That URL does not exist. It has the shape of a placeholder.

### The evidence

`response_generator` received `analysis_1`, `analysis_2`, and a source note. It did
**not** receive `state["context"]`. Yet the note for the web path instructed it to
*"cite the source URLs you relied on."*

**The node was asked to cite URLs it had never been shown.** The fabrication was not a
model failure; it was structurally guaranteed by the prompt.

### Decision

Merge the final write into `agent_2`, which *does* receive `state["context"]` — and on
the web path that context contains the real `href` values returned by `ddgs`. The
source note was rewritten to permit only URLs appearing verbatim in the reference
material, and to name the source in words when none are present.

Removing a node for speed happened to relocate the formatting step somewhere that could
actually see its sources. Worth recording as a general lesson: **a prompt that asks for
something absent from its own inputs will get an invention, every time.**

---

## 4. Rejected: Prompt Guard 2 as the supervisor

`meta-llama/llama-prompt-guard-2-86m` was considered as the grader model — small,
fast, and available on Groq.

It was rejected. Prompt Guard 2 is a DeBERTa-style **binary classifier**, ~86M
parameters, trained on one question: *is this text a prompt injection or jailbreak?*
It emits a label and a score, not free text, and has no instruction following.

Three concrete failures:

| Requirement | Prompt Guard 2 |
|---|---|
| Answer *"is this context sufficient?"* | Answers *"is this an attack?"* — a thin, irrelevant, harmless passage classifies **benign**, so the gate would approve everything and the ladder would stop escalating |
| Hold the context | **512-token window**; the web block alone is ~2,000 chars and `MAX_CONTEXT_CHARS` for attachments is 12,000 — roughly 40× over |
| Produce a displayable reason | Returns a float |

`openai/gpt-oss-20b` was chosen instead: a genuinely small *instruct* model that can
follow the existing one-line contract.

### Where Prompt Guard does belong

The idea was relocated rather than discarded. Two untrusted text sources currently flow
straight into prompts: uploaded PDFs via `build_attached_context`, and DuckDuckGo result
bodies via `web_search`. Both land in `state["context"]`, which every downstream agent
reads. Screening those chunks for injection is precisely what Prompt Guard is for, it is
cheap at 86M, it runs off the critical path, and the 512-token limit is a non-issue
because the text is already chunked.

Not yet implemented. Logged as a hardening task.

---

## 5. Regression: `max_tokens` on a reasoning model silently rejected everything

### The problem

After the supervisor swap, **almost every question was refused.**

### The evidence

```sql
select message_id, node, substr(content,1,80) from agent_steps where message_id in (7,8,9);
```

Turn 7 returned:

> **Verdict:** The grader returned nothing; trying the next source.

The grader had been configured with `max_tokens=512`. On Groq, that cap counts
`gpt-oss-20b`'s **reasoning tokens**, not just visible output. On a long passage block
the reasoning consumed the entire budget and the verdict line came back empty.

An empty string fails `startswith("YES")`, so a truncation was indistinguishable from a
considered rejection.

### Decision

Remove `max_tokens` from the grader entirely. The one-line instruction in the prompt is
sufficient bound, and the cap was only ever a backstop — one that broke the thing it was
protecting. The defensive empty-verdict branch was kept, so the failure is now named in
the trace instead of masquerading as a verdict:

```python
if not verdict:
    state["verdict"] = "The grader returned nothing; trying the next source."
    state["approved"] = False
```

**Lesson: on a reasoning model, a token cap is not an output-length control.** It is a
total-compute control, and the visible answer is what gets cut when it binds.

---

## 6. Regression: a prompt tuned for one model read differently by another

### The problem

Truncation explained turn 7, but turns 8 and 9 showed *real* reasoning behind their
refusals:

> **Verdict:** NO — The passages provide only general motorsport photography tips
> (continuous AF, burst mode, panning speeds) but none specific to the Sony α6700.

The supervisor prompt was never edited. It had always said:

> *Partial but genuinely on-topic material counts as sufficient; material that is
> merely on a related subject does not.*

That wording was written against the 120B at temperature 0.7. The 20B at temperature 0
applies it **literally**, and rejects generic photography guidance for not naming the
exact body — which is most of what a web search returns.

### Decision

Loosen the grading criterion to match the pipeline's actual purpose: adapting general
guidance to a specific camera is exactly what `agent_1` and `agent_2` are for, so the
retrieved passages need not do it themselves.

> *General guidance that bears on the question counts as sufficient — expert agents
> downstream will adapt it to the specific camera and scene, so the passages need not
> name either. Reject only material that is off-topic, or too thin to inform an answer
> at all.*

### The tradeoff, stated explicitly

Turns 8 and 9 were arguably **correct** rejections in isolation — the passages genuinely
did not cover the α6700. A looser gate means thin sources now reach the agents instead
of triggering the refusal path. The project has chosen *synthesize from general guidance*
over *refuse unless the exact body is documented*. That is a product decision, not a bug
fix, and it should be revisited if hallucinated specifics start appearing.

**Lesson: prompts are calibrated against a specific model and temperature.** Swapping
the model is not a drop-in change, even when the prompt text is untouched.

---

## 7. Regression: over-constraining `agent_1` produced a useless brief

### The problem

To cut `agent_1`'s 9,346-character output, it was given a rigid contract: six labelled
lines, ≤120 words, and — the fatal clause —

> *Where the reference material does not cover a line, write 'unknown' for it instead
> of guessing.*

Turn 10's `agent_1` output was **214 characters**:

```
Light: unknown.
Motion: unknown.
Distance: unknown.
Background: unknown.
Risk: unknown.
Intent: Freeze the car; a high shutter speed is needed.
```

Latency dropped, and the answer became worthless. `agent_2` had nothing to work from.

### Why the rule was wrong

It conflated two different kinds of knowledge. Web snippets about panning technique do
not state the light level at the Red Bull Ring or the shooting distance from a
grandstand — and they never will. **Scene analysis should come from the model's own
knowledge of scenes like this; the reference documents are for camera-specific facts.**
The instruction told the agent to suppress precisely the knowledge it was there to
supply.

An intermediate fix — raising the cap from 120 to 250 words — did not help, because the
word count was never the binding constraint. The `unknown` rule was.

### Decision

Revert to the original prose prompt, with a soft brevity instruction appended rather
than a rigid schema:

> *Keep it to a reasonable length — a brief the next agent can read in a few seconds,
> not an exhaustive document. Cover what actually bears on the settings, and leave out
> venue history, gear lists, safety advice and scenarios the user did not ask about.
> Where the reference documents are silent, draw on what you know about scenes like
> this rather than reporting the detail as unknown.*

**Lesson: a schema bounds shape, not usefulness.** The exclusion list ("leave out venue
history, gear lists, safety advice") did the real work, because it named the specific
padding observed in the 9,346-character sample. A word count alone had cut the wrong
material.

---

## 8. Results

Measured from `conversations.db`, all on the web-fallback path (the slowest route):

| Turn | Configuration | Elapsed | `agent_1` | Delivered | Yield |
|---|---|---|---|---|---|
| 1 | Original, 5 LLM calls | 81.5 s | — | 1,594 | — |
| 4 | Original | 54.6 s | — | 1,784 | — |
| 5 | Original | **80.3 s** | 9,346 | 1,685 | **8%** |
| 7–9 | Regression: strict grader | 4.6–7.1 s | — | *refused* | — |
| 10 | Regression: `unknown` cascade | 12.1 s | 214 | 1,580 | — |
| 11 | Current | **14.9 s** | 4,063 | 1,228 | 22% |
| 12 | Current | **8.6 s** | 4,411 | 1,498 | 24% |

**~80 s → 9–15 s**, roughly a 5–9× improvement, with the answer format unchanged.
LLM calls per answer went from 5 to 3. `agent_1`'s output roughly halved rather than
collapsing, which is the intended outcome — the earlier 214-character version was faster
still and worth nothing.

Turns 7–10 are left in the table deliberately. Both regressions *improved the latency
metric* while destroying the answer, which is the argument for reading the transcript
rather than the stopwatch.

---

## 9. Accuracy audit

A separate review of the original F1 answer found errors a photographer would have acted
on. These are content-quality issues, distinct from the latency work, and most are still
open.

| Finding | Status |
|---|---|
| **Headline settings ~2.7 stops overexposed.** f/2.8, 1/1000 s, ISO 200 in bright sun — sunny-16 puts correct exposure at roughly **1/6400 s**. The lead recommendation would blow out the shot. | Partly addressed |
| **Panning speeds were not panning speeds.** 1/800–1/1000 s at 300 km/h yields almost no background blur; real motorsport panning is 1/125–1/400 s. | Open |
| **"Kemmel straight" is at Spa-Francorchamps**, not the Red Bull Ring. | Open |
| **The α6700 has no CFexpress Type A slot** — it is a single SD UHS-II. "UHS-III" cards do not ship. | Open |
| **Menu paths were for the older a6x00 body**, so the custom-preset walkthrough could not be followed on an α6700. | Open |
| **Recommended Eye-AF for a car.** The α6700's actual feature is AI subject recognition with a **Car/Train** mode — the single most useful setting for this shoot, and it was missing. | Open |
| **Fabricated source URLs.** | Fixed — see §3 |
| **Invented a lens lineup** the user never said they owned. | Partly addressed |

Two mitigations were added to `agent_2`'s prompt: cover only the conditions the user
asked about (which suppresses unrequested night-race and alternate-lens branches), and
check the table's aperture/shutter/ISO expose correctly together at the light level in
the scene analysis.

The exposure error is worth noting as an *architectural* symptom, not just a bad number.
No stage in a linear relay ever checks the previous stage's arithmetic, so a wrong
value introduced at `agent_2` passes through to the reader unchallenged. A verification
step, or a deterministic exposure check in Python, would catch this class of error
properly. The prompt-level instruction is a mitigation, not a fix.

---

## 10. Deferred

Identified and deliberately not implemented, in rough priority order:

1. **Run the web search concurrently with the archive grade.** `web_search` is pure I/O
   and does not depend on the supervisor's verdict. Firing it in a thread at turn start
   would take it off the critical path — and the transcript shows the web path is the
   common case, not the exception.
2. **Stream the final node's tokens** into `st.write_stream`. This does not reduce wall
   clock at all, but it moves time-to-first-token from the full duration to a few
   seconds, which is what "slow" actually means to a user.
3. **A substance threshold before the grader.** The empty-context short circuit already
   exists, but only fires at *exactly zero* — one thin chunk still costs a full LLM call
   to reject. Extending it to a minimum character count removes that call on the common
   miss.
4. **Prompt Guard 2 screening** of attached files and web results — see §4.
5. **A deterministic exposure check** in Python rather than a prompt instruction — see §9.

---

## Summary of lessons

- **Measure before optimising.** The provider was the intuitive suspect and was not the
  problem. The transcript store answered the question in one SQL query.
- **Count what you throw away, not just what you produce.** An 8% token yield was the
  whole diagnosis.
- **A prompt asking for something absent from its inputs gets an invention.**
- **On reasoning models, `max_tokens` caps total compute, not visible output** — and the
  visible answer is what gets cut.
- **Prompts are calibrated to a model and a temperature.** A model swap is a behaviour
  change even when the prompt text is identical.
- **Bounding output by schema bounds shape, not usefulness.** Naming the specific
  padding to remove worked; a word limit did not.
- **A latency metric that improves while the answer degrades is not an improvement.**
  Both regressions here looked like wins on the stopwatch.
