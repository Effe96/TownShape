from town_db.schema import connect, create_schema
from town_db.succession import primary_occupation_info, promote_apprentice


def test_primary_occupation_info_identifies_shopkeep_with_apprentice():
    is_primary, apprentice_occupation = primary_occupation_info("shop", "shopkeep")
    assert is_primary is True
    assert apprentice_occupation == "shop_staff"


def test_primary_occupation_info_false_for_non_promotable_building():
    is_primary, apprentice_occupation = primary_occupation_info("temple", "priest")
    assert is_primary is False
    assert apprentice_occupation is None


def test_primary_occupation_info_false_for_non_primary_occupation():
    is_primary, apprentice_occupation = primary_occupation_info("shop", "shop_staff")
    assert is_primary is False


def test_promote_apprentice_promotes_living_apprentice(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'merchant', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'merchant', 'shop', 0, 0, 1)"
    )
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) "
        "VALUES (1, 1, 'A', 'B', 'male', 'human', '1280-01-01', 'poor', 1, 'shop_staff')"
    )
    conn.commit()

    promoted_id = promote_apprentice(conn, workplace_id=1, apprentice_occupation="shop_staff", primary_occupation="shopkeep")
    conn.commit()

    assert promoted_id == 1
    row = conn.execute("SELECT occupation FROM residents WHERE id = 1").fetchone()
    assert row == ("shopkeep",)


def test_promote_apprentice_returns_none_when_no_apprentice_occupation():
    conn = None  # not reached -- apprentice_occupation is None short-circuits before any query
    assert promote_apprentice(conn, workplace_id=1, apprentice_occupation=None, primary_occupation="shopkeep") is None
