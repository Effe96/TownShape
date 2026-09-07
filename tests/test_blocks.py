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
    # Jittered leaf splits (see _split_polygon) produce non-rectangular leaves
    # whose OBB-derived footprint can overshoot the leaf itself -- a wider
    # buffer than a rectangular-leaf split needs, but still a bounded overshoot.
    block_shape = ShapelyPolygon(block).buffer(2.0)
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

    # Every urban building has a real footprint polygon (Task 8+) and
    # finish_leaves guarantees leaves never overlap, so check the real
    # footprint rather than the OBB approximation (which can over-cover a
    # non-rectangular leaf) -- and expect near-zero overlap, not a loose
    # fraction.
    shapes = [ShapelyPolygon(b.footprint) if b.footprint else _footprint_shape(b) for b in buildings]
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            overlap = shapes[i].intersection(shapes[j]).area
            assert overlap < 1e-6


def test_leaf_footprint_never_over_covers_a_non_rectangular_leaf():
    # The footprint comes from the leaf's minimum rotated rectangle, which for
    # any non-rectangular leaf strictly over-covers it -- a triangle's OBB is
    # exactly twice its area. The reported footprint must match the leaf's real
    # area instead, or neighbouring buildings overlap and spill out of the block.
    from town_shaper.blocks import _leaf_footprint

    triangle = [(0.0, 0.0), (20.0, 0.0), (0.0, 10.0)]  # area 100, OBB area 200
    _cx, _cy, width, height, _rotation = _leaf_footprint(triangle)

    assert math.isclose(width * height, 100.0, rel_tol=1e-9)


def test_place_buildings_in_non_rectangular_block_fit_and_dont_overlap():
    # A non-rectangular block subdivides into non-rectangular leaves (triangles,
    # trapezoids), whose OBB over-covers them. Post-scaling the footprints no
    # longer over-cover, so none of them overlap and their total stays under the
    # block's own area.
    #
    # Known ceiling: the footprint is still centred on the leaf's OBB centre,
    # which for a concave leaf can sit in the leaf's own notch, so an individual
    # footprint may still sit partly outside the block -- hence the generous
    # buffer below rather than an exact containment assertion. Tightening that
    # means abandoning the OBB centre entirely, which moves every building in
    # every town; not worth it for the residual.
    from town_shaper.blocks import place_buildings_in_block

    l_shape = [(0.0, 0.0), (40.0, 0.0), (40.0, 20.0), (20.0, 20.0), (20.0, 40.0), (0.0, 40.0)]
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 12)

    buildings = place_buildings_in_block(
        l_shape, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    assert len(buildings) > 1
    block = ShapelyPolygon(l_shape)
    shapes = [_footprint_shape(b) for b in buildings]

    assert sum(s.area for s in shapes) <= block.area
    roomy_block = block.buffer(5.0)
    for shape in shapes:
        assert roomy_block.contains(shape)
    # Same real-footprint check as the rectangular-block overlap test above:
    # finish_leaves guarantees leaves never overlap, so real footprints
    # (rather than the OBB approximation, which over-covers non-rectangular
    # leaves) should show near-zero overlap.
    real_shapes = [ShapelyPolygon(b.footprint) if b.footprint else s for b, s in zip(buildings, shapes)]
    for i in range(len(real_shapes)):
        for j in range(i + 1, len(real_shapes)):
            overlap = real_shapes[i].intersection(real_shapes[j]).area
            assert overlap < 1e-6


def test_place_buildings_in_block_rotations_vary_for_a_rectangular_block():
    # Was "...stays_axis_aligned..." -- the old clean OBB-perpendicular
    # split kept every leaf's rotation at a multiple of 90 degrees. The
    # jittered split (this task) is specifically meant to break that.
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 12)

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    assert buildings

    def is_axis_aligned(rotation):
        remainder = abs(rotation) % (math.pi / 2)
        return remainder < 1e-6 or (math.pi / 2 - remainder) < 1e-6

    assert any(not is_axis_aligned(b.rotation) for b in buildings)


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


