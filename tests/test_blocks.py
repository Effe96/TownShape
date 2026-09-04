import math

from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.blocks import TARGET_BLOCK_AREA_BY_ZONE, subdivide_into_blocks
from town_shaper.geometry import polygon_area
from town_shaper.models import Anchor, District, ZoneType
from town_shaper.seeding import rng_for


def _square(side: float):
    return [(0.0, 0.0), (side, 0.0), (side, side), (0.0, side)]


def test_subdivide_into_blocks_returns_original_when_already_small():
    small_square = _square(5.0)  # area 25, well under any zone's target
    rng = rng_for(("town", 1), "blocks-test", 1)

    blocks = subdivide_into_blocks(small_square, ZoneType.MERCHANT, rng)

    assert blocks == [small_square]


def test_subdivide_into_blocks_respects_target_area():
    large_square = _square(100.0)  # area 10000
    target_area = TARGET_BLOCK_AREA_BY_ZONE[ZoneType.MERCHANT]
    rng = rng_for(("town", 1), "blocks-test", 2)

    blocks = subdivide_into_blocks(large_square, ZoneType.MERCHANT, rng)

    assert len(blocks) > 1
    for block in blocks:
        assert polygon_area(block) <= target_area


def test_subdivide_into_blocks_conserves_area_within_street_gaps():
    large_square = _square(100.0)
    rng = rng_for(("town", 1), "blocks-test", 3)

    blocks = subdivide_into_blocks(large_square, ZoneType.MERCHANT, rng)

    original_area = polygon_area(large_square)
    total_block_area = sum(polygon_area(b) for b in blocks)
    assert total_block_area <= original_area
    assert total_block_area >= original_area * 0.6


def test_subdivide_into_blocks_is_deterministic():
    large_square = _square(100.0)

    rng1 = rng_for(("town", 1), "blocks-test", 6)
    blocks1 = subdivide_into_blocks(large_square, ZoneType.MERCHANT, rng1)
    rng2 = rng_for(("town", 1), "blocks-test", 6)
    blocks2 = subdivide_into_blocks(large_square, ZoneType.MERCHANT, rng2)

    assert [sorted(b) for b in blocks1] == [sorted(b) for b in blocks2]


def _rectangle(width: float, height: float):
    return [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]


def _district(zone_type):
    anchor = Anchor(id=1, zone_type=zone_type, x=0.0, y=0.0)
    return District(id=1, zone_type=zone_type, anchor=anchor, polygon_parts=[])


def _footprint_shape(building):
    hw, hh = building.width / 2.0, building.height / 2.0
    cos_r, sin_r = math.cos(building.rotation), math.sin(building.rotation)
    corners = [
        (building.x + lx * cos_r - ly * sin_r, building.y + lx * sin_r + ly * cos_r)
        for lx, ly in [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    ]
    return ShapelyPolygon(corners)


def test_place_buildings_in_block_footprints_stay_within_the_block():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 10)

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    assert len(buildings) > 0
    block_shape = ShapelyPolygon(block).buffer(0.5)
    for building in buildings:
        assert block_shape.contains(_footprint_shape(building))


def test_place_buildings_in_block_footprints_dont_overlap():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 11)

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    shapes = [_footprint_shape(b) for b in buildings]
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            assert shapes[i].intersection(shapes[j]).area < 1e-6


def test_place_buildings_in_block_footprints_stay_axis_aligned_for_a_rectangular_block():
    # A recursive axis-perpendicular bisection of a rectangle should keep
    # every resulting leaf's rotation at 0 or 90 degrees relative to the
    # original block, regardless of how many times it's been split.
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 12)

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    assert buildings
    for b in buildings:
        remainder = abs(b.rotation) % (math.pi / 2)
        assert remainder < 1e-6 or (math.pi / 2 - remainder) < 1e-6


