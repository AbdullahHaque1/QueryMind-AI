"""Streamlit UI:  streamlit run src/app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # make `src` importable

import streamlit as st

from src import config, db, nl2sql 

st.set_page_config(page_title="Text-to-SQL Assistant", page_icon="🗄️", layout="wide")
st.title("🗄️ Text-to-SQL Assistant")
st.caption(f"Database: **{config.DB_NAME}** · read-only · SELECT queries only")

if not config.DB_PATH.exists():
    st.error("Database not found. Run `python -m src.build_db` first.")
    st.stop()

# ── sidebar ──
with st.sidebar:
    has_key = bool(config.OPENAI_API_KEY)
    mode = st.radio("Mode", ["demo", "llm"], index=1 if has_key else 0,
                    help="demo = curated questions, free. llm = any question, needs OPENAI_API_KEY.")
    if mode == "llm" and not has_key:
        st.warning("No OPENAI_API_KEY found - switch to demo mode or add one to .env")
    with st.expander("Database schema"):
        st.code(db.get_schema(), language="sql")

# ── question input ──
examples = nl2sql.load_examples()
choice = st.selectbox("Curated examples", ["(type your own)"] + [e["question"] for e in examples[:30]])
question = st.text_input("Your question", value="" if choice.startswith("(") else choice)

if st.button("Ask", type="primary") and question.strip():
    try:
        out = nl2sql.answer(question.strip(), mode)
    except (nl2sql.DemoMiss, db.UnsafeSQLError, db.QueryError, RuntimeError) as exc:
        st.error(str(exc))
    else:
        st.subheader("Generated SQL")
        st.code(out["sql"], language="sql")
        st.subheader("Results")
        df = out["result"].to_df()
        st.dataframe(df)
        st.caption(f"{len(df)} row(s)" + (" (truncated)" if out["result"].truncated else ""))
