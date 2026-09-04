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

    buildings = place_buildings_in_block(block, district, rng, 0, target_population=3000, magic_prevalence=0.0)

    assert len(buildings) > 0
    block_shape = ShapelyPolygon(block).buffer(0.5)  # small tolerance for footprints flush on the boundary
    for building in buildings:
        assert block_shape.contains(_footprint_shape(building))


def test_place_buildings_in_block_footprints_dont_overlap():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 11)

    buildings = place_buildings_in_block(block, district, rng, 0, target_population=3000, magic_prevalence=0.0)

    shapes = [_footprint_shape(b) for b in buildings]
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            assert shapes[i].intersection(shapes[j]).area < 1e-6


def test_place_buildings_in_block_rotation_matches_frontage_edge():
    from town_shaper.blocks import place_buildings_in_block

    # A 40x20 rectangle has two horizontal edges (bottom/top) and two
    # vertical edges (left/right) -- every building's rotation should land
    # in one of exactly two buckets, and both buckets should be populated
    # (not just one, which would mean rotation isn't actually tracking the
    # edge it was placed against).
    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 12)

    buildings = place_buildings_in_block(block, district, rng, 0, target_population=3000, magic_prevalence=0.0)

    horizontal = [b for b in buildings if math.isclose(abs(b.rotation) % math.pi, 0.0, abs_tol=1e-6)]
    vertical = [b for b in buildings if math.isclose(abs(b.rotation) % math.pi, math.pi / 2, abs_tol=1e-6)]
    assert horizontal
    assert vertical
    assert len(horizontal) + len(vertical) == len(buildings)


def test_place_buildings_in_block_is_deterministic():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)

    rng1 = rng_for(("town", 1), "blocks-test", 13)
    b1 = place_buildings_in_block(block, district, rng1, 0, target_population=3000, magic_prevalence=0.0)
    rng2 = rng_for(("town", 1), "blocks-test", 13)
    b2 = place_buildings_in_block(block, district, rng2, 0, target_population=3000, magic_prevalence=0.0)

    key = lambda buildings: [(b.x, b.y, b.width, b.height, b.rotation, b.building_type) for b in buildings]
    assert key(b1) == key(b2)


def test_place_buildings_in_block_density_multiplier_scales_lot_size():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)

    rng_sparse = rng_for(("town", 1), "blocks-test", 14)
    sparse = place_buildings_in_block(
        block, district, rng_sparse, 0, target_population=3000, magic_prevalence=0.0, density_multiplier=0.5,
    )
    rng_dense = rng_for(("town", 1), "blocks-test", 14)
    dense = place_buildings_in_block(
        block, district, rng_dense, 0, target_population=3000, magic_prevalence=0.0, density_multiplier=2.0,
    )

    assert len(dense) > len(sparse)


def test_place_buildings_in_block_skips_footprints_that_would_exit_a_narrow_block():
    from town_shaper.blocks import place_buildings_in_block

    # 80 long x 20 deep: long enough for a lot to clear the corner
    # skip_distance margin on the long edges (skip_distance=15.4, frontage=30
    # at density_multiplier=0.5, so 80 - 2*15.4 = 49.2 >= 30 -- one lot per
    # long edge), but the block's cross-dimension (20) is far shorter than
    # the inflated lot depth's inward reach at this density_multiplier
    # (depth/2 + footprint_half_height = 18 + 14.4 = 32.4), so a naive
    # lot-center placement pushes the footprint's far edge outside the
    # opposite long edge entirely.
    narrow_block = _rectangle(80.0, 20.0)
    district = _district(ZoneType.CIVIC)
    rng = rng_for(("town", 1), "blocks-test", 20)

    buildings = place_buildings_in_block(
        narrow_block, district, rng, 0, target_population=3000, magic_prevalence=0.0, density_multiplier=0.5,
    )

    block_shape = ShapelyPolygon(narrow_block).buffer(0.5)
    for building in buildings:
        assert block_shape.contains(_footprint_shape(building))


def _multi_part_district(zone_type, polygon_parts):
    anchor = Anchor(id=1, zone_type=zone_type, x=0.0, y=0.0)
    return District(id=1, zone_type=zone_type, anchor=anchor, polygon_parts=polygon_parts)


def test_generate_blocks_and_buildings_covers_every_polygon_part():
    from town_shaper.blocks import generate_blocks_and_buildings

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(40.0, 20.0), _rectangle(30.0, 15.0)])

    buildings, nodes, edges, next_node_id, next_edge_id = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, next_node_id=0, next_edge_id=0,
        target_population=3000, magic_prevalence=0.0,
    )

    assert len(buildings) > 0
    building_ids = [b.id for b in buildings]
    assert building_ids == sorted(building_ids)
    assert building_ids == list(range(len(buildings)))  # sequential, starting at next_building_id
    assert next_node_id >= 0
    assert next_edge_id >= 0
    # nodes/edges may be empty if both parts are already under target area,
    # but the counters must never regress.
    assert next_node_id >= len(nodes)
    assert next_edge_id >= len(edges)
