"""Judge the stored golden-eval answers with an LLM, a few at a time, and log the scores to LangSmith.

Usage (from the project folder, with the venv active):
    python evals/judge_golden.py                    # the next 10 results not yet judged
    python evals/judge_golden.py --limit 5
    python evals/judge_golden.py --category triage  # only this category
    python evals/judge_golden.py --ids SET-001 QUE-003   # judge, or re-judge, these cases
    python evals/judge_golden.py --status           # what is judged so far; no model calls

The pipeline is not run again: this reads evals/results.jsonl (written by
run_golden.py) and judges only the results whose routing checks all passed. Each
answer is checked against its case's criteria and must_not lists and the dataset's
global_criteria. Cases whose expected reply is a fixed string (smalltalk_reply,
outside_reply) are already decided by the routing check, so they are logged as
passing without a judge call.

Each judged case is appended to evals/judgments.jsonl straight away; the last line
for an id is the one that counts. A case is judged again when run_golden.py has
re-run it since (its result is newer than its judgment) or when it is named in --ids.

In LangSmith, the golden cases are uploaded once to the dataset "shutteraide-golden"
(cases added to golden_dataset.json later are uploaded when first needed; edits to
existing cases are not). Each prompt version gets one experiment on that dataset,
"golden-judge-<prompt version>", and every batch adds its cases to it. The scores are
feedback on each row: criteria, must_not, rules (share passed) and pass (0 or 1). A
re-judged case updates its row instead of adding a second one. The judge's own calls
are traced in the usual project with the tag "golden-judge", linked from the feedback.

When Groq's per-minute token limit is hit, the run waits as long as Groq asks (up to
MAX_WAIT seconds) and tries the case again; a longer wait means a daily limit, and the
run stops there. A case the judge or LangSmith fails on for any other reason is not
stored, so it comes round again on the next run.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from run_golden import DATASET, EVALS_DIR, ROOT, load_cases, load_results

JUDGMENTS = os.path.join(EVALS_DIR, "judgments.jsonl")
DATASET_NAME = "shutteraide-golden"
JUDGE_MODEL = "qwen/qwen3.8-27b"  # a different family from the pipeline's gpt-oss-120b
FIXED_REPLIES = ("smalltalk_reply", "outside_reply")
MAX_WAIT = 90  # seconds; Groq asking for a longer wait means a daily limit

JUDGE_PROMPT = """You grade one answer from ShutterAide, a photography assistant, against a fixed test case.

You are given the user's message, the earlier conversation, the reference material the assistant was given, the assistant's answer, a reference answer, and a numbered list of items to check. There are three kinds of item:
- C items are criteria. passed = true when the answer meets it.
- M items describe something the answer must not do. passed = true when the answer does NOT do it.
- R items are general rules. passed = true when the answer follows the rule, or when the rule does not apply to this answer (for example, a rule about exposure when the answer gives no settings).

Grade each item on its own, strictly but literally: never fail an item for something it does not ask about. "The reference material shown to the judge" means the reference material below. Where the reference answer gives a range, any value inside it is correct.

