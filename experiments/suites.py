"""Hand-written test material for the offline experiments.
All queries target the bundled e-commerce database (src.build_db fallback, seed 42):
  customers(id, name, city, country, signup_date)   products(id, name, category, price)
  orders(id, customer_id, order_date, status)       order_items(id, order_id, product_id, quantity)
"""

# (category, sql) - every one of these should be refused or neutralised.
ATTACKS = [
    # stacked statements
    ("stacked", "SELECT 1; DROP TABLE orders"),
    ("stacked", "SELECT * FROM orders; DELETE FROM orders"),
    ("stacked", "SELECT 1;\n\nUPDATE orders SET status = 'x'"),
    ("stacked", "SELECT 1 /**/ ; /**/ DROP TABLE products"),
    ("stacked", "SELECT 1; INSERT INTO customers(id, name) VALUES (500, 'x')"),
    # schema changes
    ("ddl", "DROP TABLE orders"),
    ("ddl", "DROP TABLE IF EXISTS customers"),
    ("ddl", "CREATE TABLE scratch(a INTEGER)"),
    ("ddl", "ALTER TABLE orders ADD COLUMN flag INTEGER"),
    ("ddl", "CREATE INDEX ix_status ON orders(status)"),
    # plain data changes
    ("dml", "DELETE FROM orders"),
    ("dml", "UPDATE orders SET status = 'cancelled'"),
    ("dml", "INSERT INTO customers(id, name) VALUES (501, 'mallory')"),
    ("dml", "REPLACE INTO products(id, name, category, price) VALUES (1, 'x', 'x', 0)"),
    ("dml", "INSERT OR REPLACE INTO products(id, name, category, price) VALUES (2, 'x', 'x', 0)"),
    # write statements hidden behind a WITH clause
    ("cte-write", "WITH x AS (SELECT 1) DELETE FROM orders"),
    ("cte-write", "WITH x AS (SELECT 1 AS a) INSERT INTO customers(id) SELECT a + 900 FROM x"),
    ("cte-write", "WITH x AS (SELECT 1) UPDATE orders SET status = 'y'"),
    ("cte-write", "WITH x AS (SELECT 77 AS id, 'zz' AS name, 'Books' AS category, 1.0 AS price) "
                  "REPLACE INTO products(id, name, category, price) SELECT id, name, category, price FROM x"),
    ("cte-write", "WITH x AS (SELECT 1 AS id, 'zz' AS name, 'Books' AS category, 1.0 AS price) "
                  "REPLACE INTO products(id, name, category, price) SELECT id, name, category, price FROM x"),
    # administrative statements
    ("admin", "PRAGMA writable_schema = 1"),
    ("admin", "PRAGMA user_version = 7"),
    ("admin", "PRAGMA table_info(orders)"),
    ("admin", "VACUUM"),
    ("admin", "REINDEX"),
    ("admin", "ATTACH DATABASE ':memory:' AS m"),
    ("admin", "ATTACH DATABASE 'evil.db' AS e"),
    ("admin", "DETACH DATABASE main"),
    ("admin", "EXPLAIN DELETE FROM orders"),
    # transaction control
    ("transaction", "BEGIN; DELETE FROM orders; COMMIT"),
    ("transaction", "COMMIT"),
    ("transaction", "SAVEPOINT s1"),
    # spelling tricks
    ("obfuscation", "dRoP tAbLe orders"),
    ("obfuscation", "  /* note */ DELETE /* more */ FROM orders"),
    ("obfuscation", "-- harmless\nDELETE FROM orders"),
    ("obfuscation", "SELECT 1 -- ;\n; DROP TABLE orders"),
    # strings and quoted names used to hide code from a naive scan
    ("quote-trick", "WITH x AS (SELECT 1 AS [a']) DELETE FROM orders RETURNING id AS [']"),
    ("quote-trick", "WITH x AS (SELECT 1 AS `a'`) DELETE FROM orders RETURNING id AS `'`"),
    ("quote-trick", "WITH x AS (SELECT 1 AS [a']) UPDATE orders SET status = 'hacked' RETURNING id AS [']"),
    ("quote-trick", "SELECT [x'] FROM orders; DROP TABLE orders; SELECT ['] FROM orders"),
    # dangerous functions
    ("function", "SELECT load_extension('libevil')"),
    ("function", "SELECT readfile('/etc/passwd')"),
]

