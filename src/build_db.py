"""Prepare the database and the example question->SQL pairs.

Usage:  python -m src.build_db
"""
import json
import random
import shutil 
import sqlite3
import zipfile

from . import config

SPIDER_DIR = config.DATA_DIR / "spider"
# Official Spider download (Google Drive). May change; manual download also works.
SPIDER_GDRIVE_ID = "1403EGqzIDoHMdQF4c9Bkyl7dZLZ5Wt6J"


# ───────────── Spider ─────────────
def download_spider() -> bool:
    """Try to download + unzip Spider. Returns True on success."""
    try:
        import gdown
        zip_path = config.DATA_DIR / "spider.zip"
        gdown.download(id=SPIDER_GDRIVE_ID, output=str(zip_path), quiet=False)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(SPIDER_DIR)
        return True
    except Exception as exc:                       # network, quota, bad zip ...
        print(f"[build_db] Could not download Spider automatically: {exc}")
        return False


def _not_macosx(path) -> bool:
    return "__MACOSX" not in path.parts


def find_spider():
    """Return (database_dir, train_json, dev_json) or None."""
    if not SPIDER_DIR.exists():
        return None
    dev = next((p for p in SPIDER_DIR.rglob("dev.json") if _not_macosx(p)), None)
    train = next((p for p in SPIDER_DIR.rglob("train_spider.json") if _not_macosx(p)), None)
    dbs = next((p for p in SPIDER_DIR.rglob("database") if p.is_dir() and _not_macosx(p)), None)
    return (dbs, train, dev) if dbs and train and dev else None


def pairs_for(json_path, db_name):
    rows = json.loads(json_path.read_text(encoding="utf-8"))
    return [{"question": r["question"], "sql": r["query"]}
            for r in rows if r["db_id"] == db_name]


def build_from_spider(found) -> None:
    dbs, train, dev = found
    src = dbs / config.DB_NAME / f"{config.DB_NAME}.sqlite"
    if not src.exists():
        raise SystemExit(f"Database '{config.DB_NAME}' not found in Spider ({dbs}).")
    shutil.copy(src, config.DB_PATH)
    train_pairs = pairs_for(train, config.DB_NAME)
    dev_pairs = pairs_for(dev, config.DB_NAME)
    if not train_pairs and dev_pairs:
        # Spider puts each database in exactly one split. Databases such as
        # concert_singer, pets_1 or world_1 live in the dev split, so the train
        # file has nothing for them. Split their dev questions into two disjoint
        # halves: one is the example pool, the other stays held out for evaluation.
        shuffled = dev_pairs[:]
        random.Random(42).shuffle(shuffled)
        half = max(1, len(shuffled) // 2)
        train_pairs, dev_pairs = shuffled[:half], shuffled[half:]
        print(f"[build_db] '{config.DB_NAME}' is a Spider dev-split database: "
              "its questions were split into example pool / held-out halves.")
    config.EXAMPLES_PATH.write_text(json.dumps(train_pairs, indent=2), encoding="utf-8")
    config.DEV_PATH.write_text(json.dumps(dev_pairs, indent=2), encoding="utf-8")
    print(f"[build_db] Spider DB '{config.DB_NAME}' ready: "
          f"{len(train_pairs)} train examples, {len(dev_pairs)} dev questions.")


# ───────────── Fallback: tiny e-commerce DB ─────────────
def build_fallback() -> None:
    print("[build_db] Spider not found -> building small fallback e-commerce database.")
    rnd = random.Random(42)
    config.DB_PATH.unlink(missing_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.executescript("""
    CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, city TEXT, country TEXT, signup_date TEXT);
    CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL);
    CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id),
                        order_date TEXT, status TEXT);
    CREATE TABLE order_items(id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id),
                             product_id INTEGER REFERENCES products(id), quantity INTEGER);
    """)
    cities = [("Colombo", "Sri Lanka"), ("Kandy", "Sri Lanka"), ("Delhi", "India"),
              ("Berlin", "Germany"), ("Austin", "USA"), ("Toronto", "Canada")]
    for i in range(1, 31):
        city, country = rnd.choice(cities)
        con.execute("INSERT INTO customers VALUES (?,?,?,?,?)",
                    (i, f"Customer {i}", city, country, f"2024-{rnd.randint(1,12):02d}-{rnd.randint(1,28):02d}"))
    cats = {"Electronics": ["Phone", "Laptop", "Headphones", "Camera"],
            "Books": ["Novel", "Cookbook", "Biography", "Textbook"],
            "Home": ["Lamp", "Chair", "Kettle", "Rug"]}
    pid = 1
    for cat, names in cats.items():
        for n in names:
            con.execute("INSERT INTO products VALUES (?,?,?,?)", (pid, n, cat, round(rnd.uniform(8, 900), 2)))
            pid += 1
    for oid in range(1, 81):
        con.execute("INSERT INTO orders VALUES (?,?,?,?)",
                    (oid, rnd.randint(1, 30), f"2025-{rnd.randint(1,12):02d}-{rnd.randint(1,28):02d}",
                     rnd.choice(["completed", "completed", "shipped", "cancelled", "pending"])))
    for iid in range(1, 201):
        con.execute("INSERT INTO order_items VALUES (?,?,?,?)",
                    (iid, rnd.randint(1, 80), rnd.randint(1, 12), rnd.randint(1, 5)))
    con.commit()
    con.close()

    examples = [
        {"question": "How many customers are there?", "sql": "SELECT COUNT(*) FROM customers"},
        {"question": "Orders per status", "sql": "SELECT status, COUNT(*) AS n FROM orders GROUP BY status"},
        {"question": "Total revenue by category",
         "sql": "SELECT p.category, ROUND(SUM(p.price*oi.quantity),2) AS revenue FROM order_items oi "
                "JOIN products p ON p.id=oi.product_id GROUP BY p.category ORDER BY revenue DESC"},
        {"question": "Top 3 customers by total spend",
         "sql": "SELECT c.name, ROUND(SUM(p.price*oi.quantity),2) AS spend FROM customers c "
                "JOIN orders o ON o.customer_id=c.id JOIN order_items oi ON oi.order_id=o.id "
                "JOIN products p ON p.id=oi.product_id GROUP BY c.id ORDER BY spend DESC LIMIT 3"},
        {"question": "Which 5 products earned the most revenue?",
         "sql": "SELECT p.name, ROUND(SUM(p.price*oi.quantity),2) AS revenue FROM order_items oi "
                "JOIN products p ON p.id=oi.product_id GROUP BY p.id ORDER BY revenue DESC LIMIT 5"},
    ]
    dev = [
        {"question": "How many orders were cancelled?", "sql": "SELECT COUNT(*) FROM orders WHERE status = 'cancelled'"},
        {"question": "List the names of products in the Books category",
         "sql": "SELECT name FROM products WHERE category = 'Books'"},
    ]
    config.EXAMPLES_PATH.write_text(json.dumps(examples, indent=2), encoding="utf-8")
    config.DEV_PATH.write_text(json.dumps(dev, indent=2), encoding="utf-8")


def main() -> None:
    config.DATA_DIR.mkdir(exist_ok=True)
    config.EXAMPLES_DIR.mkdir(exist_ok=True)
    found = find_spider()
    if not found:
        print("[build_db] Spider not on disk, trying to download ...")
        if download_spider():
            found = find_spider()
    if found:
        build_from_spider(found)
    else:
        build_fallback()


if __name__ == "__main__":
    main()