Return one result for every item, under its id, with a one-sentence reason that points to the part of the answer that decided it."""


def load_judgments() -> dict[str, dict]:
    """Stored judgments by case id. The last line for an id wins."""
    judgments = {}
    if os.path.exists(JUDGMENTS):
        with open(JUDGMENTS, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    judgments[record["id"]] = record
    return judgments


def load_global_criteria() -> dict[str, list[str]]:
    with open(DATASET, encoding="utf-8") as f:
        return json.load(f)["meta"]["global_criteria"]


def judgeable(cases: list[dict], results: dict[str, dict]) -> list[dict]:
    """Stored results whose routing checks all passed, in dataset order."""
    return [results[c["id"]] for c in cases
            if c["id"] in results and all(results[c["id"]]["checks"].values())]


def is_current(record: dict, judgments: dict[str, dict]) -> bool:
    """True when the case has a judgment of its latest result."""
    judgment = judgments.get(record["id"])
    return judgment is not None and judgment["result_ran_at"] == record["ran_at"]


def checklist(case: dict, record: dict, global_criteria: dict) -> list[tuple[str, str]]:
    """The numbered items the judge answers: C = criteria, M = must_not, R = global rules."""
    rules = list(global_criteria["all_answers"])
    if record["kind"] == "settings":
        rules += global_criteria["settings_answers"]
    elif record["kind"] == "question":
        rules += global_criteria["question_answers"]
    return ([(f"C{i}", s) for i, s in enumerate(case["criteria"], 1)]
            + [(f"M{i}", s) for i, s in enumerate(case["must_not"], 1)]
            + [(f"R{i}", s) for i, s in enumerate(rules, 1)])


def judge_message(case: dict, record: dict, items: list[tuple[str, str]]) -> str:
    history = "\n\n".join(f"User: {turn['question']}\nAssistant: {turn['answer']}"
                          for turn in case["history"]) or "(none)"
    return "\n\n".join([
        f"## User message\n{record['input']}",
        f"## Earlier conversation\n{history}",
        f"## Reference material the assistant was given\n{record['context'] or '(none)'}",
        f"## Assistant's answer\n{record['answer']}",
        f"## Reference answer\n{case['reference']}",
        "## Items\n" + "\n".join(f"{item}. {statement}" for item, statement in items),
    ])


def judge(case: dict, record: dict, items: list[tuple[str, str]], llm, config: dict) -> list[dict]:
    """One judge call; a pass/fail and reason for every item."""
    verdict = llm.invoke([("system", JUDGE_PROMPT),
                          ("human", judge_message(case, record, items))], config=config)
    by_item = {r.item.strip().upper(): r for r in verdict.results}
    missing = [item for item, _ in items if item not in by_item]
    if missing:
        raise ValueError(f"judge gave no result for {', '.join(missing)}")
    return [{"item": item, "statement": statement,
             "passed": by_item[item].passed, "reason": by_item[item].reason}
            for item, statement in items]


def retry_after(exc) -> float | None:
    """Seconds Groq asks us to wait before the next call, or None when it does not say."""
    try:
        return float(exc.response.headers["retry-after"])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def fixed_reply_checks(case: dict) -> list[dict]:
    """A fixed reply that passed the string-equality check meets its criteria by definition."""
    reason = "The answer equals the fixed reply string (routing check)."
    return ([{"item": f"C{i}", "statement": s, "passed": True, "reason": reason}
             for i, s in enumerate(case["criteria"], 1)]
            + [{"item": f"M{i}", "statement": s, "passed": True, "reason": reason}
               for i, s in enumerate(case["must_not"], 1)])


def scores(checks: list[dict]) -> dict[str, tuple[float, str]]:
    """Feedback key -> (score, comment). A key with no items is left out."""
    feedback = {}
    for key, prefix in (("criteria", "C"), ("must_not", "M"), ("rules", "R")):
        group = [c for c in checks if c["item"].startswith(prefix)]
        if not group:
            continue
        failed = [c for c in group if not c["passed"]]
        score = (0.0 if failed else 1.0) if key == "must_not" else round(1 - len(failed) / len(group), 2)
        comment = ("\n".join(f"{c['item']} {c['statement']} -> {c['reason']}" for c in failed)
                   or f"all {len(group)} passed")
        feedback[key] = (score, comment)
    failed = [c["item"] for c in checks if not c["passed"]]
    feedback["pass"] = (0.0 if failed else 1.0,
                        "failed: " + ", ".join(failed) if failed else "every item passed")
    return feedback


def ensure_examples(client, cases: list[dict]):
    """The LangSmith dataset and its examples by case id, uploading any case not there yet."""
    if client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
    else:
        dataset = client.create_dataset(
            DATASET_NAME, description="ShutterAide golden dataset (evals/golden_dataset.json).")

    def by_case_id():
        return {e.metadata["case_id"]: e for e in client.list_examples(dataset_id=dataset.id)
                if e.metadata and "case_id" in e.metadata}

    examples = by_case_id()
    new = [c for c in cases if c["id"] not in examples]
    if new:
        client.create_examples(dataset_id=dataset.id, examples=[{
            "inputs": {"case_id": c["id"], "input": c["input"], "history": c["history"],
                       "attachments": c["attachments"]},
            "outputs": {"reference": c["reference"], "criteria": c["criteria"],
                        "must_not": c["must_not"], "expected": c["expected"]},
            "metadata": {"case_id": c["id"], "category": c["category"], "tags": c["tags"]},
        } for c in new])
        print(f"Uploaded {len(new)} case(s) to the LangSmith dataset {DATASET_NAME}.")
        examples = by_case_id()
    return dataset, examples


def ensure_experiment(client, dataset, record: dict):
    """The experiment for this result's prompt version, created on first use."""
    from langsmith.utils import LangSmithNotFoundError

    name = f"golden-judge-{record['prompt_version']}"
    try:
        return client.read_project(project_name=name)
    except LangSmithNotFoundError:
        return client.create_project(
            name, reference_dataset_id=dataset.id,
            description="Stored golden-eval answers scored by an LLM judge (evals/judge_golden.py).",
            metadata={"prompt_version": record["prompt_version"], "pipeline_model": record["model"],
                      "judge_model": JUDGE_MODEL})


