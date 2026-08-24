from town_relationships.work import derive_coworker_relationships


def test_residents_sharing_a_workplace_are_coworkers():
    residents = [
        {"id": 1, "workplace_building_id": 50}, {"id": 2, "workplace_building_id": 50},
        {"id": 3, "workplace_building_id": 51},
    ]
    relationships = derive_coworker_relationships(residents)
    pairs = {(r["resident_a_id"], r["resident_b_id"]) for r in relationships}
    assert pairs == {(1, 2)}
    assert all(r["relationship_type"] == "coworker" for r in relationships)


def test_residents_with_no_workplace_are_excluded():
    residents = [{"id": 1, "workplace_building_id": None}, {"id": 2, "workplace_building_id": None}]
    assert derive_coworker_relationships(residents) == []


def test_three_coworkers_at_the_same_workplace_get_every_pair():
    residents = [{"id": i, "workplace_building_id": 50} for i in (1, 2, 3)]
    relationships = derive_coworker_relationships(residents)
    pairs = {(r["resident_a_id"], r["resident_b_id"]) for r in relationships}
    assert pairs == {(1, 2), (1, 3), (2, 3)}
