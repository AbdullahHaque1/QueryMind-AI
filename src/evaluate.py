"""Execution-accuracy evaluation on held-out dev questions.

  python -m src.evaluate            # needs OPENAI_API_KEY
"""
from __future__ import annotations

import json
from collections import Counter

from . import config, db, nl2sql 


def _norm(rows) -> Counter:
    """Order-insensitive multiset of rows (floats rounded)."""
    return Counter(tuple(round(v, 4) if isinstance(v, float) else v for v in r) for r in rows)


def evaluate(limit: int | None = None, verbose: bool = True, k: int = 5, retry: bool = True) -> dict:
    dev = json.loads(config.DEV_PATH.read_text(encoding="utf-8"))[:limit]
    correct, failures = 0, []
    for item in dev:
        try:
            pred = nl2sql.answer(item["question"], mode="llm", k=k, retry=retry)["sql"]
            ok = _norm(db.run_query(pred).rows) == _norm(db.run_query(item["sql"]).rows)
        except Exception as exc:                   # any failure counts as wrong
            pred, ok = f"ERROR: {exc}", False
        correct += ok
        if not ok:
            failures.append({"question": item["question"], "gold": item["sql"], "pred": pred})
    report = {"total": len(dev), "correct": correct,
              "accuracy": round(correct / len(dev), 3) if dev else 0.0, "failures": failures}
    if verbose:
        print(f"Execution accuracy: {correct}/{len(dev)} = {report['accuracy']:.1%}")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Execution accuracy on dev questions")
    parser.add_argument("--limit", type=int, default=None, help="only the first N dev questions")
    args = parser.parse_args()
    if not config.OPENAI_API_KEY:
        raise SystemExit("Set OPENAI_API_KEY first - evaluation needs LLM mode.")
    report = evaluate(limit=args.limit)
    out_dir = config.ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"eval_{config.DB_NAME}_{config.MODEL}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Saved:", out)
