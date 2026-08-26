# tests/test_db_unrest.py
from datetime import date

from town_db.military import MILITARY_OCCUPATIONS
from town_db.unrest import generate_skirmish_casualties, generate_skirmish_events

YEAR_START = date(1300, 1, 1)


def _resident(db_id, ses="poor", age_bracket="adult", occupation=None, death_date=None):
    return {
        "db_id": db_id, "ses": ses, "age_bracket": age_bracket,
        "occupation": occupation, "death_date": death_date,
    }


def test_generate_skirmish_events_produces_none_at_zero_aggression():
    events = generate_skirmish_events(("town", 1), YEAR_START, aggression=0.0)
    assert events == []


def test_generate_skirmish_events_frequency_scales_with_aggression():
    low_total = 0
    high_total = 0
    trials = 30
    for seed_index in range(trials):
        low_total += len(generate_skirmish_events(("town", seed_index), YEAR_START, aggression=0.05))
        high_total += len(generate_skirmish_events(("town", seed_index), YEAR_START, aggression=0.9))
    assert high_total > low_total


def test_generate_skirmish_events_shape_is_valid():
    # aggression=100.0 forces a skirmish every single week (weekly chance is
    # capped at 1.0 in practice since rng.random() < 1.0 always), making this
    # deterministic rather than relying on a specific seed happening to roll one.
    events = generate_skirmish_events(("town", 1), YEAR_START, aggression=100.0)
    assert len(events) == 52
    for event in events:
        d = date.fromisoformat(event["skirmish_date"])
        assert YEAR_START <= d < date(1301, 1, 1)
        assert 0.2 <= event["severity"] <= 1.0
        assert event["name"]


def test_casualties_only_ever_poor_adults_or_guards():
    residents = (
        [_resident(i, ses="poor", age_bracket="adult") for i in range(200)]
        + [_resident(200 + i, ses="poor", age_bracket="child") for i in range(50)]
        + [_resident(300 + i, ses="rich", age_bracket="adult") for i in range(50)]
        + [_resident(400 + i, ses="rich", age_bracket="adult", occupation="guard") for i in range(10)]
        + [_resident(500 + i, ses="poor", age_bracket="adult", occupation="soldier") for i in range(10)]
    )
    # severity is pushed well above the normal 0.2-1.0 range so that the
    # poor/guard casualty rates saturate to (effectively) certainty; this
    # keeps the "at least one death occurs" assertion deterministic instead
    # of depending on this specific seed's draws clearing a <=1% threshold
    # across a population this small.
    skirmishes = [{"_db_id": 1, "skirmish_date": "1300-06-01", "severity": 500.0}]
    deaths = generate_skirmish_casualties(("town", 1), residents, skirmishes, reporting_building_id=99)

    resident_by_id = {r["db_id"]: r for r in residents}
    assert len(deaths) > 0
    for death in deaths:
        resident = resident_by_id[death["resident_db_id"]]
        is_guard = resident["occupation"] in MILITARY_OCCUPATIONS
        is_poor_adult = resident["ses"] == "poor" and resident["age_bracket"] == "adult"
        assert is_guard or is_poor_adult
        assert resident["age_bracket"] != "child"


def test_no_reporting_building_means_no_casualties():
    residents = [_resident(i, ses="poor", age_bracket="adult") for i in range(500)]
    skirmishes = [{"_db_id": 1, "skirmish_date": "1300-06-01", "severity": 1.0}]
    deaths = generate_skirmish_casualties(("town", 1), residents, skirmishes, reporting_building_id=None)
    assert deaths == []


def test_a_resident_who_already_died_is_never_a_casualty():
    resident = _resident(1, ses="poor", age_bracket="adult", death_date="1299-05-01")
    skirmishes = [{"_db_id": 1, "skirmish_date": "1300-06-01", "severity": 1.0}]
    deaths = generate_skirmish_casualties(("town", 1), [resident], skirmishes, reporting_building_id=99)
    assert deaths == []


def test_casualty_records_reference_the_correct_skirmish_and_building():
    residents = [_resident(i, occupation="guard") for i in range(50)]
    # see the saturating-severity note above: 500.0 makes the >0 assertion
    # deterministic rather than seed-dependent.
    skirmishes = [{"_db_id": 7, "skirmish_date": "1300-06-01", "severity": 500.0}]
    deaths = generate_skirmish_casualties(("town", 1), residents, skirmishes, reporting_building_id=42)
    assert len(deaths) > 0
    for death in deaths:
        assert death["skirmish_event_id"] == 7
        assert death["reported_by_building_id"] == 42
        assert death["cause"] == "skirmish"


def test_casualties_mutate_resident_death_date_in_place():
    residents = [_resident(i, occupation="guard") for i in range(50)]
    # see the saturating-severity note above: 500.0 makes the >0 assertion
    # deterministic rather than seed-dependent.
    skirmishes = [{"_db_id": 1, "skirmish_date": "1300-06-01", "severity": 500.0}]
    deaths = generate_skirmish_casualties(("town", 1), residents, skirmishes, reporting_building_id=99)
    assert len(deaths) > 0
    dead_ids = {d["resident_db_id"] for d in deaths}
    for resident in residents:
        if resident["db_id"] in dead_ids:
            assert resident["death_date"] == "1300-06-01"
        else:
            assert resident["death_date"] is None