def test_split_polygon_angle_varies_across_calls():
    # The old clean OBB-perpendicular split always cut along the same axis
    # (a grid-like result); the jittered version should vary the cut angle
    # from one call to the next given different rng draws.
    from town_shaper.blocks import _split_polygon

    square = _square(40.0)
    rng1 = rng_for(("town", 1), "split-test", 1)
    rng2 = rng_for(("town", 1), "split-test", 2)

    side_a1, _ = _split_polygon(square, rng1, gap=0.4)
    side_a2, _ = _split_polygon(square, rng2, gap=0.4)

    # Different rng streams should not produce byte-identical first halves
    # (a purely-fixed-axis split would, since the split line's angle
    # never varies regardless of rng).
    assert side_a1 != side_a2


def test_split_polygon_still_conserves_area_within_the_gap():
    from town_shaper.blocks import _split_polygon

    square = _square(40.0)
    rng = rng_for(("town", 1), "split-test", 3)
    side_a, side_b = _split_polygon(square, rng, gap=0.4)

    original_area = polygon_area(square)
    total = polygon_area(side_a) + polygon_area(side_b)
    assert total <= original_area
    assert total >= original_area * 0.85  # gap only removes a thin strip


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


def test_compute_district_blocks_covers_every_polygon_part():
    from town_shaper.blocks import compute_district_blocks

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(40.0, 20.0), _rectangle(30.0, 15.0)])
    blocks = compute_district_blocks(district, ("town", 1))
    assert len(blocks) > 0


def test_compute_district_blocks_is_deterministic():
    from town_shaper.blocks import compute_district_blocks

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(60.0, 60.0)])
    blocks1 = compute_district_blocks(district, ("town", 1))
    blocks2 = compute_district_blocks(district, ("town", 1))
    assert [sorted(b) for b in blocks1] == [sorted(b) for b in blocks2]


def test_compute_district_blocks_stays_within_the_original_district_polygon():
    from shapely.geometry import Polygon as ShapelyPolygon

    from town_shaper.blocks import compute_district_blocks

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(60.0, 60.0)])
    blocks = compute_district_blocks(district, ("town", 1))

    original = ShapelyPolygon(_rectangle(60.0, 60.0))
    for block in blocks:
        # jaggify_polygon's max_absolute_offset keeps the perturbed inset
        # boundary from bleeding past the original district edge -- a
        # small buffer absorbs floating-point/clip slack, not design slack.
        assert original.buffer(0.5).contains(ShapelyPolygon(block))


def test_organic_subdivide_never_exceeds_the_hard_cap():
    from town_shaper.blocks import organic_subdivide

    large_square = _square(100.0)  # area 10000
    target_area = 50.0
    hard_cap = 200.0
    rng = rng_for(("town", 1), "organic-test", 1)

    leaves = organic_subdivide(large_square, target_area, hard_cap, rng)

    assert len(leaves) > 1
    for leaf in leaves:
        assert polygon_area(leaf) <= hard_cap + 1e-6


def test_organic_subdivide_returns_original_when_already_small():
    from town_shaper.blocks import organic_subdivide

    small_square = _square(5.0)  # area 25, under any reasonable target
    rng = rng_for(("town", 1), "organic-test", 2)

    leaves = organic_subdivide(small_square, target_area=100.0, hard_cap_area=400.0, rng=rng)

    assert leaves == [small_square]


def test_organic_subdivide_forces_a_split_above_the_hard_cap_even_if_near_target():
    # A polygon whose area sits between target_area and hard_cap_area could
    # randomly sample a stop_area above its own area and stop immediately
    # under the old design -- but once area exceeds hard_cap_area outright,
    # it must always keep splitting regardless of the soft sample.
    from town_shaper.blocks import organic_subdivide

    square = _square(20.0)  # area 400
    rng = rng_for(("town", 1), "organic-test", 3)

    leaves = organic_subdivide(square, target_area=50.0, hard_cap_area=300.0, rng=rng)

    assert len(leaves) > 1
    for leaf in leaves:
        assert polygon_area(leaf) <= 300.0 + 1e-6


