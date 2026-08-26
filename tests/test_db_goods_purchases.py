from datetime import date

from town_shaper.seeding import rng_for
from town_db.goods import GOODS_CATALOG, insert_goods
from town_db.purchases import generate_purchases
from town_db.schema import connect, create_schema

YEAR_START = date(1300, 1, 1)


def _household(id_):
    return {"id": id_, "family_name": "Smith", "race": "human"}


def _resident(db_id, household_id, age_bracket="adult", death_date=None):
    return {
        "db_id": db_id, "household_id": household_id, "age_bracket": age_bracket,
        "ses": "poor", "is_noble": False, "death_date": death_date,
    }


def test_insert_goods_populates_the_catalog(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    ids = insert_goods(conn)
    assert set(ids.keys()) == {g["name"] for g in GOODS_CATALOG}
    count = conn.execute("SELECT COUNT(*) FROM goods").fetchone()[0]
    assert count == len(GOODS_CATALOG)


def test_generate_purchases_returns_nothing_with_no_shops():
    households = [_household(1)]
    residents = [_resident(1, 1)]
    purchases = generate_purchases(
        ("town", 1), households, residents, {"bread": 1}, [], YEAR_START, weeks=4
    )
    assert purchases == []


def test_generate_purchases_only_references_provided_shops_and_goods():
    households = [_household(1), _household(2)]
    residents = [_resident(1, 1), _resident(2, 2)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    shop_ids = [10, 11, 12]
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, shop_ids, YEAR_START, weeks=52
    )
    assert len(purchases) > 0
    for p in purchases:
        assert p["shop_building_id"] in shop_ids
        assert p["good_id"] in goods_ids.values()
        assert p["total_price"] == round(p["unit_price"] * p["quantity"], 2)
        purchase_date = date.fromisoformat(p["purchase_date"])
        assert YEAR_START <= purchase_date < date(1301, 1, 1)


def test_generate_purchases_is_deterministic():
    households = [_household(1)]
    residents = [_resident(1, 1)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    p1 = generate_purchases(("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52)
    p2 = generate_purchases(("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52)
    assert p1 == p2


def test_high_sv_staples_are_bought_more_often_than_low_sv_luxuries():
    # The spec: "SV weights how often a purchase category occurs (bread
    # constantly, jewelry rarely)". bread sv=800, jewelry sv=400.
    households = [_household(i) for i in range(1, 41)]
    residents = [_resident(i, i) for i in range(1, 41)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52
    )
    assert len(purchases) >= 500

    bread_count = sum(1 for p in purchases if p["good_id"] == goods_ids["bread"])
    jewelry_count = sum(1 for p in purchases if p["good_id"] == goods_ids["jewelry"])
    assert bread_count > jewelry_count, f"bread={bread_count}, jewelry={jewelry_count}"


def test_expensive_goods_are_only_ever_bought_one_at_a_time():
    households = [_household(i) for i in range(1, 21)]
    residents = [_resident(i, i) for i in range(1, 21)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    price_by_id = {goods_ids[g["name"]]: g["typical_price"] for g in GOODS_CATALOG}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52
    )
    for p in purchases:
        if price_by_id[p["good_id"]] >= 1.0:
            assert p["quantity"] == 1


def test_a_resident_never_shops_after_their_own_death_date():
    death_date = "1300-06-15"
    households = [_household(1)]
    residents = [_resident(1, 1, death_date=death_date)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52
    )
    assert len(purchases) > 0
    for p in purchases:
        assert p["purchase_date"] <= death_date, p


def test_a_household_whose_only_adult_died_before_the_year_buys_nothing():
    households = [_household(1)]
    residents = [_resident(1, 1, death_date="1299-12-31")]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52
    )
    assert purchases == []


def test_goods_catalog_includes_magic_category():
    magic_goods = [g for g in GOODS_CATALOG if g["category"] == "magic"]
    assert {g["name"] for g in magic_goods} == {"healing potion", "spell scroll", "arcane reagents"}


def test_insert_goods_includes_magic_goods(tmp_path):
    conn = connect(str(tmp_path / "town.db"))
    create_schema(conn)
    ids = insert_goods(conn)
    assert "healing potion" in ids
    assert "spell scroll" in ids
    assert "arcane reagents" in ids


def test_magic_goods_excluded_when_magic_prevalence_is_zero():
    households = [_household(i) for i in range(1, 21)]
    residents = [_resident(i, i) for i in range(1, 21)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    magic_good_ids = {goods_ids["healing potion"], goods_ids["spell scroll"], goods_ids["arcane reagents"]}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
        magic_prevalence=0.0, arcane_shop_building_ids=[99],
    )
    assert all(p["good_id"] not in magic_good_ids for p in purchases)


def test_magic_goods_excluded_when_no_arcane_shop_exists():
    households = [_household(i) for i in range(1, 21)]
    residents = [_resident(i, i) for i in range(1, 21)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    magic_good_ids = {goods_ids["healing potion"], goods_ids["spell scroll"], goods_ids["arcane reagents"]}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
        magic_prevalence=0.9, arcane_shop_building_ids=[],
    )
    assert all(p["good_id"] not in magic_good_ids for p in purchases)


def test_magic_goods_purchased_and_shop_scoped_when_available():
    households = [_household(i) for i in range(1, 41)]
    residents = [_resident(i, i) for i in range(1, 41)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    magic_good_ids = {goods_ids["healing potion"], goods_ids["spell scroll"], goods_ids["arcane reagents"]}
    purchases = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
        magic_prevalence=0.9, arcane_shop_building_ids=[99],
    )
    magic_purchases = [p for p in purchases if p["good_id"] in magic_good_ids]
    assert len(magic_purchases) > 0
    assert all(p["shop_building_id"] == 99 for p in magic_purchases)
    non_magic_purchases = [p for p in purchases if p["good_id"] not in magic_good_ids]
    assert all(p["shop_building_id"] == 10 for p in non_magic_purchases)


def test_generate_purchases_default_magic_params_match_previous_behavior():
    households = [_household(1)]
    residents = [_resident(1, 1)]
    goods_ids = {g["name"]: i + 1 for i, g in enumerate(GOODS_CATALOG)}
    baseline = generate_purchases(("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52)
    explicit = generate_purchases(
        ("town", 1), households, residents, goods_ids, [10], YEAR_START, weeks=52,
        magic_prevalence=0.0, arcane_shop_building_ids=None,
    )
    assert baseline == explicit
