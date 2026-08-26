# tests/test_db_stats.py
from town_db.schema import connect, create_schema
from town_db.stats import compute_stress


def _insert_resident(conn, resident_id, ses, household_id=1):
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (?, ?, 'A', 'B', 'male', 'human', '1280-01-01', ?)",
        (resident_id, household_id, ses),
    )


def _setup_db(db_path, poor_count, rich_count):
    conn = connect(db_path)
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    for i in range(poor_count):
        _insert_resident(conn, i + 1, "poor")
    for i in range(rich_count):
        _insert_resident(conn, poor_count + i + 1, "rich")
    conn.commit()
    conn.close()


def test_compute_stress_returns_zero_for_empty_database(tmp_path):
    db_path = str(tmp_path / "empty.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.commit()
    conn.close()
    assert compute_stress(db_path) == 0.0


def test_compute_stress_increases_with_higher_poor_fraction(tmp_path):
    low_poor_path = str(tmp_path / "low_poor.db")
    high_poor_path = str(tmp_path / "high_poor.db")
    _setup_db(low_poor_path, poor_count=10, rich_count=90)
    _setup_db(high_poor_path, poor_count=90, rich_count=10)
    assert compute_stress(high_poor_path) > compute_stress(low_poor_path)


def test_compute_stress_increases_with_more_skirmish_events(tmp_path):
    db_path = str(tmp_path / "town.db")
    _setup_db(db_path, poor_count=50, rich_count=50)
    baseline = compute_stress(db_path)

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
        ("a clash", "1300-06-01", 0.8),
    )
    conn.commit()
    conn.close()
    assert compute_stress(db_path) > baseline


def test_compute_stress_is_clamped_at_one(tmp_path):
    db_path = str(tmp_path / "town.db")
    _setup_db(db_path, poor_count=100, rich_count=0)
    conn = connect(db_path)
    for _ in range(20):
        conn.execute(
            "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
            ("a clash", "1300-06-01", 1.0),
        )
    conn.commit()
    conn.close()
    assert compute_stress(db_path) == 1.0
