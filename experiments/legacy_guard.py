"""Layer-1 validator exactly as first written (v1). Kept only so the experiments can
compare it with the current validator (v2) in src/db.py."""
import re

from src.db import UnsafeSQLError

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|vacuum|reindex|truncate|"
    r"begin|commit|rollback|savepoint|release)\b", re.IGNORECASE)


def _strip_comments(sql):
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _blank_literals(sql):
    return re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", "''", sql)


def validate_select_v1(sql):
    if not sql or not sql.strip():
        raise UnsafeSQLError("Empty query.")
    cleaned = _strip_comments(sql).strip().rstrip(";").strip()
    probe = _blank_literals(cleaned)
    if ";" in probe:
        raise UnsafeSQLError("Only one statement is allowed.")
    if not re.match(r"(?i)^\s*(select|with)\b", probe):
        raise UnsafeSQLError("Only SELECT queries are allowed.")
    bad = _FORBIDDEN.search(probe)
    if bad:
        raise UnsafeSQLError(f"Forbidden keyword: {bad.group(1).upper()}")
    return cleaned