def log_case(client, experiment, example, record: dict, checks: list[dict],
             judge_run_id: str | None, old_run_id: str | None) -> str:
    """Add the case to the experiment (or update its row) with its scores. Returns the run id."""
    from langsmith.run_trees import RunTree

    finished = datetime.fromisoformat(record["ran_at"])
    started = finished - timedelta(seconds=record["elapsed_seconds"])
    outputs = {k: record[k] for k in ("answer", "kind", "source", "question", "context")}

    if old_run_id:
        for feedback in client.list_feedback(run_ids=[old_run_id]):
            client.delete_feedback(feedback.id)
        client.update_run(old_run_id, outputs=outputs, start_time=started, end_time=finished)
        run_id = old_run_id
    else:
        run = RunTree(name="golden_case", run_type="chain", inputs=dict(example.inputs),
                      project_name=experiment.name, reference_example_id=example.id,
                      start_time=started, ls_client=client,
                      extra={"metadata": {"case_id": record["id"], "category": record["category"],
                                          "prompt_version": record["prompt_version"],
                                          "model": record["model"]}})
        run.end(outputs=outputs, end_time=finished)
        run.post()
        run_id = str(run.id)

    for key, (score, comment) in scores(checks).items():
        client.create_feedback(run_id, key, score=score, comment=comment, trace_id=run_id,
                               source_run_id=judge_run_id, feedback_source_type="model")
    client.flush()
    return run_id


