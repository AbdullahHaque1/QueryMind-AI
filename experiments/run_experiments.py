"""Offline experiments used in the project report. No API key and no Spider download needed.

  python -m experiments.run_experiments

Everything runs on the small e-commerce database that src.build_db can generate
(seed 42), built into a temporary folder so your own database is never touched.
Results are written to results/results.json.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

from src import build_db, config, db, evaluate, nl2sql
from experiments import suites
from experiments.legacy_guard import validate_select_v1

OUT = config.ROOT / "results"


# ───────────────────────── helpers ─────────────────────────
def digest(path: Path) -> str:
    """Whole-database fingerprint: every table, row and the user_version header field."""
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        dump = "\n".join(con.iterdump())
        version = con.execute("PRAGMA user_version").fetchone()[0]
    finally:
        con.close()
    return f"{version}|{dump}"


def ms(x: float) -> float:
    return round(x * 1000, 3)


def pct(a: int, b: int) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


# ───────────────────────── E1: safety layers ─────────────────────────
VALIDATORS = {"v1": validate_select_v1, "v2": db.validate_select}
CONFIGS = {
    "no protection": dict(l1=None, ro=False, auth=False),
    "L1 (v1)":       dict(l1="v1", ro=False, auth=False),
    "L1 (v2)":       dict(l1="v2", ro=False, auth=False),
    "L2 read-only":  dict(l1=None, ro=True, auth=False),
    "L3 authorizer": dict(l1=None, ro=False, auth=True),
    "L2+L3":         dict(l1=None, ro=True, auth=True),
    "full (v2+L2+L3)": dict(l1="v2", ro=True, auth=True),
}


def attempt(cfg: dict, sql: str, base: Path, work: Path):
    """Run one statement under one configuration on a fresh copy. -> (status, modified)"""
    shutil.copy(base, work)
    before = digest(work)
    status = "executed"
    try:
        query = VALIDATORS[cfg["l1"]](sql) if cfg["l1"] else sql
        mode = "ro" if cfg["ro"] else "rw"
        con = sqlite3.connect(f"file:{work.as_posix()}?mode={mode}", uri=True)
        try:
            if cfg["auth"]:
                con.set_authorizer(db._authorizer)
            con.execute(query).fetchall()
            con.commit()
        finally:
            con.close()
    except db.UnsafeSQLError:
        status = "rejected"
    except sqlite3.Error:
        status = "errored"
    return status, digest(work) != before


def safety_ablation(base: Path, work: Path) -> dict:
    out = {"n_attacks": len(suites.ATTACKS), "configs": {}, "by_category": {}, "admitted_by_l1": {}}
    for name, cfg in CONFIGS.items():
        tally = Counter()
        cats = defaultdict(Counter)
        for cat, sql in suites.ATTACKS:
            status, modified = attempt(cfg, sql, base, work)
            tally[status] += 1
            tally["modified"] += int(modified)
            cats[cat][status] += 1
            cats[cat]["modified"] += int(modified)
        out["configs"][name] = {k: tally.get(k, 0) for k in ("rejected", "errored", "executed", "modified")}
        out["by_category"][name] = {c: dict(v) for c, v in cats.items()}
    # which attacks did each static validator let through?
    for tag, fn in VALIDATORS.items():
        passed = []
        for cat, sql in suites.ATTACKS:
            try:
                fn(sql)
                passed.append({"category": cat, "sql": sql})
            except db.UnsafeSQLError:
                pass
        out["admitted_by_l1"][tag] = passed
    out["categories"] = sorted({c for c, _ in suites.ATTACKS})
    out["category_sizes"] = dict(Counter(c for c, _ in suites.ATTACKS))
    return out


def benign_check(base: Path) -> dict:
    res = {"n_benign": len(suites.BENIGN), "validators": {}}
    raw_con = sqlite3.connect(f"file:{base.as_posix()}?mode=ro", uri=True)

    def raw_rows(sql):
        return raw_con.execute(sql).fetchall()

    for tag in ("v1", "v2", "full"):
        accepted, parity, bad = 0, 0, []
        for cat, sql in suites.BENIGN:
            try:
                if tag == "full":
                    got = db.run_query(sql).rows
                    cleaned = sql
                else:
                    cleaned = VALIDATORS[tag](sql)
                    got = [tuple(r) for r in raw_rows(cleaned)]
                accepted += 1
                same = got == [tuple(r) for r in raw_rows(sql)]
                parity += int(same)
                if not same:
                    bad.append({"category": cat, "sql": sql, "why": "result differs"})
            except db.UnsafeSQLError as exc:
                bad.append({"category": cat, "sql": sql, "why": f"rejected: {exc}"})
            except sqlite3.Error as exc:
                accepted += 1                               # passed the check, then failed to run
                bad.append({"category": cat, "sql": sql, "why": f"error: {exc}"})
            except db.QueryError as exc:
                accepted += 1
                bad.append({"category": cat, "sql": sql, "why": f"error: {exc}"})
        res["validators"][tag] = {"accepted": accepted, "same_result": parity, "problems": bad}
    raw_con.close()
    return res


# ───────────────────────── E2: resource limits ─────────────────────────
RUNAWAY = "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) SELECT COUNT(*) FROM c"
HEAVY = "SELECT COUNT(*) FROM order_items a, order_items b, order_items c, order_items d"
CROSS = "SELECT * FROM order_items a, order_items b"


def limits() -> dict:
    out = {"timeout": [], "row_cap": []}
    for label, sql in (("recursive CTE", RUNAWAY), ("four-way cross join", HEAVY)):
        for limit in (0.25, 0.5, 1.0, 2.0):
            runs = []
            for _ in range(3):
                t0 = time.monotonic()
                try:
                    db.run_query(sql, timeout=limit)
                    stopped = False
                except db.QueryError:
                    stopped = True
                runs.append((time.monotonic() - t0, stopped))
            out["timeout"].append({
                "query": label, "limit_s": limit,
                "stopped": all(s for _, s in runs),
                "mean_s": round(statistics.mean(t for t, _ in runs), 3),
                "max_s": round(max(t for t, _ in runs), 3)})
    # row cap
    con = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True)
    t0 = time.perf_counter()
    full = con.execute(CROSS).fetchall()
    full_time = time.perf_counter() - t0
    con.close()
    out["row_cap_unguarded"] = {"rows": len(full), "ms": ms(full_time)}
    for cap in (10, 50, 200, 1000):
        times = []
        for _ in range(20):
            t0 = time.perf_counter()
            r = db.run_query(CROSS, max_rows=cap)
            times.append(time.perf_counter() - t0)
        out["row_cap"].append({"cap": cap, "rows": len(r.rows), "truncated": r.truncated,
                               "median_ms": ms(statistics.median(times))})
    return out


# ───────────────────────── E3: demo-mode matcher ─────────────────────────
def matcher() -> dict:
    bank = [{"question": q, "sql": s} for q, s in suites.BANK]
    nl2sql.load_examples = lambda path=None: bank            # use the experiment bank
    sim = nl2sql._similarity

    def best(question):
        scores = [sim(question, e["question"]) for e in bank]
        i = max(range(len(bank)), key=lambda j: scores[j])
        return i, scores[i]

    inscope = []
    for gold_idx, diff, text in suites.PARAPHRASES:
        i, s = best(text)
        inscope.append({"gold": gold_idx, "difficulty": diff, "text": text, "pick": i, "score": round(s, 4)})
    oos = []
    for kind, text in suites.OUT_OF_SCOPE:
        i, s = best(text)
        oos.append({"kind": kind, "text": text, "pick": i, "score": round(s, 4)})

    sweep = []
    for t in [x / 100 for x in range(20, 85, 5)]:
        c = sum(1 for r in inscope if r["score"] >= t and r["pick"] == r["gold"])
        w = sum(1 for r in inscope if r["score"] >= t and r["pick"] != r["gold"])
        m = sum(1 for r in inscope if r["score"] < t)
        fa = sum(1 for r in oos if r["score"] >= t)
        sweep.append({"threshold": round(t, 2), "correct": c, "wrong": w, "missed": m,
                      "oos_accepted": fa, "oos_total": len(oos), "inscope_total": len(inscope)})
    # check the sweep agrees with the real demo_sql() at its default threshold
    agree = 0
    for r in inscope:
        try:
            got = nl2sql.demo_sql(r["text"])
            agree += int((got == bank[r["pick"]]["sql"]) == (r["score"] >= 0.55))
        except nl2sql.DemoMiss:
            agree += int(r["score"] < 0.55)
    by_diff = {}
    for d in ("easy", "medium", "hard"):
        rows = [r for r in inscope if r["difficulty"] == d]
        by_diff[d] = {"n": len(rows),
                      "correct": sum(1 for r in rows if r["score"] >= 0.55 and r["pick"] == r["gold"]),
                      "wrong": sum(1 for r in rows if r["score"] >= 0.55 and r["pick"] != r["gold"]),
                      "missed": sum(1 for r in rows if r["score"] < 0.55),
                      "mean_score": round(statistics.mean(r["score"] for r in rows), 3)}
    # do the bank queries really run?
    ok = 0
    for e in bank:
        try:
            db.run_query(e["sql"])
            ok += 1
        except Exception:
            pass
    return {"default_threshold": 0.55, "inscope": inscope, "oos": oos, "sweep": sweep,
            "by_difficulty": by_diff, "bank_size": len(bank), "bank_sql_runs": ok,
            "sweep_matches_demo_sql": f"{agree}/{len(inscope)}"}


# ───────────────────────── E4: latency ─────────────────────────
def latency() -> dict:
    queries = []
    for cat, sql in suites.BENIGN:
        try:
            db.validate_select(sql)
            queries.append(sql)
        except db.UnsafeSQLError:
            pass
    reps = 30
    val, guarded, raw = [], [], []
    for sql in queries:
        for _ in range(reps):
            t0 = time.perf_counter_ns(); db.validate_select(sql); val.append(time.perf_counter_ns() - t0)
            t0 = time.perf_counter_ns(); db.run_query(sql); guarded.append(time.perf_counter_ns() - t0)
            t0 = time.perf_counter_ns()
            con = sqlite3.connect(config.DB_PATH.as_posix())
            con.execute(sql).fetchmany(config.MAX_ROWS + 1)
            con.close()
            raw.append(time.perf_counter_ns() - t0)

    def stats(xs, unit):
        xs = sorted(xs)
        f = 1e3 if unit == "us" else 1e6
        return {"mean": round(statistics.mean(xs) / f, 3), "median": round(statistics.median(xs) / f, 3),
                "p95": round(xs[int(0.95 * (len(xs) - 1))] / f, 3)}
    return {"queries": len(queries), "repetitions": reps,
            "validate_us": stats(val, "us"), "guarded_ms": stats(guarded, "ms"), "raw_ms": stats(raw, "ms")}


# ───────────────────────── E5: prompt size ─────────────────────────
def prompt_size() -> dict:
    schema = db.get_schema()
    rows = []
    for k in (0, 1, 3, 5, 10):
        sizes = []
        for _, _, text in suites.PARAPHRASES:
            msgs = nl2sql.build_messages(text, schema, k=k)
            sizes.append(sum(len(m["content"]) for m in msgs))
        rows.append({"k": k, "mean_chars": round(statistics.mean(sizes)), "min_chars": min(sizes),
                     "max_chars": max(sizes), "approx_tokens": round(statistics.mean(sizes) / 4)})
    return {"schema_chars": len(schema), "rows": rows,
            "note": "approx_tokens = characters / 4, a rough rule of thumb for English text and SQL"}


# ───────────────────────── E6: evaluator self-check ─────────────────────────
def evaluator_check() -> dict:
    agree_eq = agree_ne = 0
    n_eq = sum(1 for *_, m in suites.EVAL_PAIRS if m)
    n_ne = len(suites.EVAL_PAIRS) - n_eq
    wrong = []
    for a, b, should in suites.EVAL_PAIRS:
        same = evaluate._norm(db.run_query(a).rows) == evaluate._norm(db.run_query(b).rows)
        if same == should:
            agree_eq += int(should)
            agree_ne += int(not should)
        else:
            wrong.append({"a": a, "b": b, "expected_match": should, "evaluator_said_match": same})
    return {"equivalent_pairs": n_eq, "equivalent_ok": agree_eq,
            "different_pairs": n_ne, "different_ok": agree_ne, "disagreements": wrong}


# ───────────────────────── main ─────────────────────────
def main() -> None:
    OUT.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="t2s_exp_"))
    saved = (config.DB_PATH, config.EXAMPLES_PATH, config.DEV_PATH, os.getcwd())
    config.DB_PATH, config.EXAMPLES_PATH, config.DEV_PATH = tmp / "shop.sqlite", tmp / "ex.json", tmp / "dev.json"
    os.chdir(tmp)                                   # ATTACH 'evil.db' must not litter the project
    try:
        build_db.build_fallback()
        base, work = config.DB_PATH, tmp / "work.sqlite"
        results = {
            "environment": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
                            "platform": platform.platform(), "cpu_count": os.cpu_count()},
            "database": {"tables": ["customers", "products", "orders", "order_items"],
                         "rows": {t: sqlite3.connect(base).execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                                  for t in ("customers", "products", "orders", "order_items")}},
        }
        print("E1 safety ablation ..."); results["safety"] = safety_ablation(base, work)
        print("E1b benign queries ..."); results["benign"] = benign_check(base)
        print("E2 resource limits ..."); results["limits"] = limits()
        print("E3 demo matcher ...");    results["matcher"] = matcher()
        print("E4 latency ...");         results["latency"] = latency()
        print("E5 prompt size ...");     results["prompt"] = prompt_size()
        print("E6 evaluator check ...");  results["evaluator"] = evaluator_check()
    finally:
        config.DB_PATH, config.EXAMPLES_PATH, config.DEV_PATH, cwd = saved
        os.chdir(cwd)
        shutil.rmtree(tmp, ignore_errors=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("Saved", OUT / "results.json")


if __name__ == "__main__":
    main()
