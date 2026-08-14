import sqlite3

from town_db.generate import generate_town_database


def test_generate_town_database_creates_a_populated_db(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path)

    conn = sqlite3.connect(db_path)
    resident_count = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    building_count = conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0]
    purchase_count = conn.execute("SELECT COUNT(*) FROM purchases").fetchone()[0]
    tax_count = conn.execute("SELECT COUNT(*) FROM tax_payments").fetchone()[0]

    assert resident_count > 0
    assert building_count > 0
    assert purchase_count > 0
    assert tax_count > 0


def test_generate_town_database_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def test_generate_town_database_is_deterministic(tmp_path):
    db_path_1 = str(tmp_path / "town1.db")
    db_path_2 = str(tmp_path / "town2.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_1)
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_2)

    conn1 = sqlite3.connect(db_path_1)
    conn2 = sqlite3.connect(db_path_2)
    for table in ["residents", "buildings", "purchases", "tax_payments", "births", "deaths"]:
        rows1 = conn1.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        rows2 = conn2.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert rows1 == rows2


def test_generate_town_database_business_rules(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path)
    conn = sqlite3.connect(db_path)

    noble_head_tax = conn.execute(
        "SELECT COUNT(*) FROM tax_payments tp "
        "JOIN residents r ON r.id = tp.resident_id "
        "WHERE tp.tax_type = 'head_tax' AND r.is_noble = 1"
    ).fetchone()[0]
    assert noble_head_tax == 0

    military_without_garrison_job = conn.execute(
        "SELECT COUNT(*) FROM military_service ms "
        "JOIN residents r ON r.id = ms.resident_id "
        "WHERE r.occupation NOT IN ('soldier', 'guard')"
    ).fetchone()[0]
    assert military_without_garrison_job == 0

    plague_deaths_missing_event = conn.execute(
        "SELECT COUNT(*) FROM deaths WHERE cause = 'plague' AND disease_event_id IS NULL"
    ).fetchone()[0]
    assert plague_deaths_missing_event == 0

    duplicate_deaths = conn.execute(
        "SELECT resident_id, COUNT(*) c FROM deaths GROUP BY resident_id HAVING c > 1"
    ).fetchall()
    assert duplicate_deaths == []
