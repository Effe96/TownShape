from datetime import date

from town_db.enrollment import SCHOOL_AGE_RANGE, generate_school_enrollments
from town_db.military import MILITARY_OCCUPATIONS, generate_military_service

YEAR_START = date(1300, 1, 1)


def _resident(db_id, age_years, occupation=None, workplace_building_id=None):
    birth_year = YEAR_START.year - age_years
    return {
        "db_id": db_id, "birth_date": date(birth_year, 6, 1).isoformat(),
        "death_date": None, "occupation": occupation,
        "workplace_building_id": workplace_building_id,
    }


def test_school_age_child_enrolls_when_a_school_exists():
    resident = _resident(1, SCHOOL_AGE_RANGE[0])
    enrollments = generate_school_enrollments(
        ("town", 1), [resident], school_building_ids=[10], university_building_ids=[], year_start=YEAR_START
    )
    assert len(enrollments) == 1
    assert enrollments[0]["resident_db_id"] == 1
    assert enrollments[0]["enrollment_type"] == "school"
    assert enrollments[0]["school_building_id"] == 10


def test_no_enrollment_when_no_school_or_university_exists():
    resident = _resident(1, SCHOOL_AGE_RANGE[0])
    enrollments = generate_school_enrollments(
        ("town", 1), [resident], school_building_ids=[], university_building_ids=[], year_start=YEAR_START
    )
    assert enrollments == []


def test_out_of_range_age_never_enrolls():
    resident = _resident(1, 45)
    enrollments = generate_school_enrollments(
        ("town", 1), [resident], school_building_ids=[10], university_building_ids=[20], year_start=YEAR_START
    )
    assert enrollments == []


def test_military_service_only_for_military_occupations_at_a_real_garrison():
    soldier = _resident(1, 30, occupation="soldier", workplace_building_id=50)
    farmer = _resident(2, 30, occupation="farmer", workplace_building_id=51)
    soldier_wrong_building = _resident(3, 30, occupation="soldier", workplace_building_id=99)

    records = generate_military_service(
        [soldier, farmer, soldier_wrong_building], garrison_building_ids=[50], year_start=YEAR_START
    )
    assert len(records) == 1
    assert records[0]["resident_db_id"] == 1
    assert records[0]["garrison_building_id"] == 50


def test_military_service_skips_dead_residents():
    soldier = _resident(1, 30, occupation="soldier", workplace_building_id=50)
    soldier["death_date"] = "1299-01-01"
    records = generate_military_service([soldier], garrison_building_ids=[50], year_start=YEAR_START)
    assert records == []
