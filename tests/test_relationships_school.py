import json

from town_relationships.school import derive_classmate_relationships


def test_overlapping_enrollment_at_the_same_school_are_classmates():
    school_enrollments = [
        {"resident_id": 1, "school_building_id": 21, "start_date": "1300-09-01", "end_date": "1301-06-01"},
        {"resident_id": 2, "school_building_id": 21, "start_date": "1300-09-01", "end_date": None},
    ]
    relationships = derive_classmate_relationships(school_enrollments)
    assert len(relationships) == 1
    row = relationships[0]
    assert (row["resident_a_id"], row["resident_b_id"]) == (1, 2)
    assert row["relationship_type"] == "classmate"
    assert json.loads(row["detail"]) == {"overlap_start": "1300-09-01", "overlap_end": "1301-06-01"}


def test_non_overlapping_enrollment_at_the_same_school_are_not_classmates():
    school_enrollments = [
        {"resident_id": 1, "school_building_id": 21, "start_date": "1290-09-01", "end_date": "1291-06-01"},
        {"resident_id": 2, "school_building_id": 21, "start_date": "1300-09-01", "end_date": None},
    ]
    assert derive_classmate_relationships(school_enrollments) == []


def test_overlapping_enrollment_at_different_schools_are_not_classmates():
    school_enrollments = [
        {"resident_id": 1, "school_building_id": 21, "start_date": "1300-09-01", "end_date": None},
        {"resident_id": 2, "school_building_id": 22, "start_date": "1300-09-01", "end_date": None},
    ]
    assert derive_classmate_relationships(school_enrollments) == []
