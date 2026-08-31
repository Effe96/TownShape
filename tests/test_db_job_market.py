from datetime import date

from town_db.job_market import fill_job_vacancies
from town_db.schema import connect, create_schema


def _insert_shop_with_owner_and_apprentice(conn, owner_id, apprentice_id, household_id=1, building_id=1):
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'merchant', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (?, 1, 'merchant', 'shop', 0, 0, 0)", (building_id,),
    )
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (?, 'Smith', 'human')", (household_id,))
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) "
        "VALUES (?, ?, 'A', 'B', 'male', 'human', '1260-01-01', 'poor', ?, 'shopkeep')",
        (owner_id, household_id, building_id),
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) "
        "VALUES (?, ?, 'C', 'D', 'male', 'human', '1280-01-01', 'poor', ?, 'shop_staff')",
        (apprentice_id, household_id, building_id),
    )


def test_apprentice_is_promoted_when_owner_dies_this_year(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_shop_with_owner_and_apprentice(conn, owner_id=1, apprentice_id=2)
    conn.execute(
        "INSERT INTO deaths (resident_id, death_date, cause) VALUES (1, '1301-03-01', 'illness')"
    )
    conn.execute("UPDATE residents SET death_date = '1301-03-01' WHERE id = 1")
    conn.commit()

    fill_job_vacancies(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    row = conn.execute("SELECT occupation FROM residents WHERE id = 2").fetchone()
    assert row == ("shopkeep",)


def test_labor_market_fallback_fills_non_promotable_vacancy(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', '[]')")
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'temple', 0, 0, 0)"
    )
    conn.execute("INSERT INTO households (id, family_name, race) VALUES (1, 'Smith', 'human')")
    # the deceased acolyte
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses, "
        "workplace_building_id, occupation) "
        "VALUES (1, 1, 'A', 'B', 'male', 'human', '1260-01-01', 'poor', 1, 'acolyte')"
    )
    conn.execute("INSERT INTO deaths (resident_id, death_date, cause) VALUES (1, '1301-03-01', 'illness')")
    conn.execute("UPDATE residents SET death_date = '1301-03-01' WHERE id = 1")
    # an unemployed adult, the only eligible candidate
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, ses) "
        "VALUES (2, 1, 'C', 'D', 'male', 'human', '1275-01-01', 'poor')"
    )
    conn.commit()

    fill_job_vacancies(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()

    row = conn.execute("SELECT occupation, workplace_building_id FROM residents WHERE id = 2").fetchone()
    assert row == ("acolyte", 1)


def test_vacancy_unfilled_when_no_apprentice_and_no_candidates(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    _insert_shop_with_owner_and_apprentice(conn, owner_id=1, apprentice_id=2)
    # the apprentice also dies, along with the owner -- no one left to promote or hire
    conn.execute("INSERT INTO deaths (resident_id, death_date, cause) VALUES (1, '1301-03-01', 'illness')")
    conn.execute("INSERT INTO deaths (resident_id, death_date, cause) VALUES (2, '1301-03-01', 'illness')")
    conn.execute("UPDATE residents SET death_date = '1301-03-01' WHERE id IN (1, 2)")
    conn.commit()

    fill_job_vacancies(conn, seed=("town", 1), year_start=date(1301, 1, 1), year_end=date(1302, 1, 1))
    conn.commit()  # must not raise

    assert conn.execute("SELECT COUNT(*) FROM residents WHERE occupation = 'shopkeep' AND death_date IS NULL").fetchone()[0] == 0
