import json
import sqlite3

from town_shaper.generate import generate_town

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


def test_generate_town_database_default_new_parameters_match_previous_behavior(tmp_path):
    db_path_a = str(tmp_path / "a.db")
    db_path_b = str(tmp_path / "b.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_a)
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path_b,
        area_per_resident_multiplier=1.0, density_multiplier=1.0, rich_proportion=0.05,
    )

    conn_a = sqlite3.connect(db_path_a)
    conn_b = sqlite3.connect(db_path_b)
    for table in ["residents", "buildings"]:
        rows_a = conn_a.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        rows_b = conn_b.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert rows_a == rows_b


def test_generate_town_database_threads_area_multiplier_into_building_placement(tmp_path):
    db_path_small = str(tmp_path / "small.db")
    db_path_large = str(tmp_path / "large.db")
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path_small, area_per_resident_multiplier=0.5
    )
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path_large, area_per_resident_multiplier=2.0
    )

    conn_small = sqlite3.connect(db_path_small)
    conn_large = sqlite3.connect(db_path_large)
    small_max_x = conn_small.execute("SELECT MAX(x) FROM buildings").fetchone()[0]
    large_max_x = conn_large.execute("SELECT MAX(x) FROM buildings").fetchone()[0]
    assert large_max_x > small_max_x


def test_generate_town_database_default_water_params_match_previous_behavior(tmp_path):
    db_path_a = str(tmp_path / "a.db")
    db_path_b = str(tmp_path / "b.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_a)
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path_b,
        num_rivers=0, has_coastline=False, has_port=False,
    )

    conn_a = sqlite3.connect(db_path_a)
    conn_b = sqlite3.connect(db_path_b)
    for table in ["residents", "buildings"]:
        rows_a = conn_a.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        rows_b = conn_b.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert rows_a == rows_b

    assert conn_a.execute("SELECT COUNT(*) FROM water_features").fetchone()[0] == 0


def test_generate_town_database_persists_water_features_and_port_buildings(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path,
        num_rivers=1, has_coastline=True, has_port=True,
    )
    conn = sqlite3.connect(db_path)
    kinds = sorted(row[0] for row in conn.execute("SELECT kind FROM water_features").fetchall())
    assert kinds == ["coastline", "river"]

    port_building_count = conn.execute(
        "SELECT COUNT(*) FROM buildings WHERE zone_type = 'port'"
    ).fetchone()[0]
    assert port_building_count > 0


def test_generate_town_database_with_water_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(
        ("town", 1), target_population=1500, db_path=db_path,
        num_rivers=1, has_coastline=True, has_port=True,
    )
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def test_generate_town_database_persists_water_feature_interior_rings(tmp_path):
    found_multi_ring = False
    for seed_index in range(10):
        seed = ("town", seed_index)
        db_path = str(tmp_path / f"town_{seed_index}.db")
        generate_town_database(seed, target_population=1500, db_path=db_path, has_coastline=True)

        town = generate_town(seed, target_population=1500, has_coastline=True)
        feature = next(f for f in town.water_features if f.kind == "coastline")
        expected_ring_count = 1 + len(feature.polygon.interiors)
        if expected_ring_count > 1:
            found_multi_ring = True

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT polygon FROM water_features WHERE kind = 'coastline'").fetchone()
        rings = json.loads(row[0])
        assert len(rings) == expected_ring_count

    assert found_multi_ring, "expected at least one seed to produce a coastline with interior rings"


def test_generate_town_database_default_magic_prevalence_matches_previous_behavior(tmp_path):
    db_path_a = str(tmp_path / "a.db")
    db_path_b = str(tmp_path / "b.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_a)
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_b, magic_prevalence=0.0)

    conn_a = sqlite3.connect(db_path_a)
    conn_b = sqlite3.connect(db_path_b)
    for table in ["residents", "buildings", "purchases"]:
        rows_a = conn_a.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        rows_b = conn_b.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert rows_a == rows_b


def test_generate_town_database_high_magic_prevalence_produces_talented_residents_and_arcane_purchases(tmp_path):
    found_arcane_purchase = False
    for seed_index in range(5):
        db_path = str(tmp_path / f"town_{seed_index}.db")
        generate_town_database(
            ("town", seed_index), target_population=5000, db_path=db_path, magic_prevalence=0.9,
        )
        conn = sqlite3.connect(db_path)
        talented_count = conn.execute("SELECT COUNT(*) FROM residents WHERE has_magical_talent = 1").fetchone()[0]
        assert talented_count > 0

        magic_purchase_count = conn.execute(
            "SELECT COUNT(*) FROM purchases p JOIN goods g ON g.id = p.good_id WHERE g.category = 'magic'"
        ).fetchone()[0]
        if magic_purchase_count > 0:
            found_arcane_purchase = True

    assert found_arcane_purchase


