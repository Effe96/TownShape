from town_relationships.pairs import canonical_pair


def test_canonical_pair_orders_lower_id_first():
    row = canonical_pair(7, 3, "coworker")
    assert row["resident_a_id"] == 3
    assert row["resident_b_id"] == 7
    assert row["relationship_type"] == "coworker"
    assert row["detail"] is None


def test_canonical_pair_is_order_independent():
    assert canonical_pair(3, 7, "coworker") == canonical_pair(7, 3, "coworker")


def test_canonical_pair_carries_detail():
    row = canonical_pair(1, 2, "neighbor", detail='{"distance": 5.0}')
    assert row["detail"] == '{"distance": 5.0}'
