import json

from town_relationships.neighbors import derive_neighbor_relationships


def test_residents_of_different_households_in_the_same_building_are_neighbors_at_zero_distance():
    residents = [
        {"id": 1, "household_id": 100, "home_building_id": 1},
        {"id": 2, "household_id": 200, "home_building_id": 1},
    ]
    buildings = [{"id": 1, "x": 0.0, "y": 0.0}]
    relationships = derive_neighbor_relationships(residents, buildings)
    assert len(relationships) == 1
    row = relationships[0]
    assert (row["resident_a_id"], row["resident_b_id"]) == (1, 2)
    assert json.loads(row["detail"])["distance"] == 0.0


def test_residents_of_the_same_household_and_building_are_not_double_counted_as_neighbors():
    residents = [
        {"id": 1, "household_id": 100, "home_building_id": 1},
        {"id": 2, "household_id": 100, "home_building_id": 1},
    ]
    buildings = [{"id": 1, "x": 0.0, "y": 0.0}]
    assert derive_neighbor_relationships(residents, buildings) == []


def test_nearest_building_within_k_produces_neighbor_ties():
    residents = [
        {"id": 1, "household_id": 100, "home_building_id": 1},
        {"id": 2, "household_id": 200, "home_building_id": 2},
    ]
    buildings = [{"id": 1, "x": 0.0, "y": 0.0}, {"id": 2, "x": 3.0, "y": 4.0}]
    relationships = derive_neighbor_relationships(residents, buildings, k=1)
    assert len(relationships) == 1
    row = relationships[0]
    assert (row["resident_a_id"], row["resident_b_id"]) == (1, 2)
    assert json.loads(row["detail"])["distance"] == 5.0


def test_buildings_beyond_k_nearest_are_not_neighbors():
    residents = [
        {"id": 1, "household_id": 100, "home_building_id": 1},
        {"id": 2, "household_id": 200, "home_building_id": 2},
        {"id": 3, "household_id": 300, "home_building_id": 3},
        {"id": 4, "household_id": 400, "home_building_id": 4},
    ]
    buildings = [
        {"id": 1, "x": 0.0, "y": 0.0}, {"id": 2, "x": 1.0, "y": 0.0},
        {"id": 3, "x": 1000.0, "y": 0.0}, {"id": 4, "x": 1001.0, "y": 0.0},
    ]
    relationships = derive_neighbor_relationships(residents, buildings, k=1)
    pairs = {(r["resident_a_id"], r["resident_b_id"]) for r in relationships}
    assert pairs == {(1, 2), (3, 4)}


def test_residents_with_no_home_building_are_excluded():
    residents = [{"id": 1, "household_id": 100, "home_building_id": None}]
    buildings = [{"id": 1, "x": 0.0, "y": 0.0}]
    assert derive_neighbor_relationships(residents, buildings) == []
