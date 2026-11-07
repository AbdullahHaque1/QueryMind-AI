"""Quick end-to-end check (the notebook's demo cells).   Run:  python demo.py"""
from src import config, db, nl2sql

print("Mode:", config.default_mode())
print("\n--- Schema (first 1500 chars) ---")
print(db.get_schema()[:1500])

examples = nl2sql.load_examples()
print(f"\n--- {len(examples)} curated examples loaded. First three ---")
for e in examples[:3]:
    print(" •", e["question"])

q = examples[0]["question"]
out = nl2sql.answer(q, mode="demo")
print("\nQuestion:", q)
print("SQL     :", out["sql"])
print(out["result"].to_df().head(10).to_string(index=False))

print("\n--- A question demo mode doesn't know ---")
try:
    nl2sql.answer("What is the meaning of life?", mode="demo")
except nl2sql.DemoMiss as e:
    print(e)
