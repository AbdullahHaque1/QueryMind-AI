# Text-to-SQL Assistant

Ask a question in plain English, get an answer from a database. The app turns the question into a
**read-only SQL query**, runs it on a Spider benchmark database, and shows the SQL next to the results.

Runs free in demo mode; add `OPENAI_API_KEY` to `.env` to ask anything.

```
question + schema -> LLM -> SQL (SELECT only) -> safety check -> run on SQLite -> table
```

## Run in VS Code
1. **File → Open Folder…** and choose this folder (`text_to_sql_assistant`).
2. Open a terminal (**Ctrl+`**) and create an environment:
   - Windows: `python -m venv .venv` then `.venv\Scripts\activate`
   - macOS/Linux: `python -m venv .venv && source .venv/bin/activate`
3. Select the interpreter: **Ctrl+Shift+P → Python: Select Interpreter → .venv**.
4. `pip install -r requirements.txt`
5. (Optional) copy `.env.example` to `.env` and add your OpenAI key.
6. `python -m src.build_db`   # downloads Spider, copies the database, writes examples
7. `python demo.py`           # quick end-to-end check
8. `python -m src.cli`        # terminal interface
9. `streamlit run src/app.py` # web UI
10. `python -m src.evaluate`  # execution accuracy (needs an API key), saves results/*.json
11. `python -m tests.safety_eval`  # measures the four safety layers

You can also run any of these from **Run and Debug (Ctrl+Shift+D)** using the ready-made configurations.

## Structure
```
text_to_sql_assistant/
├── src/            config, build_db, db, nl2sql, cli, app, evaluate
├── examples/       examples.json (few-shot / demo)  dev.json (evaluation)   [generated]
├── data/           SQLite database                                          [generated, git-ignored]
├── tests/          test_guard.py (attacks the SQL safety guard)
├── demo.py         end-to-end check
├── requirements.txt  .env.example  .gitignore  Makefile  .vscode/
```

## Safety
Four layers: static SELECT-only validation, read-only SQLite connection, SQLite authorizer, row + time limits.

## Dataset
[Spider](https://yale-lily.github.io/spider) (Yu et al., 2018) - human-written questions + gold SQL over many databases.
Note: Spider assigns each database to one split. `concert_singer` is a dev-split database, so `build_db` divides its questions into an example pool and a held-out half.

If the automatic download fails, download `spider.zip` manually, unzip it into `data/spider/`, and re-run `python -m src.build_db`.

## Ideas to extend
Postgres support, an "explain this query" mode, sample rows in the prompt, multi-database routing, a leaderboard of models.
