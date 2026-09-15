from town_shaper.models import (
    Anchor, Building, District, Household, JobVacancy,
    ResidentSlot, SES, Town, ZoneType,
)


def test_zone_type_has_seven_members():
    assert {z.value for z in ZoneType} == {
        "civic", "merchant", "rich_residential", "poor_residential", "farmland_edge", "port", "park",
    }


def test_ses_has_exactly_two_tiers_matching_residential_zones():
    assert {s.value for s in SES} == {"rich", "poor"}


def test_building_defaults_to_empty_vacancies_and_residents():
    building = Building(
        id=1, district_id=1, district_zone_type=ZoneType.POOR_RESIDENTIAL,
        x=0.0, y=0.0, building_type="residence", capacity=6,
    )
    assert building.vacancies == []
    assert building.resident_ids == []


def test_district_defaults_to_empty_buildings():
    anchor = Anchor(id=1, zone_type=ZoneType.CIVIC, x=0.0, y=0.0)
    district = District(id=1, zone_type=ZoneType.CIVIC, anchor=anchor, polygon_parts=[[(0.0, 0.0)]])
    assert district.buildings == []


def test_town_defaults_to_empty_districts_and_residents():
    town = Town(seed=(1,), target_population=100, bounds=(-10.0, -10.0, 10.0, 10.0))
    assert town.districts == []
    assert town.residents == []


def test_resident_slot_starts_unassigned():
    resident = ResidentSlot(id=1, household_id=1, ses=SES.POOR, age_bracket="adult")
    assert resident.home_building_id is None
    assert resident.workplace_building_id is None
    assert resident.occupation is None


def test_building_footprint_defaults_to_none():
    building = Building(
        id=1, district_id=1, district_zone_type=ZoneType.POOR_RESIDENTIAL,
        x=0.0, y=0.0, building_type="residence", capacity=6,
    )
    assert building.footprint is None


def test_building_accepts_an_explicit_footprint():
    footprint = [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)]
    building = Building(
        id=1, district_id=1, district_zone_type=ZoneType.POOR_RESIDENTIAL,
        x=2.5, y=2.5, building_type="residence", capacity=6, footprint=footprint,
    )
    assert building.footprint == footprint
