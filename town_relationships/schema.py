import sqlite3

RELATIONSHIPS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_a_id INTEGER NOT NULL REFERENCES residents(id),
    resident_b_id INTEGER NOT NULL REFERENCES residents(id),
    relationship_type TEXT NOT NULL,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS shop_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    shop_building_id INTEGER NOT NULL REFERENCES buildings(id),
    purchase_count INTEGER NOT NULL,
    total_spent REAL NOT NULL,
    distance REAL NOT NULL,
    need_score REAL NOT NULL,
    customer_score REAL NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0
);
"""


def create_relationships_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(RELATIONSHIPS_SCHEMA_SQL)
