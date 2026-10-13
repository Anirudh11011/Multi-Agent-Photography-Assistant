"""Run golden-dataset cases through the pipeline, without the UI, a few at a time.

Usage (from the project folder, with the venv active):
    python evals/run_golden.py                    # the next 10 cases not yet done
    python evals/run_golden.py --limit 5
    python evals/run_golden.py --category triage  # only this category
    python evals/run_golden.py --ids SET-001 QUE-003   # run, or re-run, these cases
    python evals/run_golden.py --status           # what is done so far; no model calls

Each finished case is appended to evals/results.jsonl straight away, one JSON object
per line, so an interrupted run loses nothing and the next run carries on where this
one stopped. A case that is run again is appended again; the last line for an id is
the one that counts (load_results() applies that rule).

The run stops at the first rate-limit error from Groq. A case that fails for any
other reason, or whose web search was unavailable, is not stored, so it comes round
again on the next run.

Nothing is written to conversations.db. If LangSmith tracing is configured, the runs
are traced with the tag "golden-eval".
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

EVALS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EVALS_DIR)
DATASET = os.path.join(EVALS_DIR, "golden_dataset.json")
RESULTS = os.path.join(EVALS_DIR, "results.jsonl")

# The pipeline uses paths relative to the project folder (./chroma_langchain_db).
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, EVALS_DIR)


def load_cases() -> list[dict]:
    with open(DATASET, encoding="utf-8") as f:
        return json.load(f)["cases"]


def load_results() -> dict[str, dict]:
    """Stored results by case id. The last line for an id wins."""
    results = {}
    if os.path.exists(RESULTS):
        with open(RESULTS, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    results[record["id"]] = record
    return results


def attached_context(attachments: list[dict]) -> str:
    """The same block format build_attached_context() produces in the app."""
    return "\n\n".join(f"[attached file: {a['name']}]\n{a['content']}" for a in attachments)


def routing_checks(case: dict, state: dict, P, pipeline) -> dict[str, bool]:
    """The checks that need no judge: plain comparisons against the pipeline state."""
    expected, answer = case["expected"], state["final_response"]
    checks = {"kind": state["kind"] in expected["kind"]}

    if expected["source"]:
        checks["source"] = state["source"] in expected["source"]

    if expected["rewrite_must_include"]:
        rewrite = state["question"].lower()
        checks["rewrite"] = all(t.lower() in rewrite for t in expected["rewrite_must_include"])

    if expected["safety_line"] == "required":
        checks["safety_line"] = answer.lstrip().startswith("**Safety:**")
    elif expected["safety_line"] == "forbidden":
        checks["safety_line"] = "**Safety:**" not in answer

    if expected["behavior"] == "smalltalk_reply":
        checks["fixed_reply"] = answer == P.SMALLTALK_REPLY
    elif expected["behavior"] == "outside_reply":
        checks["fixed_reply"] = answer == P.OUTSIDE_SCOPE_REPLY

    answered = state["source"] in ("attached", "retrieved", "web")
    if expected["behavior"] == "answer" and state["kind"] == "settings" and answered:
        checks["format"] = not pipeline.check_format(answer)

    return checks


def run_case(case: dict, graph, P, pipeline, obs) -> dict:
    """One case through the graph, returned as the record to store."""
    context = attached_context(case["attachments"])
    stages = (["attached"] if context else []) + ["retrieved", "web"]
    state = {"user_input": case["input"], "history": pipeline.format_history(case["history"]),
             "kind": "", "question": case["input"],
             "attached_context": context,
             "context": "", "source": "", "stages": stages, "stage": 0,
             "approved": False, "verdict": "", "attempts": [],
             "analysis_1": "", "final_response": "", "validation": []}
    config = obs.run_config(
        conversation_id=f"golden-{case['id']}", turn_index=0, run_name="golden_case",
        extra_metadata={"case_id": case["id"], "model": pipeline.MODEL_NAME,
                        "prompt_version": P.PROMPT_VERSION},
        extra_tags=["golden-eval"],
    )

    started = time.time()
    final = graph.invoke(state, config=config)
    elapsed = time.time() - started

    return {
        "id": case["id"],
        "category": case["category"],
        "input": case["input"],
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "prompt_version": P.PROMPT_VERSION,
        "model": pipeline.MODEL_NAME,
        "elapsed_seconds": round(elapsed, 1),
        "kind": final["kind"],
        "question": final["question"],
        "source": final["source"],
        "attempts": [list(a) for a in final.get("attempts") or []],
        "context": final.get("context") or "",
        "scene_brief": final.get("analysis_1") or "",
        "answer": final["final_response"],
        "validation": final.get("validation") or [],
        "checks": routing_checks(case, final, P, pipeline),
    }


def web_search_was_down(record: dict) -> bool:
    return any(verdict.startswith("Web search unavailable") for _, verdict in record["attempts"])


def print_status(cases: list[dict], results: dict[str, dict]) -> None:
    total = Counter(c["category"] for c in cases)
    done = Counter(c["category"] for c in cases if c["id"] in results)
    print(f"{sum(done.values())} of {len(cases)} cases stored in {os.path.relpath(RESULTS, ROOT)}\n")
    for category, n in total.items():
        print(f"  {category:15} {done[category]:>2} / {n}")

    failed = [(r["id"], [name for name, ok in r["checks"].items() if not ok])
              for r in results.values()]
    failed = [(cid, names) for cid, names in failed if names]
    if failed:
        print("\nRouting checks that failed:")
        for cid, names in failed:
            print(f"  {cid}: {', '.join(names)}")

    versions = Counter(r["prompt_version"] for r in results.values())
    if len(versions) > 1:
        print("\nResults mix prompt versions: "
              + ", ".join(f"{v} ({n})" for v, n in versions.items())
              + ". Re-run the older ones with --ids before judging.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=10,
                        help="how many cases to run this time (default: 10)")
    parser.add_argument("--category", help="only run cases in this category")
    parser.add_argument("--ids", nargs="+", metavar="ID",
                        help="run exactly these cases, even if already stored")
    parser.add_argument("--sleep", type=float, default=5.0,
                        help="seconds to wait between cases (default: 5)")
    parser.add_argument("--status", action="store_true",
                        help="show progress and exit without calling any model")
    args = parser.parse_args()

    cases = load_cases()
    results = load_results()

    if args.status:
        print_status(cases, results)
        return

    if args.ids:
        known = {c["id"] for c in cases}
        unknown = [i for i in args.ids if i not in known]
        if unknown:
            sys.exit(f"Not in the dataset: {', '.join(unknown)}")
        todo = [c for c in cases if c["id"] in args.ids]
    else:
        todo = [c for c in cases if c["id"] not in results
                and (not args.category or c["category"] == args.category)]
        todo = todo[:args.limit]

    if not todo:
        print("Nothing to run.")
        print_status(cases, results)
        return

    # Imported here so --status stays instant: these load the embedding model.
    from dotenv import load_dotenv
    load_dotenv()
    if not os.getenv("GROQ_API_KEY"):
        sys.exit("No GROQ_API_KEY found. Add it to .env first.")

    from groq import RateLimitError
    from langchain_chroma import Chroma
    from langchain_huggingface import HuggingFaceEmbeddings

    from app.loaders import COLLECTION, PERSIST_DIR
    from app import observability as obs
    from app import prompts as P
    import pipeline_copy as pipeline

    obs.configure_langsmith()
    graph = pipeline.build_graph(Chroma(
        collection_name=COLLECTION,
        embedding_function=HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"),
        persist_directory=PERSIST_DIR,
    ))

    print(f"Running {len(todo)} case(s), prompt version {P.PROMPT_VERSION}\n")
    stored = 0
    for number, case in enumerate(todo, 1):
        label = f"[{number}/{len(todo)}] {case['id']}"
        try:
            record = run_case(case, graph, P, pipeline, obs)
        except RateLimitError as exc:
            print(f"{label}  rate limit reached, stopping here.\n  {exc}")
            break
        except Exception as exc:
            print(f"{label}  ERROR, not stored: {type(exc).__name__}: {exc}")
            continue

        if web_search_was_down(record):
            print(f"{label}  web search was unavailable, not stored. Run it again later.")
            continue

        with open(RESULTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        results[record["id"]] = record
        stored += 1

        failed = [name for name, ok in record["checks"].items() if not ok]
        print(f"{label}  kind={record['kind']} source={record['source']} "
              f"{record['elapsed_seconds']}s  "
              + ("checks ok" if not failed else "CHECKS FAILED: " + ", ".join(failed)))

        if number < len(todo):
            time.sleep(args.sleep)

    print(f"\nStored {stored} new result(s).")
    print_status(cases, results)


if __name__ == "__main__":
    main()