# (category, sql) - every one of these is a legitimate read-only question.
BENIGN = [
    ("basic", "SELECT COUNT(*) FROM customers"),
    ("basic", "SELECT name, country FROM customers WHERE country = 'India' ORDER BY name"),
    ("basic", "select max(price), min(price) from products"),
    ("basic", "SELECT COUNT(*) FROM orders;"),
    ("basic", "SELECT signup_date FROM customers WHERE signup_date >= '2024-06-01'"),
    ("aggregate", "SELECT status, COUNT(*) AS n FROM orders GROUP BY status"),
    ("aggregate", "SELECT p.category, ROUND(SUM(p.price*oi.quantity),2) AS revenue FROM order_items oi "
                  "JOIN products p ON p.id = oi.product_id GROUP BY p.category"),
    ("aggregate", "SELECT substr(order_date, 1, 7) AS month, COUNT(*) FROM orders GROUP BY month ORDER BY month"),
    ("aggregate", "SELECT CASE WHEN price > 100 THEN 'high' ELSE 'low' END AS band, COUNT(*) FROM products GROUP BY band"),
    ("join", "SELECT o.id, c.name, SUM(p.price*oi.quantity) AS total FROM orders o "
             "JOIN customers c ON c.id = o.customer_id JOIN order_items oi ON oi.order_id = o.id "
             "JOIN products p ON p.id = oi.product_id GROUP BY o.id ORDER BY total DESC LIMIT 10"),
    ("subquery", "SELECT name FROM products WHERE price > (SELECT AVG(price) FROM products)"),
    ("subquery", "SELECT c.name FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)"),
    ("cte", "WITH big AS (SELECT order_id, SUM(quantity) AS q FROM order_items GROUP BY order_id) "
            "SELECT COUNT(*) FROM big WHERE q > 5"),
    ("cte", "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i < 10) SELECT SUM(i) FROM n"),
    ("window", "SELECT name, price, RANK() OVER (PARTITION BY category ORDER BY price DESC) AS rk FROM products"),
    ("set-op", "SELECT name FROM customers UNION SELECT name FROM products"),
    ("set-op", "SELECT category FROM products EXCEPT SELECT category FROM products WHERE price < 50"),
    ("function", "SELECT replace(name, 'Customer', 'C') FROM customers LIMIT 5"),
    ("function", "SELECT date('2025-03-01', '+1 month')"),
    ("metadata", "SELECT sql FROM sqlite_master WHERE type = 'table'"),
    # words that look dangerous but sit inside literals
    ("in-literal", "SELECT * FROM orders WHERE status = 'drop'"),
    ("in-literal", "SELECT 'update; delete' AS note"),
    ("in-literal", "SELECT * FROM products WHERE name LIKE '%--%'"),
    ("in-literal", "SELECT * FROM products WHERE name LIKE '%/*%'"),
    # comments and alternative quoting
    ("syntax", "SELECT name FROM products -- trailing comment"),
    ("syntax", "SELECT name /* inline */ FROM products"),
    ("syntax", 'SELECT "name" FROM "products" LIMIT 3'),
    ("syntax", "SELECT [name] FROM products LIMIT 3"),
    ("syntax", "SELECT `name` FROM products LIMIT 3"),
    ("syntax", 'SELECT name AS "create" FROM products LIMIT 3'),
    ("syntax", "SELECT name AS update_date FROM products LIMIT 3"),
    # unquoted identifiers that collide with blocked words (known weak spot)
    ("collision", "SELECT name AS release FROM products LIMIT 3"),
    ("collision", "SELECT 1 AS begin"),
]

