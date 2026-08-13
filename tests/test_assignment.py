from town_shaper.anchors import place_anchors
from town_shaper.assignment import assign_residents
from town_shaper.buildings import fill_district_buildings
from town_shaper.districts import build_districts
from town_shaper.households import generate_households


def _build_town_pieces(seed, target_population=3000):
    bounds = (-200.0, -200.0, 200.0, 200.0)
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