def test_place_buildings_in_block_is_deterministic():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)

    rng1 = rng_for(("town", 1), "blocks-test", 13)
    b1 = place_buildings_in_block(
        block, district, rng1, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )
    rng2 = rng_for(("town", 1), "blocks-test", 13)
    b2 = place_buildings_in_block(
        block, district, rng2, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    key = lambda buildings: [(b.x, b.y, b.width, b.height, b.rotation, b.building_type) for b in buildings]
    assert key(b1) == key(b2)


def test_place_buildings_in_block_density_multiplier_scales_building_count():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)

    rng_sparse = rng_for(("town", 1), "blocks-test", 14)
    sparse = place_buildings_in_block(
        block, district, rng_sparse, 0, target_population=3000, magic_prevalence=0.0,
        notable_building_counts={}, density_multiplier=0.5,
    )
    rng_dense = rng_for(("town", 1), "blocks-test", 14)
    dense = place_buildings_in_block(
        block, district, rng_dense, 0, target_population=3000, magic_prevalence=0.0,
        notable_building_counts={}, density_multiplier=2.0,
    )

    assert len(dense) > len(sparse)


def test_place_buildings_in_block_respects_notable_building_cap():
    from town_shaper.blocks import place_buildings_in_block
    from town_shaper.buildings import notable_building_cap

    block = _rectangle(60.0, 60.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 21)
    target_population = 3000
    cap = notable_building_cap("tavern", target_population)
    notable_building_counts = {"tavern": cap}

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=target_population, magic_prevalence=0.0,
        notable_building_counts=notable_building_counts,
    )

    assert all(b.building_type != "tavern" for b in buildings)
    assert notable_building_counts["tavern"] == cap


def test_place_buildings_in_block_uses_infill_type_once_all_named_types_are_capped():
    from town_shaper.blocks import place_buildings_in_block
    from town_shaper.buildings import BUILDING_TYPES_BY_ZONE, INFILL_BUILDING_TYPE_BY_ZONE, notable_building_cap

    block = _rectangle(60.0, 60.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 22)
    target_population = 3000
    notable_building_counts = {
        bt: notable_building_cap(bt, target_population) for bt in BUILDING_TYPES_BY_ZONE[ZoneType.MERCHANT]
    }

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=target_population, magic_prevalence=0.0,
        notable_building_counts=notable_building_counts,
    )

    assert buildings
    infill_type = INFILL_BUILDING_TYPE_BY_ZONE[ZoneType.MERCHANT]
    assert all(b.building_type == infill_type for b in buildings)
    assert all(b.name is None for b in buildings)
    assert all(b.capacity == 0 for b in buildings)


def _multi_part_district(zone_type, polygon_parts):
    anchor = Anchor(id=1, zone_type=zone_type, x=0.0, y=0.0)
    return District(id=1, zone_type=zone_type, anchor=anchor, polygon_parts=polygon_parts)


def test_generate_blocks_and_buildings_covers_every_polygon_part():
    from town_shaper.blocks import generate_blocks_and_buildings

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(40.0, 20.0), _rectangle(30.0, 15.0)])

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
    )

    assert len(buildings) > 0
    building_ids = [b.id for b in buildings]
    assert building_ids == sorted(building_ids)
    assert building_ids == list(range(len(buildings)))


def test_generate_blocks_and_buildings_insets_away_from_the_district_boundary():
    from shapely.geometry import Point, Polygon as ShapelyPolygon

    from town_shaper.blocks import DISTRICT_INSET_DISTANCE, generate_blocks_and_buildings

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(60.0, 60.0)])

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
    )

    assert buildings
    original_boundary = ShapelyPolygon(_rectangle(60.0, 60.0)).boundary
    for building in buildings:
        assert Point(building.x, building.y).distance(original_boundary) >= DISTRICT_INSET_DISTANCE - 0.5


def test_generate_blocks_and_buildings_shares_notable_building_counts_across_parts():
    from town_shaper.blocks import generate_blocks_and_buildings
    from town_shaper.buildings import notable_building_cap

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(60.0, 60.0), _rectangle(60.0, 60.0)])
    target_population = 3000
    notable_building_counts = {}

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=target_population,
        magic_prevalence=0.0, notable_building_counts=notable_building_counts,
    )

    assert buildings
    tavern_count = sum(1 for b in buildings if b.building_type == "tavern")
    assert tavern_count <= notable_building_cap("tavern", target_population)
    assert notable_building_counts.get("tavern", 0) == tavern_count
