"""Natural language -> SQL, then guarded execution."""
from __future__ import annotations

import difflib
import json
import re

from . import config, db
 

class DemoMiss(LookupError):
    """Demo mode could not find a close curated question."""


# ───────────── helpers ─────────────
def load_examples(path=None) -> list[dict]:
    path = path or config.EXAMPLES_PATH
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    ratio = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return 0.5 * jaccard + 0.5 * ratio


def pick_examples(question: str, k: int = 5) -> list[dict]:
    """The k curated examples most similar to the question."""
    return sorted(load_examples(), key=lambda e: _similarity(question, e["question"]), reverse=True)[:k]


def clean_sql(text: str) -> str:
    """Remove ```sql fences / chatter and keep the SQL."""
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (m.group(1) if m else text).strip()


# ───────────── demo mode ─────────────
def demo_sql(question: str, threshold: float = 0.55) -> str:
    examples = load_examples()
    if not examples:
        raise DemoMiss("No examples found - run `python -m src.build_db` first.")
    best = max(examples, key=lambda e: _similarity(question, e["question"]))
    if _similarity(question, best["question"]) < threshold:
        hints = [e["question"] for e in pick_examples(question, 3)]
        raise DemoMiss("Demo mode only knows curated questions. Try one of:\n- " + "\n- ".join(hints))
    return best["sql"]


# ───────────── LLM mode ─────────────
SYSTEM_PROMPT = (
    "You are an expert SQLite analyst. Given a database schema and a question, "
    "write ONE read-only SQLite SELECT query that answers it.\n"
    "Rules: use only tables/columns that exist in the schema; output only the SQL, "
    "no explanation and no markdown; never write INSERT/UPDATE/DELETE/DDL."
)


def build_messages(question: str, schema: str, previous_sql=None, error=None, k: int = 5) -> list[dict]:
    shots = "\n\n".join(f"Question: {e['question']}\nSQL: {e['sql']}" for e in pick_examples(question, k)) if k > 0 else ""
    examples_block = f"### Solved examples\n{shots}\n\n" if shots else ""
    user = f"### Schema\n{schema}\n\n{examples_block}### Question\n{question}\nSQL:"
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
    if previous_sql and error:                       # self-correction round
        messages += [
            {"role": "assistant", "content": previous_sql},
            {"role": "user", "content": f"That query failed with: {error}\nReturn a corrected SQL query only."},
        ]
    return messages


def _call_llm(messages: list[dict]) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    resp = client.chat.completions.create(model=config.MODEL, messages=messages, temperature=0)
    return resp.choices[0].message.content


def llm_sql(question: str, schema: str, previous_sql=None, error=None, k: int = 5) -> str:
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set - use demo mode or add a key to .env")
    return clean_sql(_call_llm(build_messages(question, schema, previous_sql, error, k)))


# ───────────── public entry point ─────────────
def answer(question: str, mode: str | None = None, k: int = 5, retry: bool = True) -> dict:
    """question -> {'mode', 'sql', 'result': QueryResult}

    k     : number of few-shot examples in the prompt (LLM mode)
    retry : allow one self-correction round after a failed query (LLM mode)
    """
    mode = mode or config.default_mode()
    schema = db.get_schema()
    sql = demo_sql(question) if mode == "demo" else llm_sql(question, schema, k=k)
    try:
        result = db.run_query(sql)
    except (db.UnsafeSQLError, db.QueryError) as first_error:
        if mode != "llm" or not retry:
            raise
        sql = llm_sql(question, schema, previous_sql=sql, error=str(first_error), k=k)   # one retry
        result = db.run_query(sql)
    return {"mode": mode, "sql": db.validate_select(sql), "result": result}