def test_organic_subdivide_is_deterministic():
    from town_shaper.blocks import organic_subdivide

    large_square = _square(100.0)
    rng1 = rng_for(("town", 1), "organic-test", 4)
    leaves1 = organic_subdivide(large_square, 50.0, 200.0, rng1)
    rng2 = rng_for(("town", 1), "organic-test", 4)
    leaves2 = organic_subdivide(large_square, 50.0, 200.0, rng2)

    assert [sorted(leaf) for leaf in leaves1] == [sorted(leaf) for leaf in leaves2]


def test_organic_subdivide_keeps_splitting_past_max_depth_when_must_split():
    # A hard_cap_area small enough relative to the starting polygon that
    # getting every leaf under it takes more than max_depth splits: with
    # area 10000 and hard_cap_area 625, four halvings (10000 -> 5000 ->
    # 2500 -> 1250 -> 625) are needed, but max_depth=2 caps recursion at
    # depth 2 (area still ~2500, far over the cap). must_split (area >
    # hard_cap_area) must force splitting to continue past max_depth --
    # the depth limit is documented as a soft-stop-only cap, not an
    # override of the hard-cap guarantee.
    from town_shaper.blocks import organic_subdivide

    large_square = _square(100.0)  # area 10000
    rng = rng_for(("town", 1), "organic-test", 10)

    leaves = organic_subdivide(large_square, target_area=50.0, hard_cap_area=625.0, rng=rng, max_depth=2)

    assert len(leaves) > 4  # more leaves than max_depth=2 (4) could produce alone
    for leaf in leaves:
        assert polygon_area(leaf) <= 625.0 + 1e-6


def _l_shape():
    # Concave L: a 40x40 square missing its 20x20 top-right quadrant, area 1200.
    return [(0.0, 0.0), (40.0, 0.0), (40.0, 20.0), (20.0, 20.0), (20.0, 40.0), (0.0, 40.0)]


def test_organic_subdivide_never_exceeds_the_hard_cap_on_a_concave_polygon():
    # Task 6's shipped hard-cap tests only exercised symmetric squares. A
    # concave polygon is more likely to make _split_polygon produce a
    # degenerate side (len < 3), which also makes organic_subdivide bail
    # out and return an oversized leaf unsplit -- a second, related way
    # the "never exceeds hard cap" guarantee can silently fail.
    from town_shaper.blocks import organic_subdivide

    l_shape = _l_shape()  # area 1200
    rng = rng_for(("town", 1), "organic-test", 11)

    leaves = organic_subdivide(l_shape, target_area=50.0, hard_cap_area=300.0, rng=rng)

    assert len(leaves) > 1
    for leaf in leaves:
        assert polygon_area(leaf) <= 300.0 + 1e-6


def test_notch_corner_never_increases_area():
    from town_shaper.blocks import notch_corner

    square = _square(20.0)
    rng = rng_for(("town", 1), "notch-test", 1)
    for i in range(20):  # sample several rng draws -- notch is probabilistic
        r = rng_for(("town", 1), "notch-test", i)
        result = notch_corner(square, r)
        assert polygon_area(result) <= polygon_area(square) + 1e-9


def test_notch_corner_is_deterministic():
    from town_shaper.blocks import notch_corner

    square = _square(20.0)
    rng1 = rng_for(("town", 1), "notch-test", 5)
    rng2 = rng_for(("town", 1), "notch-test", 5)
    assert notch_corner(square, rng1) == notch_corner(square, rng2)


def test_add_appendage_produces_a_simple_polygon_or_leaves_it_unchanged():
    from shapely.geometry import Polygon as ShapelyPolygon

    from town_shaper.blocks import add_appendage

    square = _square(20.0)
    for i in range(30):  # sample several draws -- appendage/curve are both probabilistic
        rng = rng_for(("town", 1), "appendage-test", i)
        result = add_appendage(square, rng)
        shape = ShapelyPolygon(result)
        assert shape.is_valid
        assert shape.geom_type == "Polygon"


