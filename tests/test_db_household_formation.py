from datetime import date

from town_db.household_formation import generate_household_formations
from town_db.schema import connect, create_schema


def _insert_home_building(conn, building_id, capacity, district_id=1):
    conn.execute(
        f"INSERT OR IGNORE INTO districts (id, zone_type, polygon) VALUES ({district_id}, 'rich_residential', '[]')"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (?, ?, 'rich_residential', 'residence', 0, 0, ?)",
        (building_id, district_id, capacity),
    )


def _insert_household_with_adults(conn, household_id, resident_ids, home_building_id=None, birth_date="1275-01-01"):
    conn.execute(
        "INSERT INTO households (id, family_name, race) VALUES (?, 'Smith', 'human')", (household_id,)
    )
    for resident_id in resident_ids:
        conn.execute(
            "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
            "home_building_id) VALUES (?, ?, 'A', 'B', 'male', 'human', ?, 'poor', ?)",
            (resident_id, household_id, birth_date, home_building_id),
        )


def test_third_adult_in_household_is_eligible_and_moves_out_when_matched(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    # household 1: three adults -- residents 1,2 are the "couple", resident 3 is eligible
    _insert_household_with_adults(conn, 1, [1, 2, 3])
    # household 2: a lone eligible adult from a different household, for resident 3 to pair with
    _insert_household_with_adults(conn, 2, [4])
    _insert_home_building(conn, building_id=10, capacity=2)
    conn.commit()

    # seed ("town", 15)'s first household_formation draw is ~0.0074, reliably under
    # HOUSEHOLD_FORMATION_RATE (0.15) -- chosen deterministically rather than looping over seeds,
    # since with a single mover in this fixture the outcome is a single coin flip either way.
    generate_household_formations(conn, seed=("town", 15), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    new_household_ids = {
        row[0] for row in conn.execute("SELECT DISTINCT household_id FROM residents WHERE id IN (3, 4)").fetchall()
    }
    # Both residents 3 and 4 moved to the same new household -- never split, never still 1-and-2
    # respectively.
    assert len(new_household_ids) == 1


def test_first_two_adults_in_household_are_never_eligible(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_household_with_adults(conn, 1, [1, 2])
    _insert_home_building(conn, building_id=10, capacity=2)
    conn.commit()

    generate_household_formations(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    household_ids = {row[0] for row in conn.execute("SELECT household_id FROM residents WHERE id IN (1, 2)").fetchall()}
    assert household_ids == {1}  # unchanged -- the founding couple is never eligible


def test_no_formation_when_no_vacant_housing(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_household_with_adults(conn, 1, [1, 2, 3])
    _insert_household_with_adults(conn, 2, [4])
    # A home building that exists but is already full.
    _insert_home_building(conn, building_id=10, capacity=1)
    conn.execute("UPDATE residents SET home_building_id = 10 WHERE id = 1")
    conn.commit()

    # Same firing seed as the "moves out when matched" test above -- the roll fires and a spouse
    # candidate is found, so this actually exercises the vacancy check rather than coincidentally
    # passing because the roll never fired.
    generate_household_formations(conn, seed=("town", 15), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    household_ids = {row[0] for row in conn.execute("SELECT household_id FROM residents WHERE id IN (3, 4)").fetchall()}
    assert household_ids == {1, 2}  # neither moved -- soft cap in effect


def test_formation_does_not_touch_occupation_or_workplace(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_household_with_adults(conn, 1, [1, 2, 3])
    _insert_household_with_adults(conn, 2, [4])
    _insert_home_building(conn, building_id=10, capacity=2)
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (99, 1, 'rich_residential', 'farm', 0, 0, 0)"
    )
    conn.execute("UPDATE residents SET occupation = 'farmer', workplace_building_id = 99 WHERE id = 3")
    conn.commit()

    generate_household_formations(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    row = conn.execute("SELECT occupation, workplace_building_id FROM residents WHERE id = 3").fetchone()
    assert row == ("farmer", 99)
