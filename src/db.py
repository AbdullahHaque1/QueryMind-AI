"""Schema introspection + guarded, read-only query execution."""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass

import pandas as pd 

from . import config


class UnsafeSQLError(ValueError):
    """The SQL is not a single read-only SELECT."""


class QueryError(RuntimeError):
    """The SQL was safe but failed to run (syntax error, timeout, ...)."""


# ───────────── Schema ─────────────
def get_schema() -> str:
    """Return all CREATE TABLE statements – the context we give the LLM."""
    con = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL "
            "ORDER BY name").fetchall()
    finally:
        con.close()
    return "\n\n".join(r[0].strip() for r in rows)


# ───────────── Layer 1: static validation ─────────────
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex|truncate|"
    r"begin|commit|rollback|savepoint|release)\b|\breplace\s+into\b", re.IGNORECASE)

# One pass over the text: quoted things first ('..', "..", `..`, [..]), then comments.
# Because the alternation is tried left to right, a "--" inside a string is never
# mistaken for a comment, and an apostrophe inside [a'b] never opens a string.
_TOKEN = re.compile(
    r"""(?P<quoted>'(?:[^']|'')*'|"(?:[^"]|"")*"|`(?:[^`]|``)*`|\[[^\]]*\])"""
    r"""|(?P<comment>--[^\n]*|/\*.*?\*/)""", re.DOTALL)


def _scan(sql: str) -> tuple[str, str]:
    """Return (cleaned, probe).

    cleaned : the SQL with comments removed - this is what actually gets executed.
    probe   : cleaned with every quoted item blanked out, so that keywords or
              semicolons inside literals and identifiers are not counted.
    """
    cleaned, probe, pos = [], [], 0
    for m in _TOKEN.finditer(sql):
        plain = sql[pos:m.start()]
        cleaned.append(plain)
        probe.append(plain)
        if m.lastgroup == "quoted":
            cleaned.append(m.group())
            probe.append("''")
        else:                                  # comment
            cleaned.append(" ")
            probe.append(" ")
        pos = m.end()
    tail = sql[pos:]
    cleaned.append(tail)
    probe.append(tail)
    return "".join(cleaned), "".join(probe)


def validate_select(sql: str) -> str:
    """Return a cleaned single SELECT, or raise UnsafeSQLError."""
    if not sql or not sql.strip():
        raise UnsafeSQLError("Empty query.")
    cleaned, probe = _scan(sql)
    cleaned = cleaned.strip().rstrip(";").strip()
    probe = probe.strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeSQLError("Empty query.")
    if ";" in probe:
        raise UnsafeSQLError("Only one statement is allowed.")
    if not re.match(r"(?i)^\s*(select|with)\b", probe):
        raise UnsafeSQLError("Only SELECT queries are allowed.")
    bad = _FORBIDDEN.search(probe)
    if bad:
        raise UnsafeSQLError(f"Forbidden keyword: {bad.group(0).split()[0].upper()}")
    return cleaned


# ───────────── Layers 2-4: guarded execution ─────────────
_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}


def _authorizer(action, *_args):
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


@dataclass
class QueryResult:
    columns: list
    rows: list
    truncated: bool = False

    def to_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=self.columns)


def run_query(sql: str, max_rows: int | None = None, timeout: float | None = None) -> QueryResult:
    """Validate, then run `sql` on a read-only connection with row + time limits."""
    sql = validate_select(sql)                               # layer 1
    max_rows = max_rows or config.MAX_ROWS
    timeout = timeout or config.TIMEOUT_SECONDS

    con = sqlite3.connect(f"file:{config.DB_PATH.as_posix()}?mode=ro", uri=True)   # layer 2
    con.set_authorizer(_authorizer)                                                # layer 3
    deadline = time.monotonic() + timeout
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)  # layer 4
    try:
        cur = con.execute(sql)
        fetched = cur.fetchmany(max_rows + 1)
        cols = [d[0] for d in cur.description] if cur.description else []
        return QueryResult(cols, [tuple(r) for r in fetched[:max_rows]], len(fetched) > max_rows)
    except sqlite3.Error as exc:
        raise QueryError(str(exc)) from exc
    finally:
        con.close()
