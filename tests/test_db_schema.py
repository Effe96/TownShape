import sqlite3

from town_db.schema import connect, create_schema

EXPECTED_TABLES = {
    "districts", "buildings", "households", "residents", "goods",
    "purchases", "tax_payments", "disease_events", "illnesses", "births", "deaths",
    "school_enrollments", "military_service", "generation_parameters",
    "water_features", "skirmish_events", "town_state", "road_nodes", "road_edges",
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
        "density_multiplier, rich_proportion, num_rivers, has_coastline, has_port, magic_prevalence, aggression) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("('town', 1)", 1500, 1.0, 1.0, 0.05, 1, 1, 1, 0.3, 0.2),
    )
    conn.commit()
    row = conn.execute(
        "SELECT seed, target_population, area_per_resident_multiplier, density_multiplier, rich_proportion, "
        "num_rivers, has_coastline, has_port, magic_prevalence, aggression FROM generation_parameters"
    ).fetchone()
    assert row == ("('town', 1)", 1500, 1.0, 1.0, 0.05, 1, 1, 1, 0.3, 0.2)


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


def test_residents_has_magical_talent_defaults_to_zero(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (1, 'Ann', 'Smith', 'female', 'human', '1280-01-01', 'poor')"
    )
    row = conn.execute("SELECT has_magical_talent FROM residents").fetchone()
    assert row[0] == 0


def test_residents_has_magical_talent_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, ses, has_magical_talent) "
        "VALUES (1, 'Ann', 'Smith', 'female', 'human', '1280-01-01', 'poor', 1)"
    )
    row = conn.execute("SELECT has_magical_talent FROM residents").fetchone()
    assert row[0] == 1


def test_skirmish_events_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    cursor = conn.execute(
        "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
        ("a clash between the poor quarter and the city guard", "1300-05-01", 0.7),
    )
    conn.commit()
    row = conn.execute(
        "SELECT name, skirmish_date, severity FROM skirmish_events WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    assert row == ("a clash between the poor quarter and the city guard", "1300-05-01", 0.7)


def test_deaths_skirmish_event_id_defaults_to_null(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'guard_post', 0.0, 0.0, 0)"
    )
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (1, 'Ann', 'Smith', 'female', 'human', '1280-01-01', 'poor')"
    )
    conn.execute(
        "INSERT INTO deaths (resident_id, death_date, cause, reported_by_building_id) VALUES (1, '1300-01-01', 'illness', 1)"
    )
    row = conn.execute("SELECT skirmish_event_id FROM deaths WHERE resident_id = 1").fetchone()
    assert row[0] is None


def test_deaths_skirmish_event_id_accepts_a_value(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'guard_post', 0.0, 0.0, 0)"
    )
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (1, 'Ann', 'Smith', 'female', 'human', '1280-01-01', 'poor')"
    )
    cursor = conn.execute(
        "INSERT INTO skirmish_events (name, skirmish_date, severity) VALUES (?, ?, ?)",
        ("a clash", "1300-05-01", 0.5),
    )
    skirmish_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO deaths (resident_id, death_date, cause, skirmish_event_id, reported_by_building_id) "
        "VALUES (1, '1300-05-01', 'skirmish', ?, 1)",
        (skirmish_id,),
    )
    row = conn.execute("SELECT skirmish_event_id FROM deaths WHERE resident_id = 1").fetchone()
    assert row[0] == skirmish_id


def test_town_state_accepts_a_row(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) "
        "VALUES (1, ?, ?, ?, ?)",
        ("1300-01-01", "1301-01-01", 0.2, 0.1),
    )
    conn.commit()
    # NOTE: `current_date` is a SQLite keyword (CURRENT_DATE); a bare reference to it in a
    # result-column list evaluates to today's date, not this column. Every *read* of this
    # column must quote the identifier. Writes (INSERT column list, UPDATE SET) are unaffected.
    row = conn.execute(
        'SELECT year_start, "current_date", aggression, magic_prevalence FROM town_state WHERE id = 1'
    ).fetchone()
    assert row == ("1300-01-01", "1301-01-01", 0.2, 0.1)


