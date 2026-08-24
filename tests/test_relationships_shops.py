from town_relationships.shops import derive_shop_relationships

BUILDINGS = [{"id": 1, "x": 0.0, "y": 0.0}, {"id": 10, "x": 3.0, "y": 4.0}, {"id": 11, "x": 0.0, "y": 0.0}]


def _resident(resident_id, household_id, ses="poor", occupation=None, home_building_id=1):
    return {
        "id": resident_id, "household_id": household_id, "ses": ses,
        "occupation": occupation, "home_building_id": home_building_id,
    }


def _purchase(resident_id, shop_building_id, total_price, category):
    return {
        "resident_id": resident_id, "shop_building_id": shop_building_id,
        "total_price": total_price, "category": category,
    }


def test_a_single_purchase_produces_a_customer_row_marked_primary():
    residents = [_resident(1, 100)]
    purchases = [_purchase(1, 10, 2.0, "food")]
    relationships = derive_shop_relationships(residents, purchases, BUILDINGS)
    assert len(relationships) == 1
    row = relationships[0]
    assert row["resident_id"] == 1
    assert row["shop_building_id"] == 10
    assert row["purchase_count"] == 1
    assert row["total_spent"] == 2.0
    assert row["distance"] == 5.0
    assert row["is_primary"] == 1


def test_resident_with_no_purchases_produces_no_rows():
    residents = [_resident(1, 100)]
    assert derive_shop_relationships(residents, [], BUILDINGS) == []


def test_closer_shop_scores_higher_than_farther_shop_for_equal_spend():
    residents = [_resident(1, 100)]
    purchases = [_purchase(1, 10, 5.0, "food"), _purchase(1, 11, 5.0, "food")]
    relationships = derive_shop_relationships(residents, purchases, BUILDINGS)
    by_shop = {r["shop_building_id"]: r for r in relationships}
    assert by_shop[11]["customer_score"] > by_shop[10]["customer_score"]
    assert by_shop[11]["is_primary"] == 1
    assert by_shop[10]["is_primary"] == 0


def test_rich_household_gets_a_higher_luxury_need_score_than_poor():
    rich = [_resident(1, 100, ses="rich")]
    poor = [_resident(2, 200, ses="poor")]
    rich_row = derive_shop_relationships(rich, [_purchase(1, 10, 10.0, "luxury")], BUILDINGS)[0]
    poor_row = derive_shop_relationships(poor, [_purchase(2, 10, 10.0, "luxury")], BUILDINGS)[0]
    assert rich_row["need_score"] > poor_row["need_score"]


def test_tools_need_weight_scales_with_working_adults_not_household_size():
    residents = [
        _resident(1, 100, occupation="smith"), _resident(2, 100, occupation=None),
        _resident(3, 100, occupation="mason"),
    ]
    purchases = [_purchase(1, 10, 10.0, "tools")]
    row = derive_shop_relationships(residents, purchases, BUILDINGS)[0]
    # Household size is 3, but only residents 1 and 3 have an occupation.
    assert row["need_score"] == 10.0 * 2


def test_resident_with_no_home_building_is_skipped():
    residents = [_resident(1, 100, home_building_id=None)]
    purchases = [_purchase(1, 10, 5.0, "food")]
    assert derive_shop_relationships(residents, purchases, BUILDINGS) == []