# Question bank for the demo-mode matcher experiment: (question, gold SQL).
BANK = [
    ("How many customers are there?", "SELECT COUNT(*) FROM customers"),
    ("Orders per status", "SELECT status, COUNT(*) AS n FROM orders GROUP BY status"),
    ("Total revenue by category",
     "SELECT p.category, ROUND(SUM(p.price*oi.quantity),2) AS revenue FROM order_items oi "
     "JOIN products p ON p.id=oi.product_id GROUP BY p.category ORDER BY revenue DESC"),
    ("Top 3 customers by total spend",
     "SELECT c.name, ROUND(SUM(p.price*oi.quantity),2) AS spend FROM customers c "
     "JOIN orders o ON o.customer_id=c.id JOIN order_items oi ON oi.order_id=o.id "
     "JOIN products p ON p.id=oi.product_id GROUP BY c.id ORDER BY spend DESC LIMIT 3"),
    ("Which 5 products earned the most revenue?",
     "SELECT p.name, ROUND(SUM(p.price*oi.quantity),2) AS revenue FROM order_items oi "
     "JOIN products p ON p.id=oi.product_id GROUP BY p.id ORDER BY revenue DESC LIMIT 5"),
    ("List all customers from Sri Lanka", "SELECT name FROM customers WHERE country = 'Sri Lanka'"),
    ("What is the average product price?", "SELECT ROUND(AVG(price), 2) FROM products"),
    ("How many orders were placed in 2025?", "SELECT COUNT(*) FROM orders WHERE order_date LIKE '2025-%'"),
    ("Show the most expensive product", "SELECT name, price FROM products ORDER BY price DESC LIMIT 1"),
    ("Number of customers per country", "SELECT country, COUNT(*) AS n FROM customers GROUP BY country"),
    ("Which customers have never placed an order?",
     "SELECT name FROM customers WHERE id NOT IN (SELECT customer_id FROM orders)"),
    ("What is the total quantity sold for each product category?",
     "SELECT p.category, SUM(oi.quantity) FROM order_items oi JOIN products p ON p.id=oi.product_id GROUP BY p.category"),
]

# Rewordings of each bank question: (bank index, difficulty, text)
PARAPHRASES = [
    (0, "easy", "How many customers do we have?"),
    (0, "medium", "Count the customers"),
    (0, "hard", "What is the size of our customer base?"),
    (1, "easy", "How many orders per status?"),
    (1, "medium", "Number of orders for every status"),
    (1, "hard", "Break the orders down by their state"),
    (2, "easy", "Total revenue per category"),
    (2, "medium", "Revenue for each product category in total"),
    (2, "hard", "How much money did each type of product bring in?"),
    (3, "easy", "Top 3 customers by spend"),
    (3, "medium", "The three customers who spent the most"),
    (3, "hard", "Who are our biggest three buyers?"),
    (4, "easy", "Which five products earned the most revenue?"),
    (4, "medium", "Top 5 products by revenue"),
    (4, "hard", "Name the best-selling five items in terms of money made"),
    (5, "easy", "Which customers are from Sri Lanka?"),
    (5, "medium", "Customers living in Sri Lanka"),
    (5, "hard", "Give me the people who signed up from Sri Lanka"),
    (6, "easy", "What is the average price of a product?"),
    (6, "medium", "Average product price"),
    (6, "hard", "On average, how expensive are our items?"),
    (7, "easy", "How many orders were made in 2025?"),
    (7, "medium", "Orders placed during 2025, how many"),
    (7, "hard", "How busy was 2025 in terms of purchases?"),
    (8, "easy", "Show me the most expensive product"),
    (8, "medium", "Which product has the highest price?"),
    (8, "hard", "What is the priciest thing we sell?"),
    (9, "easy", "How many customers are there per country?"),
    (9, "medium", "Customer count by country"),
    (9, "hard", "Where do our customers come from, and how many from each place?"),
    (10, "easy", "Which customers never placed an order?"),
    (10, "medium", "Customers without any orders"),
    (10, "hard", "Who signed up but has never bought anything?"),
    (11, "easy", "What is the total quantity sold in each product category?"),
    (11, "medium", "Quantity sold per category"),
    (11, "hard", "How many units left the shop for every kind of product?"),
]

