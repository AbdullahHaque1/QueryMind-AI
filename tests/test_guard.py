"""Attack our own safety guard.   Run:  python -m tests.test_guard   (or: pytest)"""
from src import db

ATTACKS = [
    "SELECT 1; DROP TABLE singer",
    "DROP TABLE singer",
    "DELETE FROM singer",
    "/* sneaky */ UPDATE singer SET name='x'",
    "SELECT * FROM singer; SELECT 2",
    "PRAGMA table_info(singer)",
    "ATTACH DATABASE 'evil.db' AS e",
    "",
]


def test_attacks_are_blocked():
    for q in ATTACKS:
        try:
            db.validate_select(q)
        except db.UnsafeSQLError:
            continue
        raise AssertionError(f"Guard allowed: {q!r}")


def test_keyword_inside_string_is_fine():
    assert db.validate_select("SELECT 'update me' AS note")


if __name__ == "__main__":
    for q in ATTACKS:
        try:
            db.validate_select(q)
            print("❌ ALLOWED  :", q)
        except db.UnsafeSQLError as e:
            print("✅ blocked  :", repr(q)[:45].ljust(47), "->", e)
    print("\nok ->", db.validate_select("SELECT 'update me' AS note"))
