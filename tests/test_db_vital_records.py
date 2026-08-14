# tests/test_db_vital_records.py
from datetime import date, timedelta

from town_db.vital_records import (
    DEFAULT_DEATH_RATE_BY_AGE,
    DISEASE_DEATH_MULTIPLIER,
    FERTILE_AGE_RANGE,
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
    assert deaths == []


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


def test_death_rate_is_elevated_by_disease_active_on_the_actual_death_date_not_year_start():
    # Disease starts 100 days into the year, not on year_start itself -- this is
    # the realistic case that exposed the year_start-anchored bug.
    disease_start = YEAR_START + timedelta(days=100)
    disease_end = YEAR_START + timedelta(days=150)
    disease = {
        "_db_id": 1, "start_date": disease_start.isoformat(),
        "end_date": disease_end.isoformat(),
        "affected_zone_type": None, "severity": 1.0,
    }
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    residents = [_adult(i, 1, "male", 30) for i in range(500)]

    _, deaths_with_disease, _ = generate_births_and_deaths(
        ("town", 1), [household], [dict(r) for r in residents], [disease], YEAR_START,
        temple_building_id=99, healer_building_id=None,
        death_rate_by_age={**DEFAULT_DEATH_RATE_BY_AGE, "adult": 0.01},
    )
    # At least some of these deaths must actually be dated inside the disease window
    # and tagged 'plague' -- proving the check used the real candidate date, not year_start.
    plague_deaths_in_window = [
        d for d in deaths_with_disease
        if d["cause"] == "plague" and disease_start <= date.fromisoformat(d["death_date"]) <= disease_end
    ]
    assert len(plague_deaths_in_window) > 0


def test_death_rate_is_elevated_only_for_residents_in_the_affected_zone():
    disease = {
        "_db_id": 1, "start_date": YEAR_START.isoformat(),
        "end_date": date(1300, 12, 31).isoformat(),
        "affected_zone_type": "poor_residential", "severity": 1.0,
    }
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    affected_residents = [
        _adult(i, 1, "male", 30, home_building_id=1) for i in range(200)
    ]
    for r in affected_residents:
        r["home_zone_type"] = "poor_residential"
    unaffected_residents = [
        _adult(200 + i, 1, "male", 30, home_building_id=1) for i in range(200)
    ]
    for r in unaffected_residents:
        r["home_zone_type"] = "noble_residential"

    _, affected_deaths, _ = generate_births_and_deaths(
        ("town", 1), [household], [dict(r) for r in affected_residents], [disease], YEAR_START,
        temple_building_id=99, healer_building_id=None,
        death_rate_by_age={**DEFAULT_DEATH_RATE_BY_AGE, "adult": 0.01},
    )
    _, unaffected_deaths, _ = generate_births_and_deaths(
        ("town", 1), [household], [dict(r) for r in unaffected_residents], [disease], YEAR_START,
        temple_building_id=99, healer_building_id=None,
        death_rate_by_age={**DEFAULT_DEATH_RATE_BY_AGE, "adult": 0.01},
    )
    assert len(affected_deaths) > len(unaffected_deaths)
    assert all(d["cause"] == "plague" for d in affected_deaths)
    assert all(d["cause"] != "plague" for d in unaffected_deaths)


def test_childbirth_is_never_the_cause_for_men_or_non_fertile_age_women():
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    residents = []
    db_id = 0
    # A mixed population: men of every adult age, plus women both inside and
    # outside the fertile window. Death rate forced to 1.0 so everyone dies.
    for age in range(18, 60):
        residents.append(_adult(db_id, 1, "male", age))
        db_id += 1
        residents.append(_adult(db_id, 1, "female", age))
        db_id += 1

    age_by_db_id = {r["db_id"]: YEAR_START.year - date.fromisoformat(r["birth_date"]).year
                    for r in residents}
    gender_by_db_id = {r["db_id"]: r["gender"] for r in residents}

    _, deaths, _ = generate_births_and_deaths(
        ("town", 1), [household], residents, [], YEAR_START,
        temple_building_id=99, healer_building_id=None, birth_rate=0.0,
        death_rate_by_age={k: 1.0 for k in DEFAULT_DEATH_RATE_BY_AGE},
    )
    assert len(deaths) == len(residents)

    childbirth_deaths = [d for d in deaths if d["cause"] == "childbirth"]
    assert len(childbirth_deaths) > 0, "expected at least some childbirth deaths to exist at all"
    for d in childbirth_deaths:
        db_id = d["resident_db_id"]
        assert gender_by_db_id[db_id] == "female", d
        assert FERTILE_AGE_RANGE[0] <= age_by_db_id[db_id] <= FERTILE_AGE_RANGE[1], d


def test_a_second_female_adult_is_never_recorded_as_the_father():
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    mother = _adult(1, 1, "female", 25)
    other_woman = _adult(2, 1, "female", 30)

    births, _, _ = generate_births_and_deaths(
        ("town", 1), [household], [mother, other_woman], [], YEAR_START,
        temple_building_id=99, healer_building_id=None, birth_rate=1.0,
        death_rate_by_age={k: 0.0 for k in DEFAULT_DEATH_RATE_BY_AGE},
    )
    assert len(births) == 1
    assert births[0]["_mother_db_id"] == 1
    assert births[0]["_father_db_id"] is None


def test_a_male_adult_in_the_household_is_recorded_as_the_father():
    household = {"id": 1, "family_name": "Smith", "race": "human"}
    mother = _adult(1, 1, "female", 25)
    other_woman = _adult(2, 1, "female", 30)
    father = _adult(3, 1, "male", 32)

    births, _, _ = generate_births_and_deaths(
        ("town", 1), [household], [mother, other_woman, father], [], YEAR_START,
        temple_building_id=99, healer_building_id=None, birth_rate=1.0,
        death_rate_by_age={k: 0.0 for k in DEFAULT_DEATH_RATE_BY_AGE},
    )
    assert len(births) == 1
    assert births[0]["_father_db_id"] == 3


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
