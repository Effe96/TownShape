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


def test_generate_town_database_plausibility_bounds(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)
    conn = sqlite3.connect(db_path)

    resident_count = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    birth_count = conn.execute("SELECT COUNT(*) FROM births").fetchone()[0]
    death_count = conn.execute("SELECT COUNT(*) FROM deaths").fetchone()[0]

    # Real pre-industrial crude rates sit around 30-40 per 1000; the band below
    # is deliberately wide enough to absorb per-seed variance and the odd
    # disease year, but tight enough to catch an order-of-magnitude regression
    # (the original 11/1000 birth rate would have failed this).
    births_per_1000 = birth_count / resident_count * 1000
    deaths_per_1000 = death_count / resident_count * 1000
    assert 15 <= births_per_1000 <= 55, f"births/1000={births_per_1000}"
    assert 10 <= deaths_per_1000 <= 60, f"deaths/1000={deaths_per_1000}"

    # The spec explicitly requires "bread constantly, jewelry rarely" -- assert
    # the SV-weighting direction produces that outcome, not its inverse.
    bread_count = conn.execute(
        "SELECT COUNT(*) FROM purchases p JOIN goods g ON g.id = p.good_id WHERE g.name = 'bread'"
    ).fetchone()[0]
    jewelry_count = conn.execute(
        "SELECT COUNT(*) FROM purchases p JOIN goods g ON g.id = p.good_id WHERE g.name = 'jewelry'"
    ).fetchone()[0]
    assert bread_count > jewelry_count, f"bread={bread_count}, jewelry={jewelry_count}"


def test_no_purchase_or_tax_payment_postdates_the_residents_death(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)
    conn = sqlite3.connect(db_path)

    posthumous_purchases = conn.execute(
        "SELECT COUNT(*) FROM purchases p JOIN residents r ON r.id = p.resident_id "
        "WHERE r.death_date IS NOT NULL AND p.purchase_date > r.death_date"
    ).fetchone()[0]
    assert posthumous_purchases == 0

    posthumous_taxes = conn.execute(
        "SELECT COUNT(*) FROM tax_payments t JOIN residents r ON r.id = t.resident_id "
        "WHERE r.death_date IS NOT NULL AND t.payment_date > r.death_date"
    ).fetchone()[0]
    assert posthumous_taxes == 0


def test_vital_record_causes_and_parents_are_biologically_possible(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)
    conn = sqlite3.connect(db_path)

    impossible_childbirth_deaths = conn.execute(
        "SELECT COUNT(*) FROM deaths d JOIN residents r ON r.id = d.resident_id "
        "WHERE d.cause = 'childbirth' AND r.gender != 'female'"
    ).fetchone()[0]
    assert impossible_childbirth_deaths == 0

    female_fathers = conn.execute(
        "SELECT COUNT(*) FROM births b JOIN residents r ON r.id = b.father_resident_id "
        "WHERE r.gender != 'male'"
    ).fetchone()[0]
    assert female_fathers == 0

    non_female_mothers = conn.execute(
        "SELECT COUNT(*) FROM births b JOIN residents r ON r.id = b.mother_resident_id "
        "WHERE r.gender != 'female'"
    ).fetchone()[0]
    assert non_female_mothers == 0
