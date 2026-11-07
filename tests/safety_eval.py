"""Measure the SQL safety layers on hand-written query sets.

Run:  python -m tests.safety_eval
(needs the database: python -m src.build_db)
"""
import sqlite3
import statistics
import time

from src import config, db

# Statements that must NOT get through the static check (layer 1).
HOSTILE = [
    "SELECT 1; DROP TABLE t",
    "DROP TABLE t",
    "DELETE FROM t",
    "UPDATE t SET a = 1",
    "INSERT INTO t VALUES (1)",
    "/* x */ UPDATE t SET a = 1",
    "-- hi\nDELETE FROM t",
    "SeLeCt 1; dRoP TABLE t",
    "SELECT * FROM t; SELECT 2",
    "PRAGMA table_info(t)",
    "ATTACH DATABASE 'evil.db' AS e",
    "DETACH DATABASE e",
    "VACUUM",
    "ALTER TABLE t ADD COLUMN z INT",
    "CREATE TABLE z(a)",
    "BEGIN; DELETE FROM t; COMMIT",
    "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x",
    "WITH x AS (SELECT 1) DELETE FROM t",
    "REPLACE INTO t VALUES (1)",
    "",
    "   ",
    "EXPLAIN DELETE FROM t",
    "SELECT 1 /* */ ; /* */ DROP TABLE t",
    "SELECT 1;\nUPDATE t SET a = 2",
]

# Legitimate read-only queries that must pass the static check.
BENIGN = [
    "SELECT * FROM t",
    "SELECT COUNT(*) FROM t",
    "SELECT a, b FROM t WHERE a > 3 ORDER BY b DESC LIMIT 5",
    "SELECT 'update me' AS note",
    "SELECT 'drop table x; delete' AS s",
    'SELECT "update" FROM t',
    "SELECT update_date, created_at FROM t",
    "SELECT a FROM t -- trailing comment",
    "SELECT a FROM t /* block */ WHERE a = 1",
    "SELECT t1.a FROM t AS t1 JOIN u AS t2 ON t1.id = t2.id",
    "SELECT a FROM t WHERE b IN (SELECT b FROM u)",
    "SELECT a, COUNT(*) FROM t GROUP BY a HAVING COUNT(*) > 1",
    "WITH x AS (SELECT 1 AS v) SELECT v FROM x",
    "WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM c WHERE n < 5) SELECT n FROM c",
    "SELECT a FROM t UNION SELECT a FROM u",
    "SELECT a FROM t EXCEPT SELECT a FROM u",
    "SELECT CASE WHEN a > 1 THEN 'hi' ELSE 'lo' END FROM t",
    "SELECT it''s FROM t".replace("it''s", "'it''s'"),
    "SELECT a FROM t;",
    "select max(a) from t",
    # identifiers that collide with blocked words (known weak spot)
    "SELECT begin FROM t",
    "SELECT release FROM t",
]

# Write attempts sent straight to the connection, skipping layer 1.
RAW_WRITES = [
    "CREATE TABLE zz(a)",
    "INSERT INTO orders(id) VALUES (99999)",
    "UPDATE orders SET status = 'x'",
    "DELETE FROM orders",
    "DROP TABLE orders",
    "PRAGMA user_version = 5",
    "ATTACH DATABASE ':memory:' AS m",
]


def static_check():
    blocked = 0
    for q in HOSTILE:
        try:
            db.validate_select(q)
        except db.UnsafeSQLError:
            blocked += 1
    passed, false_pos = 0, []
    for q in BENIGN:
        try:
            db.validate_select(q)
            passed += 1
        except db.UnsafeSQLError:
            false_pos.append(q)
    return blocked, passed, false_pos


def raw_write_check():
    """Layers 2 and 3 only: read-only connection + authorizer, no regex layer."""
    denied = 0
    for q in RAW_WRITES:
        con = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True)
        con.set_authorizer(db._authorizer)
        try:
            con.execute(q)
        except sqlite3.Error:
            denied += 1
        finally:
            con.close()
    return denied


def timeout_check():
    sql = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c) "
           "SELECT COUNT(*) FROM c")
    t0 = time.monotonic()
    try:
        db.run_query(sql)
        stopped = False
    except db.QueryError:
        stopped = True
    return stopped, time.monotonic() - t0


def truncation_check():
    r = db.run_query("SELECT * FROM orders a, orders b")
    return len(r.rows), r.truncated


def validate_latency(n=20000):
    q = "SELECT a, COUNT(*) FROM t JOIN u ON t.id = u.id WHERE a > 3 GROUP BY a ORDER BY a LIMIT 10"
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        db.validate_select(q)
        samples.append(time.perf_counter() - t0)
    return statistics.mean(samples) * 1e6, statistics.median(samples) * 1e6


if __name__ == "__main__":
    blocked, passed, fp = static_check()
    print(f"Layer 1  hostile blocked : {blocked}/{len(HOSTILE)}")
    print(f"Layer 1  benign accepted : {passed}/{len(BENIGN)}")
    for q in fp:
        print("         false positive  :", q)
    print(f"Layers 2+3 raw writes denied: {raw_write_check()}/{len(RAW_WRITES)}")
    stopped, secs = timeout_check()
    print(f"Layer 4  runaway query stopped: {stopped} after {secs:.2f}s (limit {config.TIMEOUT_SECONDS}s)")
    rows, trunc = truncation_check()
    print(f"Layer 4  row cap: returned {rows} rows, truncated={trunc} (MAX_ROWS={config.MAX_ROWS})")
    mean_us, med_us = validate_latency()
    print(f"validate_select latency: mean {mean_us:.1f} us, median {med_us:.1f} us")
