"""Export recorded conversations for training or evaluation.

Usage:
    python export_conversations.py                       # summary only
    python export_conversations.py --out data.jsonl      # every turn, full detail
    python export_conversations.py --out sft.jsonl --format sft
    python export_conversations.py --out deploy.jsonl --environment deploy
    python export_conversations.py --to-langsmith my-dataset

Formats:
    raw  one JSON object per turn — question, answer, provenance, agent steps
    sft  {"messages": [{"role": "user", …}, {"role": "assistant", …}]}, the
         shape most fine-tuning pipelines expect
"""

import argparse
import json
import sys

from dotenv import load_dotenv

load_dotenv()

import conversation_store as store  # noqa: E402  (after load_dotenv)
import observability as obs  # noqa: E402


def write_sft(path: str, limit=None, environment=None) -> int:
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        for turn in store.iter_turns(limit=limit, environment=environment):
            if not (turn.get("question") and turn.get("answer")):
                continue
            record = {
                "messages": [
                    {"role": "user", "content": turn["question"]},
                    {"role": "assistant", "content": turn["answer"]},
                ],
                "metadata": {
                    "conversation_id": turn["conversation_id"],
                    "turn_index": turn["turn_index"],
                    "source": turn["source"],
                    "model": turn["model"],
                    "environment": turn["environment"],
                    "langsmith_run_id": turn["langsmith_run_id"],
                    "created_at": turn["created_at"],
                },
            }
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            count += 1
    return count


def push_to_langsmith(dataset_name: str, limit=None, environment=None) -> int:
    """Upload the transcripts as a LangSmith dataset for evaluation."""
    if not obs.configure_langsmith():
        sys.exit("LANGSMITH_API_KEY is not set — nothing to upload to.")
    from langsmith import Client

    client = Client()
    try:
        dataset = client.read_dataset(dataset_name=dataset_name)
    except Exception:
        dataset = client.create_dataset(
            dataset_name=dataset_name,
            description="Recorded turns from the multi-agent photography assistant.",
        )

    count = 0
    for turn in store.iter_turns(limit=limit, environment=environment):
        if not (turn.get("question") and turn.get("answer")):
            continue
        client.create_example(
            dataset_id=dataset.id,
            inputs={"user_input": turn["question"]},
            outputs={"final_response": turn["answer"]},
            metadata={"source": turn["source"], "environment": turn["environment"],
                      "conversation_id": turn["conversation_id"]},
        )
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", help="path to write JSONL to")
    parser.add_argument("--format", choices=["raw", "sft"], default="raw")
    parser.add_argument("--limit", type=int, help="cap the number of turns")
    parser.add_argument("--environment", help="only turns from this env, e.g. deploy")
    parser.add_argument("--to-langsmith", metavar="DATASET",
                        help="upload the turns as a LangSmith dataset")
    args = parser.parse_args()

    print(store.storage_notice())
    counts = store.stats()
    print(f"{counts['turns']} turn(s) across {counts['conversations']} conversation(s).")

    if args.to_langsmith:
        n = push_to_langsmith(args.to_langsmith, args.limit, args.environment)
        print(f"Uploaded {n} example(s) to LangSmith dataset '{args.to_langsmith}'.")

    if args.out:
        if args.format == "sft":
            n = write_sft(args.out, args.limit, args.environment)
        else:
            n = store.export_jsonl(args.out, args.limit, args.environment)
        print(f"Wrote {n} turn(s) to {args.out} ({args.format}).")
    elif not args.to_langsmith:
        print("\nNothing exported. Pass --out FILE or --to-langsmith DATASET.")


if __name__ == "__main__":
    main()