# Questions the matcher should refuse (not in the bank).
OUT_OF_SCOPE = [
    ("near", "How many orders were cancelled?"),
    ("near", "List the names of products in the Books category"),
    ("near", "Which city has the most customers?"),
    ("near", "What is the cheapest product in each category?"),
    ("near", "Show orders placed by customer 12"),
    ("near", "How many products are there in total?"),
    ("off-topic", "What is the meaning of life?"),
    ("off-topic", "Write me a poem about autumn"),
    ("off-topic", "Who won the cricket match yesterday?"),
    ("off-topic", "Translate good morning into French"),
    ("off-topic", "How do I reset my router?"),
    ("off-topic", "Tell me a joke"),
]

# Evaluator self-check: (sql_a, sql_b, should_match)
EVAL_PAIRS = [
    ("SELECT COUNT(*) FROM customers", "SELECT COUNT(id) FROM customers", True),
    ("SELECT name FROM customers WHERE country='India'", "SELECT c.name FROM customers AS c WHERE c.country = 'India'", True),
    ("SELECT name FROM products ORDER BY price", "SELECT name FROM products", True),
    ("SELECT status, COUNT(*) FROM orders GROUP BY status", "SELECT status, COUNT(1) FROM orders GROUP BY 1", True),
    ("SELECT DISTINCT category FROM products", "SELECT category FROM products GROUP BY category", True),
    ("SELECT ROUND(AVG(price),2) FROM products", "SELECT ROUND(SUM(price)/COUNT(*),2) FROM products", True),
    ("SELECT name FROM customers WHERE id NOT IN (SELECT customer_id FROM orders)",
     "SELECT name FROM customers c WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)", True),
    ("SELECT name FROM products WHERE price BETWEEN 10 AND 100", "SELECT name FROM products WHERE price >= 10 AND price <= 100", True),
    ("SELECT id FROM orders WHERE status IN ('shipped','pending')", "SELECT id FROM orders WHERE status='shipped' OR status='pending'", True),
    ("SELECT MAX(price) FROM products", "SELECT price FROM products ORDER BY price DESC LIMIT 1", True),
    ("SELECT country FROM customers UNION SELECT country FROM customers", "SELECT DISTINCT country FROM customers", True),
    ("SELECT COUNT(*) FROM orders", "SELECT COUNT(*) FROM orders WHERE status IS NOT NULL", True),
    ("SELECT COUNT(*) FROM customers", "SELECT COUNT(*) FROM products", False),
    ("SELECT name FROM customers WHERE country='India'", "SELECT name FROM customers WHERE country='USA'", False),
    ("SELECT category FROM products", "SELECT DISTINCT category FROM products", False),
    ("SELECT name FROM products ORDER BY price DESC LIMIT 3", "SELECT name FROM products ORDER BY price ASC LIMIT 3", False),
    ("SELECT status, COUNT(*) FROM orders GROUP BY status", "SELECT status, SUM(1) + 1 FROM orders GROUP BY status", False),
    ("SELECT ROUND(AVG(price),2) FROM products", "SELECT ROUND(MAX(price),2) FROM products", False),
    ("SELECT id FROM orders WHERE status='shipped'", "SELECT id FROM orders WHERE status='completed'", False),
    ("SELECT name FROM customers", "SELECT name FROM customers LIMIT 10", False),
    ("SELECT SUM(quantity) FROM order_items", "SELECT COUNT(quantity) FROM order_items", False),
    ("SELECT price FROM products", "SELECT price + 0.00001 FROM products", False),
    ("SELECT city, country FROM customers", "SELECT country, city FROM customers", False),
    ("SELECT name FROM customers WHERE id <= 10", "SELECT name FROM customers WHERE id < 10", False),
]
