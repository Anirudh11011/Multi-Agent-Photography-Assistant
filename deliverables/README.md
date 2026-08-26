# ShutterAide

**Track B: Bring Your Own Domain.** Live app: _<paste Streamlit link>_ · Code: `streamlit_app.py`

## The problem

A hobbyist in front of a scene has two questions at once. What does this light call for in
aperture, shutter and ISO, and where does this camera keep those controls? The second
question resets with every borrowed or rented body, because an A7 IV, an X-T5 and a Z9 bury
the same control behind three different menus. A manual explains the camera but never the
scene; a forum post explains the scene and assumes you own the camera.

## What I built

A chat box that takes the question as a person would ask it, such as *"what settings for a
mountain landscape on a Canon R5?"*, and answers both halves. Hence two agents rather than
one: the first reads the **scene**, working out what the light, motion and depth demand; the
second turns that into **settings for that body**, grounded in its manual. Built for a
first-time photographer on a camera they don't know yet.

## How it stays honest

Settings are advice someone acts on, and a beginner can't tell a good answer from a
confident guess. So context is earned. The app climbs a ladder of sources (attached manual,
then archive, then web) with a supervisor grading each rung before any answer is written and
falling through when one fails. If nothing holds up it says so rather than inventing an
f-stop, and the source that won is named with a trace behind it.

## Data

A small set of manuals and settings guides in `documents/`, chunked into ChromaDB by
`ingest_documents.py`. Small on purpose: it deploys to Streamlit Cloud from GitHub, where a
full library would clutter the repo and overrun the free tier. The ladder covers the gap.
Groq `gpt-oss-120b`, embeddings `all-MiniLM-L6-v2`.

## Assumptions and limits

Most questions therefore resolve by attachment or web rather than locally. Stills only, no
memory between questions, and a relevance floor of 0.25 tuned to this corpus. Grading costs
about five seconds, traded for not being confidently wrong.

## With more resources

These are hosting constraints rather than design ones, and they lift together: a full
multi-brand library with a re-tuned floor, chat history that survives restarts, and a saved
camera body.
