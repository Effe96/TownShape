import json

from town_relationships.school import derive_classmate_relationships


def _resident(resident_id, birth_date):
    return {"id": resident_id, "birth_date": birth_date}


def test_overlapping_enrollment_at_the_same_school_are_classmates():
    school_enrollments = [
        {"resident_id": 1, "school_building_id": 21, "start_date": "1300-09-01", "end_date": "1301-06-01"},
        {"resident_id": 2, "school_building_id": 21, "start_date": "1300-09-01", "end_date": None},
    ]
    residents = [_resident(1, "1292-01-01"), _resident(2, "1292-06-01")]
    relationships = derive_classmate_relationships(school_enrollments, residents)
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
    residents = [_resident(1, "1284-01-01"), _resident(2, "1284-01-01")]
    assert derive_classmate_relationships(school_enrollments, residents) == []


def test_overlapping_enrollment_at_different_schools_are_not_classmates():
    school_enrollments = [
        {"resident_id": 1, "school_building_id": 21, "start_date": "1300-09-01", "end_date": None},
        {"resident_id": 2, "school_building_id": 22, "start_date": "1300-09-01", "end_date": None},
    ]
    residents = [_resident(1, "1292-01-01"), _resident(2, "1292-01-01")]
    assert derive_classmate_relationships(school_enrollments, residents) == []


def test_overlapping_enrollment_at_the_same_school_but_different_ages_are_not_classmates():
    # Regression test: a school-age resident (age 6) and a much older schoolmate
    # (age 12) enrolled at the same single school building, on the exact same
    # start_date with no end_date (as generate_school_enrollments always
    # produces), must NOT be treated as classmates just because their
    # enrollment windows technically overlap -- they're in different grades.
    school_enrollments = [
        {"resident_id": 1, "school_building_id": 21, "start_date": "1300-01-01", "end_date": None},
        {"resident_id": 2, "school_building_id": 21, "start_date": "1300-01-01", "end_date": None},
    ]
    residents = [_resident(1, "1294-01-01"), _resident(2, "1288-01-01")]
    assert derive_classmate_relationships(school_enrollments, residents) == []