def print_status(cases: list[dict], results: dict[str, dict], judgments: dict[str, dict]) -> None:
    todo = judgeable(cases, results)
    current = [r for r in todo if is_current(r, judgments)]
    print(f"{len(current)} of {len(todo)} results judged in {os.path.relpath(JUDGMENTS, ROOT)} "
          f"({len(results) - len(todo)} with failed routing checks are not judged)\n")

    eligible = Counter(r["category"] for r in todo)
    judged = Counter(r["category"] for r in current)
    passed = Counter(r["category"] for r in current if judgments[r["id"]]["passed"])
    for category, n in eligible.items():
        rate = f"{passed[category]} passed" if judged[category] else ""
        print(f"  {category:15} {judged[category]:>2} / {n}   {rate}")

    scored = [r for r in current if r["category"] != "policy_gap"]
    if scored:
        n_passed = sum(judgments[r["id"]]["passed"] for r in scored)
        print(f"\nPass rate: {n_passed} / {len(scored)} ({n_passed / len(scored):.0%}), "
              "policy_gap excluded")

    failed = [(r["id"], [c["item"] for c in judgments[r["id"]]["checks"] if not c["passed"]])
              for r in current if not judgments[r["id"]]["passed"]]
    if failed:
        print("\nJudged as failing (see judgments.jsonl or LangSmith for the reasons):")
        for cid, items in failed:
            print(f"  {cid}: {', '.join(items)}")

    experiments = sorted({judgments[r["id"]]["experiment"] for r in current})
    if experiments:
        print(f"\nLangSmith: dataset {DATASET_NAME}, experiment(s) {', '.join(experiments)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=10,
                        help="how many cases to judge this time (default: 10)")
    parser.add_argument("--category", help="only judge cases in this category")
    parser.add_argument("--ids", nargs="+", metavar="ID",
                        help="judge exactly these cases, even if already judged")
    parser.add_argument("--sleep", type=float, default=5.0,
                        help="seconds to wait between judge calls (default: 5)")
    parser.add_argument("--status", action="store_true",
                        help="show progress and exit without calling any model")
    args = parser.parse_args()

    cases = load_cases()
    results = load_results()
    judgments = load_judgments()

    if args.status:
        print_status(cases, results, judgments)
        return

    eligible = judgeable(cases, results)
    if args.ids:
        known = {r["id"] for r in eligible}
        unknown = [i for i in args.ids if i not in known]
        if unknown:
            sys.exit(f"No stored result with passing routing checks for: {', '.join(unknown)}")
        todo = [r for r in eligible if r["id"] in args.ids]
    else:
        todo = [r for r in eligible if not is_current(r, judgments)
                and (not args.category or r["category"] == args.category)]
        todo = todo[:args.limit]

    if not todo:
        print("Nothing to judge.")
        print_status(cases, results, judgments)
        return

    from dotenv import load_dotenv
    load_dotenv()
    if not os.getenv("GROQ_API_KEY"):
        sys.exit("No GROQ_API_KEY found. Add it to .env first.")

    from groq import RateLimitError
    from langchain_groq import ChatGroq
    from langsmith import Client
    from pydantic import BaseModel, Field

    from app import observability as obs

    if not obs.configure_langsmith():
        sys.exit("No LANGSMITH_API_KEY found. Add it to .env first.")

    class ItemResult(BaseModel):
        item: str = Field(description="The item id, such as C1, M2 or R3.")
        reason: str = Field(description="One sentence on what in the answer decided it.")
        passed: bool

    class Verdict(BaseModel):
        results: list[ItemResult]

    llm = ChatGroq(model=JUDGE_MODEL, api_key=os.getenv("GROQ_API_KEY"),
                   temperature=0).with_structured_output(Verdict)
    client = Client()
    cases_by_id = {c["id"]: c for c in cases}
    global_criteria = load_global_criteria()
    dataset, examples = ensure_examples(client, cases)

    print(f"Judging {len(todo)} case(s) with {JUDGE_MODEL}\n")
    stored = 0
    for number, record in enumerate(todo, 1):
        case = cases_by_id[record["id"]]
        label = f"[{number}/{len(todo)}] {record['id']}"
        called_judge = case["expected"]["behavior"] not in FIXED_REPLIES
        try:
            if called_judge:
                config = obs.run_config(
                    conversation_id=f"golden-judge-{record['id']}", turn_index=0,
                    run_name="golden_judge",
                    extra_metadata={"case_id": record["id"], "judge_model": JUDGE_MODEL,
                                    "prompt_version": record["prompt_version"]},
                    extra_tags=["golden-judge"],
                )
                for attempt in range(1, 4):
                    try:
                        with obs.traced_run() as handle:
                            checks = judge(case, record,
                                           checklist(case, record, global_criteria), llm, config)
                        break
                    except RateLimitError as exc:
                        wait = retry_after(exc)
                        if attempt == 3 or wait is None or wait > MAX_WAIT:
                            raise
                        print(f"{label}  per-minute limit reached, waiting {wait:.0f} s")
                        time.sleep(wait + 1)
                judge_run_id = handle.run_id
            else:
                checks, judge_run_id = fixed_reply_checks(case), None
        except RateLimitError as exc:
            print(f"{label}  rate limit reached, stopping here.\n  {exc}")
            break
        except Exception as exc:
            print(f"{label}  ERROR, not stored: {type(exc).__name__}: {exc}")
            continue

        previous = judgments.get(record["id"])
        experiment_name = f"golden-judge-{record['prompt_version']}"
        old_run_id = (previous["run_id"] if previous and previous["experiment"] == experiment_name
                      else None)
        try:
            experiment = ensure_experiment(client, dataset, record)
            run_id = log_case(client, experiment, examples[record["id"]], record, checks,
                              judge_run_id, old_run_id)
        except Exception as exc:
            print(f"{label}  judged, but LangSmith logging failed, not stored: "
                  f"{type(exc).__name__}: {exc}")
            continue

        judgment = {
            "id": record["id"],
            "category": record["category"],
            "prompt_version": record["prompt_version"],
            "result_ran_at": record["ran_at"],
            "judged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "judge_model": JUDGE_MODEL if called_judge else "routing check",
            "experiment": experiment.name,
            "run_id": run_id,
            "judge_run_id": judge_run_id,
            "passed": all(c["passed"] for c in checks),
            "scores": {key: score for key, (score, _) in scores(checks).items()},
            "checks": checks,
        }
        with open(JUDGMENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(judgment, ensure_ascii=False) + "\n")
        judgments[record["id"]] = judgment
        stored += 1

        failed = [c["item"] for c in checks if not c["passed"]]
        print(f"{label}  " + ("PASS" if not failed else "FAIL: " + ", ".join(failed))
              + ("" if called_judge else "  (fixed reply, no judge call)"))

        if called_judge and number < len(todo):
            time.sleep(args.sleep)

    print(f"\nStored {stored} new judgment(s).")
    print_status(cases, results, judgments)


if __name__ == "__main__":
    main()
