# tests/test_db_households.py
from datetime import date

from town_shaper.models import Household, ResidentSlot, SES, Town
from town_db.households import (
    DEFAULT_INTERMARRIAGE_RATE,
    NOBLE_POPULATION_RATIO,
    build_households_and_residents,
)

REFERENCE_DATE = date(1300, 1, 1)


def _make_town(residents):
    town = Town(seed=("town", 1), target_population=len(residents), bounds=(-10.0, -10.0, 10.0, 10.0))
    town.residents = residents
    return town


def test_build_households_and_residents_produces_one_household_per_group():
    residents = [
        ResidentSlot(id=0, household_id=1, ses=SES.POOR, age_bracket="adult"),
        ResidentSlot(id=1, household_id=1, ses=SES.POOR, age_bracket="adult"),
        ResidentSlot(id=2, household_id=1, ses=SES.POOR, age_bracket="child"),
        ResidentSlot(id=3, household_id=2, ses=SES.RICH, age_bracket="adult"),
    ]
    town = _make_town(residents)
    households, enriched = build_households_and_residents(town, ("town", 1), REFERENCE_DATE)

    assert {h["id"] for h in households} == {1, 2}
    assert len(enriched) == 4
    assert {r["household_id"] for r in enriched} == {1, 2}


def test_household_members_share_a_surname_and_usually_share_a_race():
    residents = [
        ResidentSlot(id=0, household_id=1, ses=SES.POOR, age_bracket="adult"),
        ResidentSlot(id=1, household_id=1, ses=SES.POOR, age_bracket="adult"),
        ResidentSlot(id=2, household_id=1, ses=SES.POOR, age_bracket="child"),
    ]
    town = _make_town(residents)
    households, enriched = build_households_and_residents(
        town, ("town", 1), REFERENCE_DATE, intermarriage_rate=0.0
    )
    surnames = {r["last_name"] for r in enriched}
    races = {r["race"] for r in enriched}
    assert len(surnames) == 1
    assert len(races) == 1  # intermarriage_rate=0.0 guarantees a single-race household


def test_build_households_and_residents_is_deterministic():
    residents = [
        ResidentSlot(id=i, household_id=i // 3, ses=SES.POOR, age_bracket="adult")
        for i in range(9)
    ]
    town = _make_town(residents)
    _, enriched1 = build_households_and_residents(town, ("town", 1), REFERENCE_DATE)
    _, enriched2 = build_households_and_residents(town, ("town", 1), REFERENCE_DATE)
    key = lambda r: (r["household_id"], r["first_name"], r["race"], r["birth_date"])
    assert [key(r) for r in enriched1] == [key(r) for r in enriched2]


def test_nobility_is_tagged_at_roughly_the_expected_ratio_and_only_rich_adults():
    target_population = 2000
    residents = [
        ResidentSlot(id=i, household_id=i, ses=SES.RICH, age_bracket="adult")
        for i in range(50)
    ] + [
        ResidentSlot(id=100 + i, household_id=100 + i, ses=SES.POOR, age_bracket="adult")
        for i in range(50)
    ]
    town = Town(seed=("town", 1), target_population=target_population, bounds=(-10.0, -10.0, 10.0, 10.0))
    town.residents = residents
    _, enriched = build_households_and_residents(town, ("town", 1), REFERENCE_DATE)

    nobles = [r for r in enriched if r["is_noble"]]
    expected = round(target_population / NOBLE_POPULATION_RATIO)
    assert len(nobles) == min(expected, 50)
    assert all(r["ses"] == "rich" for r in nobles)
