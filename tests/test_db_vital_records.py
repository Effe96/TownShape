# tests/test_db_vital_records.py
from datetime import date

from town_db.vital_records import (
    DEFAULT_DEATH_RATE_BY_AGE,
    DISEASE_DEATH_MULTIPLIER,
    generate_births_and_deaths,
    generate_disease_events,
)

YEAR_START = date(1300, 1, 1)


def _adult(db_id, household_id, gender, age_years, ses="poor", home_building_id=1, race="human"):
    birth_year = YEAR_START.year - age_years
    return {
        "db_id": db_id, "household_id": household_id, "gender": gender,
        "birth_date": date(birth_year, 1, 1).isoformat(), "death_date": None,
        "ses": ses, "is_noble": False, "home_building_id": home_building_id,
        "home_zone_type": "poor_residential", "age_bracket": "adult", "race": race,
    }


def test_generate_disease_events_shape_is_valid():
    events = generate_disease_events(("town", 1), YEAR_START, chance=1.0)
    assert len(events) == 1
    event = events[0]
    start = date.fromisoformat(event["start_date"])
    end = date.fromisoformat(event["end_date"])
    assert YEAR_START <= start < date(1301, 1, 1)
    assert end > start
    assert 0.0 < event["severity"] <= 1.0


def test_generate_disease_events_can_produce_none():
    events = generate_disease_events(("town", 1), YEAR_START, chance=0.0)
    assert events == []


def test_births_produce_matching_new_resident_and_birth_record():
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    mother = _adult(1, 1, "female", 25)
    father = _adult(2, 1, "male", 27)
    households, residents = [household], [mother, father]

    births, deaths, new_residents = generate_births_and_deaths(
        ("town", 1), households, residents, [], YEAR_START,
        temple_building_id=99, healer_building_id=None, birth_rate=1.0,
    )
    assert len(births) == len(new_residents)
    if births:
        assert births[0]["_mother_db_id"] == 1
        assert new_residents[0]["household_id"] == 1
        assert new_residents[0]["age_bracket"] == "child"
        assert new_residents[0]["race"] in {"human"}


def test_no_reporting_building_means_no_births():
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    mother = _adult(1, 1, "female", 25)
    father = _adult(2, 1, "male", 27)
    births, deaths, new_residents = generate_births_and_deaths(
        ("town", 1), [household], [mother, father], [], YEAR_START,
        temple_building_id=None, healer_building_id=None, birth_rate=1.0,
    )
    assert births == []
    assert new_residents == []


def test_death_rate_is_elevated_during_an_active_town_wide_disease_event():
    disease = {
        "_db_id": 1, "start_date": YEAR_START.isoformat(),
        "end_date": date(1300, 12, 31).isoformat(),
        "affected_zone_type": None, "severity": 1.0,
    }
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    residents = [_adult(i, 1, "male", 30) for i in range(200)]

    _, deaths_with_disease, _ = generate_births_and_deaths(
        ("town", 1), [household], [dict(r) for r in residents], [disease], YEAR_START,
        temple_building_id=99, healer_building_id=None,
        death_rate_by_age={**DEFAULT_DEATH_RATE_BY_AGE, "adult": 0.01},
    )
    _, deaths_without_disease, _ = generate_births_and_deaths(
        ("town", 1), [household], [dict(r) for r in residents], [], YEAR_START,
        temple_building_id=99, healer_building_id=None,
        death_rate_by_age={**DEFAULT_DEATH_RATE_BY_AGE, "adult": 0.01},
    )
    assert len(deaths_with_disease) > len(deaths_without_disease)
    assert all(d["cause"] == "plague" for d in deaths_with_disease)
    assert all(d["disease_event_id"] == 1 for d in deaths_with_disease)


def test_a_resident_who_already_has_a_death_date_is_never_rolled_again():
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    resident = _adult(1, 1, "male", 40)
    resident["death_date"] = "1299-05-01"
    _, deaths, _ = generate_births_and_deaths(
        ("town", 1), [household], [resident], [], YEAR_START,
        temple_building_id=99, healer_building_id=None,
        death_rate_by_age={**DEFAULT_DEATH_RATE_BY_AGE, "adult": 1.0},
    )
    assert deaths == []