def test_add_appendage_area_is_at_least_the_original():
    from town_shaper.blocks import add_appendage

    square = _square(20.0)
    for i in range(30):
        rng = rng_for(("town", 1), "appendage-test", 100 + i)
        result = add_appendage(square, rng)
        assert polygon_area(result) >= polygon_area(square) - 1e-9


def test_finish_leaves_never_produces_overlapping_footprints():
    # The Known Risk from the design spec: an appendage grown outward from
    # one leaf's edge could reach into a neighbouring leaf across the
    # narrow party-wall gap between them. finish_leaves must check every
    # candidate appendage against every sibling leaf in the same block and
    # skip it (not shrink it) if it would overlap.
    from shapely.geometry import Polygon as ShapelyPolygon

    from town_shaper.blocks import finish_leaves, organic_subdivide

    block = _rectangle(40.0, 20.0)
    rng = rng_for(("town", 1), "finish-test", 1)
    raw_leaves = organic_subdivide(block, target_area=30.0, hard_cap_area=120.0, rng=rng)

    finish_rng = rng_for(("town", 1), "finish-test", 2)
    finished = finish_leaves(raw_leaves, finish_rng)

    assert len(finished) == len(raw_leaves)
    shapes = [ShapelyPolygon(leaf) for leaf in finished]
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            assert shapes[i].intersection(shapes[j]).area < 1e-6


def test_finish_leaves_rejects_appendage_reaching_into_a_not_yet_processed_sibling(monkeypatch):
    # finish_leaves used to check a candidate appendage only against
    # ALREADY-finished siblings (those earlier in the list). A leaf
    # processed first could grow an appendage straight into a sibling
    # later in the list -- that later leaf's own overlap check (candidate
    # vs already-finished shapes) doesn't help, because when it falls back
    # to its un-grown "notched" self, that base body is what's actually
    # sitting inside the earlier leaf's appendage; nothing ever re-checks
    # it. Verified against a real generated town: 88-90 same-district
    # overlap pairs (worst pair 72.6% of the smaller footprint) at
    # pop=5000, seed=1, dropping to 0 once finish_leaves also checks a
    # candidate against every OTHER leaf's raw (pre-notch) shape --
    # a safe superset for a not-yet-decided sibling, computed with no
    # extra rng draw so consumption order/count is unaffected.
    import town_shaper.blocks as blocks_mod

    leaf_a = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    leaf_b = [(11.0, 0.0), (13.0, 0.0), (13.0, 10.0), (11.0, 10.0)]  # separate leaf, 1-unit gap from leaf_a

    def fake_add_appendage(polygon, rng):
        if list(polygon) == leaf_a:
            # Bulge leaf_a's right edge across the gap, into leaf_b's territory.
            return [(0.0, 0.0), (10.0, 0.0), (12.0, 3.0), (12.0, 7.0), (10.0, 10.0), (0.0, 10.0)]
        return polygon

    monkeypatch.setattr(blocks_mod, "notch_corner", lambda polygon, rng: polygon)
    monkeypatch.setattr(blocks_mod, "add_appendage", fake_add_appendage)

    rng = rng_for(("town", 1), "finish-lookahead-test", 1)
    finished = blocks_mod.finish_leaves([leaf_a, leaf_b], rng)

    shape_a = ShapelyPolygon(finished[0]).buffer(0)
    shape_b = ShapelyPolygon(finished[1]).buffer(0)
    assert shape_a.intersection(shape_b).area < 1e-6


def test_finish_leaves_is_deterministic():
    from town_shaper.blocks import finish_leaves, organic_subdivide

    block = _rectangle(40.0, 20.0)
    gen_rng = rng_for(("town", 1), "finish-test", 3)
    raw_leaves = organic_subdivide(block, target_area=30.0, hard_cap_area=120.0, rng=gen_rng)

    rng1 = rng_for(("town", 1), "finish-test", 4)
    finished1 = finish_leaves(raw_leaves, rng1)
    rng2 = rng_for(("town", 1), "finish-test", 4)
    finished2 = finish_leaves(raw_leaves, rng2)

    assert finished1 == finished2


