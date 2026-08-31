from town_db.schema import connect, create_schema

from town_relationships.generate import derive_relationships


def _build_minimal_town(db_path):
    conn = connect(db_path)
    create_schema(conn)

    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'residential', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'residential', 'house', 0.0, 0.0, 6)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (2, 1, 'residential', 'house', 1.0, 0.0, 6)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (10, 1, 'commercial', 'shop', 3.0, 4.0, 0)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (20, 1, 'civic', 'garrison', 0.0, 0.0, 0)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (21, 1, 'civic', 'school', 0.0, 0.0, 0)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (30, 1, 'commercial', 'workshop', 2.0, 2.0, 0)"
    )

    conn.execute("INSERT INTO households (id, family_name, race) VALUES (100, 'Smith', 'human')")
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (200, 'Baker', 'human')")

    def resident(household_id, first_name, gender, birth_date, ses, home_building_id, workplace_building_id, occupation):
        cursor = conn.execute(
            "INSERT INTO residents (household_id, first_name, last_name, gender, race, birth_date, ses, "
            "is_noble, home_building_id, workplace_building_id, occupation) "
            "VALUES (?, ?, 'Smith', ?, 'human', ?, ?, 0, ?, ?, ?)",
            (household_id, first_name, gender, birth_date, ses, home_building_id, workplace_building_id, occupation),
        )
        return cursor.lastrowid

    father = resident(100, "Tom", "male", "1260-01-01", "poor", 1, 30, "smith")
    mother = resident(100, "Ann", "female", "1262-01-01", "poor", 1, None, None)
    child = resident(100, "Lil", "female", "1295-01-01", "poor", 1, None, None)
    neighbor = resident(200, "Bob", "male", "1265-01-01", "poor", 2, 30, "mason")

    conn.execute(
        "INSERT INTO births (child_resident_id, mother_resident_id, father_resident_id, birth_date, "
        "reported_by_building_id) VALUES (?, ?, ?, '1295-01-01', 20)",
        (child, mother, father),
    )

    good_id = conn.execute(
        "INSERT INTO goods (name, category, typical_price, sv) VALUES ('bread', 'food', 0.05, 800)"
    ).lastrowid
    conn.execute(
        "INSERT INTO purchases (resident_id, shop_building_id, good_id, quantity, unit_price, total_price, "
        "purchase_date) VALUES (?, 10, ?, 2, 0.05, 0.10, '1300-02-01')",
        (father, good_id),
    )

    conn.execute(
        "INSERT INTO military_service (resident_id, garrison_building_id, rank, start_date, end_date) "
        "VALUES (?, 20, 'soldier', '1300-01-01', NULL)",
        (father,),
    )
    conn.execute(
        "INSERT INTO military_service (resident_id, garrison_building_id, rank, start_date, end_date) "
        "VALUES (?, 20, 'soldier', '1300-02-01', NULL)",
        (neighbor,),
    )

    conn.execute(
        "INSERT INTO school_enrollments (resident_id, school_building_id, enrollment_type, start_date, end_date) "
        "VALUES (?, 21, 'student', '1300-01-01', NULL)",
        (child,),
    )
    conn.execute(
        "INSERT INTO school_enrollments (resident_id, school_building_id, enrollment_type, start_date, end_date) "
        "VALUES (?, 21, 'student', '1300-01-15', NULL)",
        (neighbor,),
    )

    conn.commit()
    conn.close()
    return {"father": father, "mother": mother, "child": child, "neighbor": neighbor}


def test_derive_relationships_populates_both_tables_end_to_end(tmp_path):
    db_path = str(tmp_path / "town.db")
    ids = _build_minimal_town(db_path)

    derive_relationships(db_path)

    conn = connect(db_path)
    relationship_rows = conn.execute(
        "SELECT resident_a_id, resident_b_id, relationship_type FROM relationships"
    ).fetchall()

    father, mother, child, neighbor = ids["father"], ids["mother"], ids["child"], ids["neighbor"]

    def types_for(resident_x, resident_y):
        lo, hi = sorted((resident_x, resident_y))
        return {t for a, b, t in relationship_rows if (a, b) == (lo, hi)}

    assert types_for(father, mother) == {"spouse"}
    assert types_for(father, child) == {"parent"}
    assert types_for(mother, child) == {"parent"}
    assert types_for(father, neighbor) == {"coworker", "neighbor", "unit_mate"}
    # Bob ("neighbor", born 1265) and Lil ("child", born 1295) are both enrolled
    # at building 21, but 30 years apart in age -- correctly not classmates.
    assert types_for(child, neighbor) == {"neighbor"}

    shop_rows = conn.execute(
        "SELECT resident_id, shop_building_id, is_primary FROM shop_relationships"
    ).fetchall()
    assert shop_rows == [(father, 10, 1)]

    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_derive_relationships_is_idempotent_when_called_twice(tmp_path):
    db_path = str(tmp_path / "town.db")
    _build_minimal_town(db_path)

    derive_relationships(db_path)
    conn = connect(db_path)
    first_relationship_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    first_shop_count = conn.execute("SELECT COUNT(*) FROM shop_relationships").fetchone()[0]

    derive_relationships(db_path)
    second_relationship_count = conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
    second_shop_count = conn.execute("SELECT COUNT(*) FROM shop_relationships").fetchone()[0]

    assert first_relationship_count > 0
    assert second_relationship_count == first_relationship_count
    assert second_shop_count == first_shop_count


def test_derive_relationships_is_deterministic_across_separate_databases(tmp_path):
    db_path_a = str(tmp_path / "town_a.db")
    db_path_b = str(tmp_path / "town_b.db")
    _build_minimal_town(db_path_a)
    _build_minimal_town(db_path_b)

    derive_relationships(db_path_a)
    derive_relationships(db_path_b)

    conn_a = connect(db_path_a)
    conn_b = connect(db_path_b)
    rows_a = sorted(conn_a.execute(
        "SELECT resident_a_id, resident_b_id, relationship_type, detail FROM relationships"
    ).fetchall())
    rows_b = sorted(conn_b.execute(
        "SELECT resident_a_id, resident_b_id, relationship_type, detail FROM relationships"
    ).fetchall())
    assert rows_a == rows_b
