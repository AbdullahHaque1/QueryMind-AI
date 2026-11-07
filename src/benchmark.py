"""Measure the safety guard, execution limits, latency and demo-mode matching.

Usage:  python -m src.benchmark          (writes results/benchmark.json)

It only needs the database + examples made by `python -m src.build_db`.
No API key is needed (LLM accuracy is measured separately by src.evaluate).
"""
from __future__ import annotations

import hashlib
import json 
import shutil
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path

from . import config, db, nl2sql

RESULTS_DIR = config.ROOT / "results"


# ───────────── helpers ─────────────
def first_table_and_column():
    con = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True)
    t = con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 1").fetchone()[0]
    c = con.execute(f'PRAGMA table_info("{t}")').fetchall()[1][1]
    con.close()
    return t, c


def unsafe_queries(t: str, c: str):
    return [
        ("stacked", f"SELECT 1; DROP TABLE {t}"),
        ("stacked", f"SELECT * FROM {t}; DELETE FROM {t}"),
        ("ddl", f"DROP TABLE {t}"),
        ("ddl", f"ALTER TABLE {t} ADD COLUMN evil INTEGER"),
        ("ddl", "CREATE TABLE evil(x INTEGER)"),
        ("ddl", f"CREATE INDEX evil_idx ON {t}({c})"),
        ("ddl", f"CREATE TRIGGER evil_t AFTER INSERT ON {t} BEGIN SELECT 1; END"),
        ("dml", f"DELETE FROM {t}"),
        ("dml", f"UPDATE {t} SET {c} = NULL"),
        ("dml", f"INSERT INTO {t} SELECT * FROM {t}"),
        ("dml", f"REPLACE INTO {t} SELECT * FROM {t}"),
        ("meta", "PRAGMA writable_schema = 1"),
        ("meta", f"PRAGMA table_info({t})"),
        ("meta", "ATTACH DATABASE ':memory:' AS evil"),
        ("meta", "VACUUM"),
        ("txn", "BEGIN"),
        ("txn", "COMMIT"),
        ("obfuscated", f"/* hi */ DROP TABLE {t}"),
        ("obfuscated", f"-- note\nDELETE FROM {t}"),
        ("obfuscated", f"dRoP tAbLe {t}"),
        ("obfuscated", f"   \n  DELETE FROM {t}"),
        ("obfuscated", f"WITH x AS (SELECT 1) DELETE FROM {t}"),
        ("obfuscated", f"SELECT 1 /* ; */ ; DROP TABLE {t}"),
        ("function", "SELECT load_extension('evil')"),
    ]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attempt(cfg: str, sql: str, tmp_db: Path) -> tuple[bool, bool]:
    """Run one attack under one configuration. Returns (executed, db_modified)."""
    before = sha(tmp_db)
    executed = False
    try:
        if cfg == "L1_static":
            db.validate_select(sql)
            con = sqlite3.connect(tmp_db)
            con.executescript(sql)
            con.commit(); con.close()
        elif cfg == "none":
            con = sqlite3.connect(tmp_db)
            con.executescript(sql)
            con.commit(); con.close()
        else:
            uri = f"file:{tmp_db.as_posix()}?mode=ro" if cfg in ("L2_readonly", "L2_L3") else f"file:{tmp_db.as_posix()}?mode=rw"
            con = sqlite3.connect(uri, uri=True)
            if cfg in ("L3_authorizer", "L2_L3"):
                con.set_authorizer(db._authorizer)
            con.executescript(sql)
            con.commit(); con.close()
        executed = True
    except Exception:
        executed = False
    return executed, sha(tmp_db) != before


def bench_guard() -> dict:
    t, c = first_table_and_column()
    attacks = unsafe_queries(t, c)
    configs = ["none", "L1_static", "L2_readonly", "L3_authorizer", "L2_L3"]
    out = {cfg: {"executed": 0, "modified": 0} for cfg in configs}
    out["all_four_layers"] = {"executed": 0, "modified": 0}
    by_cat: dict[str, list[int]] = {}
    for cat, sql in attacks:
        for cfg in configs:
            tmpdir = Path(tempfile.mkdtemp())
            tmp_db = tmpdir / "copy.sqlite"
            shutil.copy(config.DB_PATH, tmp_db)
            ex, mod = attempt(cfg, sql, tmp_db)
            out[cfg]["executed"] += ex
            out[cfg]["modified"] += mod
            shutil.rmtree(tmpdir, ignore_errors=True)
        # full pipeline (run_query) on a temp copy
        tmpdir = Path(tempfile.mkdtemp())
        tmp_db = tmpdir / "copy.sqlite"
        shutil.copy(config.DB_PATH, tmp_db)
        old = config.DB_PATH
        config.DB_PATH = tmp_db
        before = sha(tmp_db)
        try:
            db.run_query(sql)
            out["all_four_layers"]["executed"] += 1
        except Exception:
            pass
        out["all_four_layers"]["modified"] += sha(tmp_db) != before
        config.DB_PATH = old
        shutil.rmtree(tmpdir, ignore_errors=True)
        by_cat.setdefault(cat, [0, 0])
        by_cat[cat][0] += 1
    out["n_attacks"] = len(attacks)
    out["categories"] = {k: v[0] for k, v in by_cat.items()}
    return out