def test_place_buildings_in_block_footprints_now_set_on_every_building():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(40.0, 20.0)
    district = _district(ZoneType.MERCHANT)
    rng = rng_for(("town", 1), "blocks-test", 30)

    buildings = place_buildings_in_block(
        block, district, rng, 0, target_population=3000, magic_prevalence=0.0, notable_building_counts={},
    )

    assert buildings
    for b in buildings:
        assert b.footprint is not None
        assert len(b.footprint) >= 3


def test_place_buildings_in_block_respects_a_caller_supplied_target_area():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(60.0, 60.0)  # area 3600
    district = _district(ZoneType.POOR_RESIDENTIAL)
    rng_small_target = rng_for(("town", 1), "blocks-test", 31)
    small_target = place_buildings_in_block(
        block, district, rng_small_target, 0, target_population=3000, magic_prevalence=0.0,
        notable_building_counts={}, target_area=30.0, hard_cap_area=200.0,
    )
    rng_large_target = rng_for(("town", 1), "blocks-test", 31)
    large_target = place_buildings_in_block(
        block, district, rng_large_target, 0, target_population=3000, magic_prevalence=0.0,
        notable_building_counts={}, target_area=900.0, hard_cap_area=3600.0,
    )

    # A much bigger target area should produce noticeably fewer buildings
    # from the same block.
    assert len(large_target) < len(small_target)


def test_generate_blocks_and_buildings_accepts_precomputed_blocks():
    from town_shaper.blocks import (
        DEFAULT_HARD_CAP_AREA, LOT_DEPTH_BY_ZONE, LOT_FRONTAGE_BY_ZONE,
        compute_district_blocks, generate_blocks_and_buildings,
    )

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(40.0, 20.0)])
    precomputed = compute_district_blocks(district, ("town", 1))

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
        blocks=precomputed, target_area=LOT_FRONTAGE_BY_ZONE[ZoneType.MERCHANT] * LOT_DEPTH_BY_ZONE[ZoneType.MERCHANT],
        hard_cap_area=DEFAULT_HARD_CAP_AREA,
    )

    assert len(buildings) > 0


def test_generate_blocks_and_buildings_footprints_dont_overlap_across_blocks():
    # Fix for the appendage-overlap Known Risk actually crossing block
    # boundaries: finish_leaves used to start a fresh `shapes` list per
    # block, so an appendage grown near a shared boundary between two
    # blocks of the same district could reach across it undetected.
    # generate_blocks_and_buildings now threads one accumulated shape list
    # across every block in the district (district_shapes ->
    # existing_shapes -> finish_leaves' seed_shapes), so two directly
    # adjacent blocks (touching, not gapped by an inset) must still produce
    # zero real-footprint overlap between buildings in different blocks.
    from town_shaper.blocks import generate_blocks_and_buildings

    block_a = _rectangle(40.0, 20.0)  # (0,0)-(40,20)
    block_b = [(40.0, 0.0), (80.0, 0.0), (80.0, 20.0), (40.0, 20.0)]  # touches block_a at x=40
    district = _multi_part_district(ZoneType.POOR_RESIDENTIAL, [block_a, block_b])

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
        blocks=[block_a, block_b], target_area=30.0, hard_cap_area=120.0,
    )

    assert len(buildings) > 1
    shapes = [ShapelyPolygon(b.footprint) for b in buildings if b.footprint]
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            assert shapes[i].intersection(shapes[j]).area < 1e-6


def test_generate_blocks_and_buildings_culls_some_residential_leaves_as_gardens():
    from town_shaper.blocks import compute_district_blocks, generate_blocks_and_buildings

    district = _multi_part_district(ZoneType.POOR_RESIDENTIAL, [_rectangle(80.0, 80.0)])
    blocks = compute_district_blocks(district, ("town", 1))

    # A small target_area forces many leaves from an 80x80 block -- with
    # GARDEN_CULL_FRACTION > 0, the building count should land measurably
    # below the raw leaf count organic_subdivide alone would produce.
    from town_shaper.blocks import DEFAULT_HARD_CAP_AREA, organic_subdivide

    rng_probe = rng_for(("town", 1), "blocks", district.id)
    raw_leaf_count = sum(
        len(organic_subdivide(b, target_area=40.0, hard_cap_area=DEFAULT_HARD_CAP_AREA, rng=rng_probe))
        for b in blocks
    )

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
        blocks=blocks, target_area=40.0, hard_cap_area=DEFAULT_HARD_CAP_AREA,
    )

    assert 0 < len(buildings) < raw_leaf_count


