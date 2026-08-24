import json

from town_relationships.military import derive_unit_mate_relationships


def test_overlapping_service_at_the_same_garrison_are_unit_mates():
    military_service = [
        {"resident_id": 1, "garrison_building_id": 5, "start_date": "1300-01-01", "end_date": "1300-06-01"},
        {"resident_id": 2, "garrison_building_id": 5, "start_date": "1300-03-01", "end_date": None},
    ]
    relationships = derive_unit_mate_relationships(military_service)
    assert len(relationships) == 1
    row = relationships[0]
    assert (row["resident_a_id"], row["resident_b_id"]) == (1, 2)
    assert json.loads(row["detail"]) == {"overlap_start": "1300-03-01", "overlap_end": "1300-06-01"}


def test_non_overlapping_service_at_the_same_garrison_are_not_unit_mates():
    military_service = [
        {"resident_id": 1, "garrison_building_id": 5, "start_date": "1290-01-01", "end_date": "1291-01-01"},
        {"resident_id": 2, "garrison_building_id": 5, "start_date": "1300-01-01", "end_date": None},
    ]
    assert derive_unit_mate_relationships(military_service) == []


def test_overlapping_service_at_different_garrisons_are_not_unit_mates():
    military_service = [
        {"resident_id": 1, "garrison_building_id": 5, "start_date": "1300-01-01", "end_date": None},
        {"resident_id": 2, "garrison_building_id": 6, "start_date": "1300-01-01", "end_date": None},
    ]
    assert derive_unit_mate_relationships(military_service) == []


def test_two_still_serving_unit_mates_have_no_overlap_end():
    military_service = [
        {"resident_id": 1, "garrison_building_id": 5, "start_date": "1300-01-01", "end_date": None},
        {"resident_id": 2, "garrison_building_id": 5, "start_date": "1300-02-01", "end_date": None},
    ]
    relationships = derive_unit_mate_relationships(military_service)
    detail = json.loads(relationships[0]["detail"])
    assert detail["overlap_end"] is None
