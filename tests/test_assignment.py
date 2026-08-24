from town_shaper.anchors import place_anchors
from town_shaper.assignment import ZONE_TYPE_BY_SES, assign_residents
from town_shaper.buildings import fill_district_buildings
from town_shaper.districts import build_districts
from town_shaper.generate import compute_town_bounds, generate_town
from town_shaper.households import generate_households
from town_shaper.models import Anchor, Building, District, Household, SES, ZoneType


def _build_town_pieces(seed, target_population=3000):
    # Scale bounds with target_population the same way generate_town does,
    # so building density calibration (BUILDING_DENSITY_PER_AREA) — tuned
    # against real town-scale bounds — isn't starved by an undersized fixed
    # test area.
    bounds = compute_town_bounds(target_population)
    anchors = place_anchors(seed, target_population, bounds)
    districts = build_districts(anchors, bounds)

    next_id = 0
    for district in districts:
        buildings = fill_district_buildings(district, seed, next_id)
        district.buildings = buildings
        next_id += len(buildings)

    households = generate_households(seed, target_population)
    return districts, households


def test_assign_residents_never_exceeds_building_capacity():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed)
    assign_residents(seed, households, districts)

    for district in districts:
        for building in district.buildings:
            if building.capacity > 0:
                assert len(building.resident_ids) <= building.capacity


def test_assign_residents_never_double_fills_a_vacancy():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed)
    residents = assign_residents(seed, households, districts)

    filled_workplaces = [r.workplace_building_id for r in residents if r.workplace_building_id is not None]
    all_vacancies = [v for d in districts for b in d.buildings for v in b.vacancies]
    filled_vacancies = [v for v in all_vacancies if v.filled_by is not None]
    assert len(filled_vacancies) == len(filled_workplaces)
    assert len({v.filled_by for v in filled_vacancies}) == len(filled_vacancies)


def test_assign_residents_working_residents_have_occupation_matching_a_real_vacancy_type():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed)
    residents = assign_residents(seed, households, districts)

    vacancy_by_building = {}
    for d in districts:
        for b in d.buildings:
            vacancy_by_building[b.id] = {v.occupation for v in b.vacancies}

    for resident in residents:
        if resident.workplace_building_id is not None:
            assert resident.occupation in vacancy_by_building[resident.workplace_building_id]


def test_assign_residents_is_deterministic():
    seed = ("town", 1)
    districts1, households1 = _build_town_pieces(seed)
    residents1 = assign_residents(seed, households1, districts1)

    districts2, households2 = _build_town_pieces(seed)
    residents2 = assign_residents(seed, households2, districts2)

    key = lambda r: (r.id, r.household_id, r.ses, r.age_bracket, r.home_building_id, r.workplace_building_id, r.occupation)
    assert [key(r) for r in residents1] == [key(r) for r in residents2]


def test_assign_residents_children_never_get_a_workplace():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed)
    residents = assign_residents(seed, households, districts)

    for resident in residents:
        if resident.age_bracket == "child":
            assert resident.workplace_building_id is None


def test_assign_residents_realizes_close_to_target_population():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed, target_population=3000)
    residents = assign_residents(seed, households, districts)

    target_total = sum(1 + (1 if h.has_spouse else 0) + h.child_count for h in households)
    assert len(residents) >= 0.95 * target_total


def test_assign_residents_no_household_is_partially_dropped_when_a_home_exists():
    seed = ("town", 1)
    anchor = Anchor(id=1, zone_type=ZoneType.POOR_RESIDENTIAL, x=0.0, y=0.0)
    polygon = [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)]
    district = District(id=1, zone_type=ZoneType.POOR_RESIDENTIAL, anchor=anchor, polygon=polygon)
    big_home = Building(
        id=1, district_id=1, district_zone_type=ZoneType.POOR_RESIDENTIAL,
        x=20.0, y=20.0, building_type="residence", capacity=8,
    )
    district.buildings = [big_home]

    household = Household(id=1, has_spouse=True, child_count=4)
    residents = assign_residents(seed, [household], [district])

    assert len(residents) == 6  # 2 adults + 4 children
    for resident in residents:
        assert resident.home_building_id is not None


def test_assign_residents_ses_drift_is_observable():
    seed = ("town", 1)
    town = generate_town(seed, target_population=3000)
    districts = town.districts
    residents = town.residents

    building_by_id = {b.id: b for d in districts for b in d.buildings}
    residents_with_homes = [r for r in residents if r.home_building_id is not None]

    def is_drifted(resident):
        zone = building_by_id[resident.home_building_id].district_zone_type
        expected_zone = ZONE_TYPE_BY_SES[resident.ses]
        if zone == expected_zone:
            return False
        if resident.ses.value == "poor" and zone == ZoneType.FARMLAND_EDGE:
            return False
        return True

    drifted_count = sum(1 for r in residents_with_homes if is_drifted(r))
    assert 0 < drifted_count < 0.15 * len(residents_with_homes)


def test_assign_residents_default_rich_proportion_matches_previous_hardcoded_value():
    seed = ("town", 1)
    districts1, households1 = _build_town_pieces(seed, target_population=3000)
    residents_default = assign_residents(seed, households1, districts1)

    districts2, households2 = _build_town_pieces(seed, target_population=3000)
    residents_explicit = assign_residents(seed, households2, districts2, rich_proportion=0.05)

    key = lambda r: (r.id, r.household_id, r.ses, r.age_bracket, r.home_building_id, r.workplace_building_id, r.occupation)
    assert [key(r) for r in residents_default] == [key(r) for r in residents_explicit]


def test_assign_residents_high_rich_proportion_produces_majority_rich_residents():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed, target_population=3000)
    residents = assign_residents(seed, households, districts, rich_proportion=0.9)
    rich_count = sum(1 for r in residents if r.ses == SES.RICH)
    assert rich_count > 0.5 * len(residents)


def test_assign_residents_zero_rich_proportion_produces_no_rich_residents():
    seed = ("town", 1)
    districts, households = _build_town_pieces(seed, target_population=3000)
    residents = assign_residents(seed, households, districts, rich_proportion=0.0)
    assert all(r.ses == SES.POOR for r in residents)