def test_generate_blocks_and_buildings_does_not_cull_merchant_leaves():
    from town_shaper.blocks import DEFAULT_HARD_CAP_AREA, compute_district_blocks, generate_blocks_and_buildings, organic_subdivide, finish_leaves

    district = _multi_part_district(ZoneType.MERCHANT, [_rectangle(80.0, 80.0)])
    blocks = compute_district_blocks(district, ("town", 1))

    rng_probe = rng_for(("town", 1), "blocks", district.id)
    raw_leaf_count = sum(
        len(finish_leaves(organic_subdivide(b, target_area=40.0, hard_cap_area=DEFAULT_HARD_CAP_AREA, rng=rng_probe), rng=rng_probe))
        for b in blocks
    )

    buildings = generate_blocks_and_buildings(
        district, ("town", 1), next_building_id=0, target_population=3000, magic_prevalence=0.0,
        blocks=blocks, target_area=40.0, hard_cap_area=DEFAULT_HARD_CAP_AREA,
    )

    # Merchant/civic/port are NOT culled -- every generated leaf (except slivers)
    # becomes a building (named or infill).
    assert len(buildings) >= raw_leaf_count - 1


def test_organic_subdivide_respects_a_caller_supplied_gap_range():
    from town_shaper.blocks import organic_subdivide

    large_square = _square(100.0)  # area 10000
    rng_narrow = rng_for(("town", 1), "gap-test", 1)
    narrow_leaves = organic_subdivide(
        large_square, target_area=50.0, hard_cap_area=200.0, rng=rng_narrow, gap_range=(0.25, 0.6),
    )
    rng_wide = rng_for(("town", 1), "gap-test", 1)
    wide_leaves = organic_subdivide(
        large_square, target_area=50.0, hard_cap_area=200.0, rng=rng_wide, gap_range=(2.0, 4.0),
    )

    # A wider party-wall gap eats more area per split -- with the identical
    # seed and identical split decisions, total leaf area must be smaller
    # under the wider gap.
    total_narrow_area = sum(polygon_area(leaf) for leaf in narrow_leaves)
    total_wide_area = sum(polygon_area(leaf) for leaf in wide_leaves)
    assert total_wide_area < total_narrow_area


def test_place_buildings_in_block_uses_a_wider_gap_for_residential_zones():
    from town_shaper.blocks import place_buildings_in_block

    block = _rectangle(60.0, 60.0)  # area 3600
    poor_district = _district(ZoneType.POOR_RESIDENTIAL)
    merchant_district = _district(ZoneType.MERCHANT)

    rng_poor = rng_for(("town", 1), "gap-test", 2)
    poor_buildings = place_buildings_in_block(
        block, poor_district, rng_poor, 0, target_population=3000, magic_prevalence=0.0,
        notable_building_counts={}, target_area=40.0, hard_cap_area=200.0,
    )
    rng_merchant = rng_for(("town", 1), "gap-test", 2)
    merchant_buildings = place_buildings_in_block(
        block, merchant_district, rng_merchant, 0, target_population=3000, magic_prevalence=0.0,
        notable_building_counts={}, target_area=40.0, hard_cap_area=200.0,
    )

    # Same seed, same block, same target/cap -- the only difference is zone
    # type, so the wider residential gap should leave measurably less total
    # building footprint area than the merchant path's narrow gap.
    poor_total_area = sum(polygon_area(b.footprint) for b in poor_buildings)
    merchant_total_area = sum(polygon_area(b.footprint) for b in merchant_buildings)
    assert poor_total_area < merchant_total_area
