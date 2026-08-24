import sqlite3

from town_db.schema import connect, create_schema

from town_relationships.schema import create_relationships_schema

EXPECTED_TABLES = {"relationships", "shop_relationships"}


def test_create_relationships_schema_creates_both_tables(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    create_relationships_schema(conn)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {row[0] for row in rows}
    assert EXPECTED_TABLES <= table_names


def test_relationships_foreign_keys_are_enforced(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    create_relationships_schema(conn)
    try:
        conn.execute(
            "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type) VALUES (1, 2, 'coworker')"
        )
        conn.commit()
        assert False, "expected a foreign key violation"
    except sqlite3.IntegrityError:
        pass


def test_shop_relationships_foreign_keys_are_enforced(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    create_relationships_schema(conn)
    try:
        conn.execute(
            "INSERT INTO shop_relationships (resident_id, shop_building_id, purchase_count, total_spent, "
            "distance, need_score, customer_score) VALUES (1, 1, 0, 0.0, 0.0, 0.0, 0.0)"
        )
        conn.commit()
        assert False, "expected a foreign key violation"
    except sqlite3.IntegrityError:
        pass
