# tests/test_buildings.py
from town_shaper.buildings import fill_district_buildings, poisson_disc_fill
from town_shaper.geometry import distance, point_in_polygon
from town_shaper.models import Anchor, District, ZoneType
from town_shaper.seeding import rng_for


def _square_district(zone_type, side=40.0, district_id=1):
    anchor = Anchor(id=district_id, zone_type=zone_type, x=side / 2, y=side / 2)
    polygon = [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]
    return District(id=district_id, zone_type=zone_type, anchor=anchor, polygon=polygon)


def test_poisson_disc_fill_respects_min_spacing_and_polygon():
    polygon = [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)]
    rng = rng_for(("town", 1), "test-poisson")
    points = poisson_disc_fill(polygon, target_count=20, min_spacing=5.0, rng=rng)

    assert len(points) > 0
    for p in points:
        assert point_in_polygon(p, polygon)
    for i, p in enumerate(points):
        for q in points[i + 1:]:
            assert distance(p, q) >= 5.0


def test_poisson_disc_fill_returns_fewer_points_when_polygon_is_too_small():
    tiny_polygon = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
    rng = rng_for(("town", 1), "test-poisson-tiny")
    points = poisson_disc_fill(tiny_polygon, target_count=100, min_spacing=5.0, rng=rng)
    assert len(points) < 100


def test_fill_district_buildings_places_buildings_inside_district():
    district = _square_district(ZoneType.POOR_RESIDENTIAL)
    buildings = fill_district_buildings(district, ("town", 1), next_building_id=0)

    assert len(buildings) > 0
    for building in buildings:
        assert point_in_polygon((building.x, building.y), district.polygon)
        assert building.district_id == district.id
        assert building.district_zone_type == ZoneType.POOR_RESIDENTIAL


def test_fill_district_buildings_creates_vacancies_matching_building_type():
    from town_shaper.buildings import JOB_VACANCIES_BY_BUILDING_TYPE

    district = _square_district(ZoneType.MERCHANT)
    buildings = fill_district_buildings(district, ("town", 1), next_building_id=0)

    for building in buildings:
        expected = JOB_VACANCIES_BY_BUILDING_TYPE[building.building_type]
        expected_total = sum(count for _, count in expected)
        assert len(building.vacancies) == expected_total
        for vacancy in building.vacancies:
            assert vacancy.building_id == building.id
            assert vacancy.filled_by is None


def test_fill_district_buildings_is_deterministic():
    district = _square_district(ZoneType.RICH_RESIDENTIAL)
    first = fill_district_buildings(district, ("town", 1), next_building_id=0)
    second = fill_district_buildings(district, ("town", 1), next_building_id=0)
    assert [(b.id, b.x, b.y, b.building_type) for b in first] == \
           [(b.id, b.x, b.y, b.building_type) for b in second]
