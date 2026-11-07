"""Command-line interface.

  python -m src.cli                      # pick a curated example
  python -m src.cli "How many singers?"  # ask anything (LLM mode if key set)
"""
import argparse

from . import config, db, nl2sql


def show(question: str, mode: str | None) -> None:
    try:
        out = nl2sql.answer(question, mode)
    except (nl2sql.DemoMiss, db.UnsafeSQLError, db.QueryError, RuntimeError) as exc:
        print(f"\n⚠️  {exc}")
        return
    print(f"\nMode: {out['mode']}\nSQL : {out['sql']}\n")
    df = out["result"].to_df()
    print(df.to_string(index=False) if not df.empty else "(no rows)")
    if out["result"].truncated:
        print(f"... truncated to {config.MAX_ROWS} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description="Text-to-SQL assistant")
    parser.add_argument("question", nargs="?", help="question in plain English")
    parser.add_argument("--mode", choices=["demo", "llm"], help="force a mode")
    args = parser.parse_args()

    if args.question:
        show(args.question, args.mode)
        return

    examples = nl2sql.load_examples()[:15]
    for i, e in enumerate(examples, 1):
        print(f"{i:>2}. {e['question']}")
    choice = input("\nPick a number (or type your own question): ").strip()
    question = examples[int(choice) - 1]["question"] if choice.isdigit() else choice
    show(question, args.mode)


if __name__ == "__main__":
    main()