def bench_gold() -> dict:
    gold = nl2sql.load_examples() + nl2sql.load_examples(config.DEV_PATH)
    ok, errors, blocked, times = 0, 0, 0, []
    for g in gold:
        try:
            t0 = time.perf_counter()
            db.run_query(g["sql"])
            times.append((time.perf_counter() - t0) * 1000)
            ok += 1
        except db.UnsafeSQLError:
            blocked += 1
        except db.QueryError:
            errors += 1
    return {"n_gold": len(gold), "ran_ok": ok, "blocked_by_guard": blocked, "sql_errors": errors}


def bench_latency(reps: int = 100) -> dict:
    gold = nl2sql.load_examples() + nl2sql.load_examples(config.DEV_PATH)
    times = []
    for g in gold:
        for _ in range(reps):
            t0 = time.perf_counter()
            try:
                db.run_query(g["sql"])
            except Exception:
                continue
            times.append((time.perf_counter() - t0) * 1000)
    st = []
    for _ in range(reps):
        t0 = time.perf_counter(); db.get_schema(); st.append((time.perf_counter() - t0) * 1000)
    q = lambda xs, p: sorted(xs)[int(p * (len(xs) - 1))]
    return {"runs": len(times),
            "query_ms_mean": round(statistics.mean(times), 3),
            "query_ms_median": round(statistics.median(times), 3),
            "query_ms_p95": round(q(times, 0.95), 3),
            "schema_ms_mean": round(statistics.mean(st), 3)}


def bench_limits() -> dict:
    rows_sql = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<100000) "
                "SELECT x FROM c")
    t0 = time.perf_counter()
    r = db.run_query(rows_sql)
    row_ms = (time.perf_counter() - t0) * 1000
    heavy = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x<2000000000) "
             "SELECT COUNT(*) FROM c")
    t0 = time.perf_counter()
    killed = False
    try:
        db.run_query(heavy, timeout=1.0)
    except db.QueryError:
        killed = True
    elapsed = time.perf_counter() - t0
    return {"row_cap": config.MAX_ROWS, "rows_returned": len(r.rows), "truncated": r.truncated,
            "row_cap_query_ms": round(row_ms, 1),
            "timeout_set_s": 1.0, "heavy_query_stopped": killed, "heavy_query_elapsed_s": round(elapsed, 2)}


OFF_TOPIC = [
    "What is the meaning of life?", "Who won the football match yesterday?",
    "Tell me a joke about cats", "What is the capital of France?",
    "How do I bake bread at home?", "Translate good morning to Spanish",
    "What is the weather like in Delhi?", "Write a poem about the sea",
    "Who is the president of Brazil?", "Explain quantum computing",
]


def _variants(q: str):
    words = q.split()
    yield "exact", q
    yield "lower_nopunct", " ".join(w.strip("?.,!").lower() for w in words)
    yield "prefix_please", "please tell me " + q[0].lower() + q[1:]
    yield "suffix_db", q.rstrip("?.") + " in the database"
    if len(words) > 4:
        yield "drop_word", " ".join(words[:len(words) // 2] + words[len(words) // 2 + 1:])


def bench_demo() -> dict:
    ex = nl2sql.load_examples()
    stats: dict[str, dict] = {}
    for e in ex:
        for kind, text in _variants(e["question"]):
            s = stats.setdefault(kind, {"n": 0, "correct": 0, "miss": 0, "wrong": 0})
            s["n"] += 1
            try:
                sql = nl2sql.demo_sql(text)
                if sql == e["sql"] or db.run_query(sql).rows == db.run_query(e["sql"]).rows:
                    s["correct"] += 1
                else:
                    s["wrong"] += 1
            except nl2sql.DemoMiss:
                s["miss"] += 1
    rejected = 0
    for q in OFF_TOPIC:
        try:
            nl2sql.demo_sql(q)
        except nl2sql.DemoMiss:
            rejected += 1
    return {"n_examples": len(ex), "variants": stats,
            "off_topic_total": len(OFF_TOPIC), "off_topic_rejected": rejected}


def bench_size() -> dict:
    sizes = {}
    for p in sorted((config.ROOT / "src").glob("*.py")):
        if p.name == "benchmark.py":
            continue
        sizes[p.name] = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
    return sizes


def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    res = {
        "database": config.DB_NAME,
        "guard": bench_guard(),
        "gold": bench_gold(),
        "latency": bench_latency(),
        "limits": bench_limits(),
        "demo": bench_demo(),
        "non_blank_lines": bench_size(),
    }
    (RESULTS_DIR / "benchmark.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