def test_town_state_enforces_singleton(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) "
        "VALUES (1, '1300-01-01', '1301-01-01', 0.0, 0.0)"
    )
    conn.commit()
    try:
        conn.execute(
            "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) "
            "VALUES (2, '1300-01-01', '1301-01-01', 0.0, 0.0)"
        )
        assert False, "expected a CHECK constraint violation"
    except sqlite3.IntegrityError:
        pass


def test_illnesses_table_accepts_a_row_referencing_a_resident_and_disease_event(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (1, 1, 'A', 'B', 'male', 'human', '1280-01-01', 'poor')"
    )
    conn.execute(
        "INSERT INTO disease_events (id, name, start_date, end_date, affected_zone_type, severity) "
        "VALUES (1, 'fever', '1300-01-01', '1300-02-01', NULL, 0.5)"
    )
    conn.execute(
        "INSERT INTO illnesses (resident_id, disease_event_id, start_date, end_date, severity) "
        "VALUES (1, 1, '1300-01-05', '1300-01-20', 0.5)"
    )
    conn.commit()

    row = conn.execute("SELECT resident_id, disease_event_id, start_date, end_date, severity FROM illnesses").fetchone()
    assert row == (1, 1, "1300-01-05", "1300-01-20", 0.5)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_households_wealth_defaults_to_zero(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.commit()
    row = conn.execute("SELECT wealth FROM households WHERE id = 1").fetchone()
    assert row == (0.0,)


def test_households_wealth_accepts_an_explicit_value(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute(
        "INSERT INTO households (id, family_name, race, wealth) VALUES (1, 'Smith', 'human', 250.5)"
    )
    conn.commit()
    row = conn.execute("SELECT wealth FROM households WHERE id = 1").fetchone()
    assert row == (250.5,)


def test_generate_town_database_persists_road_network(tmp_path):
    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)

    conn = connect(db_path)
    node_rows = conn.execute("SELECT id, kind, anchor_id, is_hub, x, y FROM road_nodes").fetchall()
    edge_rows = conn.execute("SELECT id, from_node_id, to_node_id, road_type FROM road_edges").fetchall()
    conn.close()

    assert len(node_rows) > 0
    assert len(edge_rows) > 0
    assert sum(1 for row in node_rows if row[3] == 1) == 1  # exactly one is_hub row
    node_ids = {row[0] for row in node_rows}
    for edge in edge_rows:
        assert edge[1] in node_ids
        assert edge[2] in node_ids
        assert edge[3] in ("artery", "boundary", "spur")


def test_generate_town_database_persists_building_footprints(tmp_path):
    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)

    conn = connect(db_path)
    rows = conn.execute("SELECT width, height, rotation FROM buildings").fetchall()
    conn.close()

    assert len(rows) > 0
    assert all(row[0] > 0 and row[1] > 0 for row in rows)


def test_buildings_footprint_defaults_to_null(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'temple', 0.0, 0.0, 0)"
    )
    row = conn.execute("SELECT footprint FROM buildings WHERE id = 1").fetchone()
    assert row[0] is None


def test_buildings_footprint_accepts_a_json_polygon(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, footprint) "
        "VALUES (1, 1, 'civic', 'temple', 0.0, 0.0, 0, ?)",
        ('[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]',),
    )
    row = conn.execute("SELECT footprint FROM buildings WHERE id = 1").fetchone()
    assert row[0] == '[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]'


def test_generate_town_database_persists_building_footprint_polygons(tmp_path):
    import json

    from town_db.generate import generate_town_database

    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)

    conn = connect(db_path)
    rows = conn.execute(
        "SELECT footprint FROM buildings WHERE zone_type != 'farmland_edge'"
    ).fetchall()
    conn.close()

    assert len(rows) > 0
    # Not populated with real geometry until Task 6/7 wire it in -- for now
    # this just proves the column round-trips NULL cleanly end-to-end.
    assert all(row[0] is None for row in rows)
