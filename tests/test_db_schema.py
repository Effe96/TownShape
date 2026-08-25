import sqlite3

from town_db.schema import connect, create_schema

EXPECTED_TABLES = {
    "districts", "buildings", "households", "residents", "goods",
    "purchases", "tax_payments", "disease_events", "births", "deaths",
    "school_enrollments", "military_service", "generation_parameters",
    "water_features",
}


def test_create_schema_creates_every_table(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {row[0] for row in rows}
    assert EXPECTED_TABLES <= table_names


def test_connect_enables_foreign_keys(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    result = conn.execute("PRAGMA foreign_keys").fetchone()
    assert result[0] == 1


def test_residents_id_is_autoincrement_but_buildings_id_is_not(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (5, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (42, 5, 'civic', 'temple', 1.0, 2.0, 0)"
    )
    row = conn.execute("SELECT id FROM buildings WHERE id = 42").fetchone()
    assert row[0] == 42

    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    cursor = conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, "
        "ses, is_noble) VALUES (1, 'Ann', 'Smith', 'female', 'human', '1280-01-01', 'poor', 0)"
    )
    first_id = cursor.lastrowid
    cursor2 = conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, "
        "ses, is_noble) VALUES (1, 'Bob', 'Smith', 'male', 'human', '1275-01-01', 'poor', 0)"
    )
    assert cursor2.lastrowid == first_id + 1


def test_foreign_key_violation_is_rejected(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    try:
        conn.execute(
            "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
            "VALUES (1, 999, 'civic', 'temple', 0.0, 0.0, 0)"
        )
        conn.commit()
        assert False, "expected a foreign key violation"
    except sqlite3.IntegrityError:
        pass


def test_generation_parameters_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO generation_parameters (seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion, num_rivers, has_coastline, has_port) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("('town', 1)", 1500, 1.0, 1.0, 0.05, 1, 1, 1),
    )
    conn.commit()
    row = conn.execute(
        "SELECT seed, target_population, area_per_resident_multiplier, density_multiplier, rich_proportion, "
        "num_rivers, has_coastline, has_port FROM generation_parameters"
    ).fetchone()
    assert row == ("('town', 1)", 1500, 1.0, 1.0, 0.05, 1, 1, 1)


def test_water_features_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO water_features (id, kind, polygon) VALUES (?, ?, ?)",
        (1, "river", "[[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]]"),
    )
    conn.commit()
    row = conn.execute("SELECT id, kind, polygon FROM water_features").fetchone()
    assert row == (1, "river", "[[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]]")