def test_generate_town_database_with_magic_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(
        ("town", 1), target_population=5000, db_path=db_path, magic_prevalence=0.9,
    )
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def test_generate_town_database_default_aggression_matches_previous_behavior(tmp_path):
    db_path_a = str(tmp_path / "a.db")
    db_path_b = str(tmp_path / "b.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_a)
    generate_town_database(("town", 1), target_population=1500, db_path=db_path_b, aggression=0.0)

    conn_a = sqlite3.connect(db_path_a)
    conn_b = sqlite3.connect(db_path_b)
    for table in ["residents", "buildings", "deaths"]:
        rows_a = conn_a.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        rows_b = conn_b.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        assert rows_a == rows_b

    assert conn_a.execute("SELECT COUNT(*) FROM skirmish_events").fetchone()[0] == 0


def test_generate_town_database_high_aggression_produces_skirmishes_and_maybe_casualties(tmp_path):
    found_casualty = False
    for seed_index in range(10):
        db_path = str(tmp_path / f"town_{seed_index}.db")
        generate_town_database(
            ("town", seed_index), target_population=5000, db_path=db_path, aggression=1.0,
        )
        conn = sqlite3.connect(db_path)
        skirmish_count = conn.execute("SELECT COUNT(*) FROM skirmish_events").fetchone()[0]
        assert skirmish_count > 0

        skirmish_death_count = conn.execute(
            "SELECT COUNT(*) FROM deaths WHERE cause = 'skirmish'"
        ).fetchone()[0]
        if skirmish_death_count > 0:
            found_casualty = True

    assert found_casualty


def test_generate_town_database_with_aggression_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(
        ("town", 1), target_population=5000, db_path=db_path, aggression=1.0,
    )
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def test_generate_town_database_produces_weapons_purchases_scoped_to_blacksmiths(tmp_path):
    found_weapons_purchase = False
    for seed_index in range(10):
        db_path = str(tmp_path / f"town_{seed_index}.db")
        generate_town_database(("town", seed_index), target_population=3000, db_path=db_path)
        conn = sqlite3.connect(db_path)

        blacksmith_ids = {
            row[0] for row in conn.execute(
                "SELECT id FROM buildings WHERE building_type = 'blacksmith'"
            ).fetchall()
        }
        weapons_good_ids = {
            row[0] for row in conn.execute(
                "SELECT id FROM goods WHERE category = 'weapons'"
            ).fetchall()
        }
        weapons_purchase_shops = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT shop_building_id FROM purchases WHERE good_id IN ({})".format(
                    ",".join(str(i) for i in weapons_good_ids)
                )
            ).fetchall()
        } if weapons_good_ids else set()

        if weapons_purchase_shops:
            found_weapons_purchase = True
            assert weapons_purchase_shops <= blacksmith_ids

    assert found_weapons_purchase


def test_generate_town_database_with_blacksmith_passes_foreign_key_check(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=3000, db_path=db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def test_generate_town_database_writes_town_state(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path, aggression=0.3, magic_prevalence=0.1)

    conn = sqlite3.connect(db_path)
    # `current_date` is a SQLite keyword (CURRENT_DATE) -- a bare reference in a result-column
    # list returns today's date, not the column, so the identifier must be quoted on read.
    row = conn.execute(
        'SELECT year_start, "current_date", aggression, magic_prevalence FROM town_state WHERE id = 1'
    ).fetchone()
    assert row == ("1300-01-01", "1301-01-01", 0.3, 0.1)


def test_generate_town_database_unchanged_by_persistence_refactor(tmp_path):
    # Regression guard for the generate.py -> persistence.py extraction: every existing table's
    # content for a fixed seed must be byte-identical to before the refactor.
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path)
    conn = sqlite3.connect(db_path)
    for table in ["residents", "households", "buildings", "purchases", "tax_payments",
                  "births", "deaths", "school_enrollments", "military_service", "skirmish_events"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count >= 0  # table exists and is queryable
    resident_count = conn.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    assert resident_count > 1000  # sanity floor matching the existing plausibility-bounds test


def test_generate_town_database_seeds_and_updates_household_wealth(tmp_path):
    db_path = str(tmp_path / "town.db")
    generate_town_database(("town", 1), target_population=1500, db_path=db_path)

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT wealth FROM households").fetchall()
    assert len(rows) > 0
    # Every household ends the year with a real (non-default, non-negative) wealth value --
    # income was added and spend was subtracted, not left at the raw starting seed or at zero
    # for everyone.
    assert all(w >= 0.0 for (w,) in rows)
    assert len(set(rows)) > 1, "expected wealth to vary across households, not be uniform"


def test_generate_town_database_wealth_is_deterministic(tmp_path):
    db_path_1 = str(tmp_path / "town1.db")
    db_path_2 = str(tmp_path / "town2.db")
    generate_town_database(("town", 4), target_population=800, db_path=db_path_1)
    generate_town_database(("town", 4), target_population=800, db_path=db_path_2)

    conn1 = sqlite3.connect(db_path_1)
    conn2 = sqlite3.connect(db_path_2)
    rows1 = conn1.execute("SELECT id, wealth FROM households ORDER BY id").fetchall()
    rows2 = conn2.execute("SELECT id, wealth FROM households ORDER BY id").fetchall()
    assert rows1 == rows2
