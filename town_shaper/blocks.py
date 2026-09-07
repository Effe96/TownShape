import math
from typing import Dict, List, Optional, Tuple

from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.buildings import (
    BUILDING_HOME_CAPACITY, BUILDING_NAME_POOLS, JOB_VACANCIES_BY_BUILDING_TYPE, pick_building_type_with_cap,
)
from town_shaper.geometry import clip_polygon_by_line, distance, inset_polygon, jaggify_polygon, polygon_area
from town_shaper.models import Building, District, JobVacancy, ZoneType
from town_shaper.seeding import rng_for

TARGET_BLOCK_AREA_BY_ZONE: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 2000.0,
    ZoneType.MERCHANT: 600.0,
    ZoneType.RICH_RESIDENTIAL: 1500.0,
    ZoneType.POOR_RESIDENTIAL: 250.0,
    ZoneType.PORT: 600.0,
}
LOT_FRONTAGE_BY_ZONE: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 15.0,
    ZoneType.MERCHANT: 8.0,
    ZoneType.RICH_RESIDENTIAL: 12.0,
    ZoneType.POOR_RESIDENTIAL: 5.0,
    ZoneType.PORT: 8.0,
}
LOT_DEPTH_BY_ZONE: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 18.0,
    ZoneType.MERCHANT: 10.0,
    ZoneType.RICH_RESIDENTIAL: 15.0,
    ZoneType.POOR_RESIDENTIAL: 6.0,
    ZoneType.PORT: 10.0,
}
LOCAL_STREET_WIDTH = 4.0
DISTRICT_INSET_DISTANCE = 2.0
MAX_SPLIT_DEPTH = 8

Point = Tuple[float, float]
Polygon = List[Point]


def _longer_axis_direction(polygon: Polygon) -> Point:
    """Unit vector along the longer axis of polygon's minimum rotated rectangle."""
    obb = ShapelyPolygon(polygon).minimum_rotated_rectangle
    corners = list(obb.exterior.coords)[:-1]
    if len(corners) < 4:
        return (1.0, 0.0)  # degenerate (near-zero-area) polygon -- any axis works
    edge_a = distance(corners[0], corners[1])
    edge_b = distance(corners[1], corners[2])
    p1, p2 = (corners[0], corners[1]) if edge_a >= edge_b else (corners[1], corners[2])
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length else (1.0, 0.0)


def _polygon_centroid(polygon: Polygon) -> Point:
    return (sum(p[0] for p in polygon) / len(polygon), sum(p[1] for p in polygon) / len(polygon))


def _split_polygon(polygon: Polygon, rng, gap: float) -> Tuple[Polygon, Polygon]:
    """Split `polygon` into two halves along a jittered axis (angle offset
    from the longer OBB axis, wider ratio range than a clean 50/50) --
    this plus the per-leaf finishing pass is what gives buildings local
    irregularity, distinct from the one coarse jaggify_polygon pass on
    the district boundary."""
    axis_dir = _longer_axis_direction(polygon)
    angle = math.atan2(axis_dir[1], axis_dir[0]) + rng.uniform(-0.35, 0.35)  # +/- ~20 degrees
    axis_dir = (math.cos(angle), math.sin(angle))
    split_dir = (-axis_dir[1], axis_dir[0])  # perpendicular to the jittered axis
    cx, cy = _polygon_centroid(polygon)

    span = max((distance(p, q) for p in polygon for q in polygon), default=0.0) + 1.0
    split_fraction = rng.uniform(0.3, 0.7)
    offset_along_axis = (split_fraction - 0.5) * span
    center = (cx + axis_dir[0] * offset_along_axis, cy + axis_dir[1] * offset_along_axis)

    line_start = (center[0] - split_dir[0] * span, center[1] - split_dir[1] * span)
    line_end = (center[0] + split_dir[0] * span, center[1] + split_dir[1] * span)

    half_gap = gap / 2.0
    offset_a = (axis_dir[0] * half_gap, axis_dir[1] * half_gap)
    offset_b = (-offset_a[0], -offset_a[1])

    side_a = clip_polygon_by_line(
        polygon,
        (line_start[0] + offset_b[0], line_start[1] + offset_b[1]),
        (line_end[0] + offset_b[0], line_end[1] + offset_b[1]),
    )
    side_b = clip_polygon_by_line(
        polygon,
        (line_end[0] + offset_a[0], line_end[1] + offset_a[1]),
        (line_start[0] + offset_a[0], line_start[1] + offset_a[1]),
    )
    return side_a, side_b


def subdivide_into_blocks(polygon_part: Polygon, zone_type: ZoneType, rng) -> List[Polygon]:
    """Recursively split `polygon_part` into blocks for `zone_type`. Each
    split leaves a real LOCAL_STREET_WIDTH gap between the two halves
    (via _split_polygon's offset cut) -- that gap is the street; no
    RoadNode/RoadEdge rows are produced for it."""
    return _subdivide(polygon_part, TARGET_BLOCK_AREA_BY_ZONE[zone_type], rng, depth=0)


def _subdivide(polygon_part: Polygon, target_area: float, rng, depth: int) -> List[Polygon]:
    if len(polygon_part) < 3 or polygon_area(polygon_part) <= target_area or depth >= MAX_SPLIT_DEPTH:
        return [polygon_part]

    side_a, side_b = _split_polygon(polygon_part, rng, LOCAL_STREET_WIDTH)
    if len(side_a) < 3 or len(side_b) < 3:
        return [polygon_part]

    return _subdivide(side_a, target_area, rng, depth + 1) + _subdivide(side_b, target_area, rng, depth + 1)


def _leaf_footprint(leaf: Polygon) -> Tuple[float, float, float, float, float]:
    """Center (x, y), width, height, and rotation of `leaf`'s minimum
    rotated rectangle -- same OBB approach _longer_axis_direction uses."""
    shapely_leaf = ShapelyPolygon(leaf)
    obb = shapely_leaf.minimum_rotated_rectangle
    corners = list(obb.exterior.coords)[:-1]
    if len(corners) < 4:
        cx, cy = _polygon_centroid(leaf)
        return (cx, cy, 1.0, 1.0, 0.0)
    edge_a = distance(corners[0], corners[1])
    edge_b = distance(corners[1], corners[2])
    width, height = (edge_a, edge_b) if edge_a >= edge_b else (edge_b, edge_a)
    p1, p2 = (corners[0], corners[1]) if edge_a >= edge_b else (corners[1], corners[2])
    rotation = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    # The OBB over-covers any non-rectangular leaf (triangles, trapezoids from
    # clipping), which shows up as overlapping footprints and buildings poking
    # outside their district. Shrink both sides so the reported footprint's area
    # matches the leaf's true area, never exceeding it.
    obb_area = obb.area
    leaf_area = shapely_leaf.area
    if obb_area > 0 and leaf_area < obb_area:
        scale = math.sqrt(leaf_area / obb_area)
        width *= scale
        height *= scale
    center = obb.centroid
    return (center.x, center.y, width, height, rotation)


def place_buildings_in_block(
    block_polygon: Polygon, district: District, rng,
    next_building_id: int, target_population: int, magic_prevalence: float,
    notable_building_counts: Optional[Dict[str, int]] = None,
    density_multiplier: float = 1.0,
    target_area: Optional[float] = None,
    hard_cap_area: Optional[float] = None,
    existing_shapes: Optional[List[ShapelyPolygon]] = None,
) -> List[Building]:
    if notable_building_counts is None:
        notable_building_counts = {}

    zone_type = district.zone_type
    if target_area is None:
        target_area = (
            (LOT_FRONTAGE_BY_ZONE[zone_type] / density_multiplier)
            * (LOT_DEPTH_BY_ZONE[zone_type] / density_multiplier)
        )
    if hard_cap_area is None:
        hard_cap_area = DEFAULT_HARD_CAP_AREA

    gap_range = RESIDENTIAL_SPLIT_GAP_RANGE if zone_type in RESIDENTIAL_ZONE_TYPES else (0.25, 0.6)
    raw_leaves = organic_subdivide(block_polygon, target_area, hard_cap_area, rng, gap_range=gap_range)
    leaves = finish_leaves(raw_leaves, rng, seed_shapes=existing_shapes)
    if existing_shapes is not None:
        existing_shapes.extend(ShapelyPolygon(leaf).buffer(0) for leaf in leaves)

    if zone_type in RESIDENTIAL_ZONE_TYPES:
        leaves = [leaf for leaf in leaves if rng.random() >= GARDEN_CULL_FRACTION]

    buildings: List[Building] = []
    building_id = next_building_id
    for leaf in leaves:
        if polygon_area(leaf) < 1.0:
            continue  # sliver left over from a degenerate cut, not worth a building

        cx, cy, width, height, rotation = _leaf_footprint(leaf)
        building_type = pick_building_type_with_cap(
            zone_type, target_population, magic_prevalence, rng, notable_building_counts,
        )
        capacity = BUILDING_HOME_CAPACITY.get(building_type, 0)
        vacancies = [
            JobVacancy(building_id=building_id, occupation=occupation)
            for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[building_type]
            for _ in range(count)
        ]
        name_pool = BUILDING_NAME_POOLS.get(building_type)
        name = rng.choice(name_pool) if name_pool else None

        buildings.append(Building(
            id=building_id,
            district_id=district.id,
            district_zone_type=zone_type,
            x=cx,
            y=cy,
            building_type=building_type,
            capacity=capacity,
            vacancies=vacancies,
            name=name,
            width=width,
            height=height,
            rotation=rotation,
            footprint=leaf,
        ))
        building_id += 1

    return buildings


def compute_district_blocks(district: District, town_seed, skip_block_subdivision: bool = False) -> List[Polygon]:
    """Inset each of the district's polygon parts, jaggify the inset
    boundary (fixes the straight Voronoi-cell-edge look), then subdivide
    into blocks. Split out from generate_blocks_and_buildings so the
    two-pass residential flow (town_shaper/generate.py) can compute every
    residential district's block geometry and total area before deriving
    a demand-driven leaf target area -- see the design spec's two-pass
    description.

    skip_block_subdivision=True skips the TARGET_BLOCK_AREA_BY_ZONE-driven
    subdivide_into_blocks step, returning one "block" per polygon part
    (just inset+jaggified) instead. Used for residential zones: their
    blocks are already smaller than the demand-driven leaf target_area,
    so subdividing into blocks here first leaves organic_subdivide nothing
    to do -- each block becomes exactly one leaf/building, and building
    count collapses to block count, disconnected from household demand.
    Skipping this step lets organic_subdivide (with the real target_area)
    be the only thing that subdivides residential zones."""
    # Distinct path segment from generate_blocks_and_buildings' own
    # rng_for(town_seed, "blocks", district.id) -- both used to share this
    # exact path, so calling them both replayed the identical sequence
    # instead of continuing one stream.
    rng = rng_for(town_seed, "blocks", district.id, "geometry")
    blocks: List[Polygon] = []
    for part in district.polygon_parts:
        inset_part = inset_polygon(part, DISTRICT_INSET_DISTANCE)
        if len(inset_part) < 3:
            continue
        # Absolute cap so the perturbation can never push a vertex back out
        # past most of its own inset margin into a neighbouring district.
        jagged = jaggify_polygon(inset_part, rng, max_absolute_offset=DISTRICT_INSET_DISTANCE * 0.8)
        if skip_block_subdivision:
            blocks.append(jagged)
        else:
            blocks.extend(subdivide_into_blocks(jagged, district.zone_type, rng))
    return blocks


def generate_blocks_and_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0, magic_prevalence: float = 0.0,
    notable_building_counts: Optional[Dict[str, int]] = None,
    blocks: Optional[List[Polygon]] = None,
    target_area: Optional[float] = None,
    hard_cap_area: Optional[float] = None,
) -> List[Building]:
    rng = rng_for(town_seed, "blocks", district.id)
    if notable_building_counts is None:
        notable_building_counts = {}
    if blocks is None:
        blocks = compute_district_blocks(district, town_seed)

    buildings: List[Building] = []
    building_id = next_building_id
    # Accumulated across every block of this district so finish_leaves'
    # appendage-overlap check sees siblings from earlier blocks/parts too,
    # not just the current block -- a district can have many blocks (see
    # compute_district_blocks' skip_block_subdivision path for residential
    # zones), and appendages must not bridge across them undetected.
    district_shapes: List[ShapelyPolygon] = []

    for block in blocks:
        block_buildings = place_buildings_in_block(
            block, district, rng, building_id, target_population, magic_prevalence,
            notable_building_counts=notable_building_counts, density_multiplier=density_multiplier,
            target_area=target_area, hard_cap_area=hard_cap_area,
            existing_shapes=district_shapes,
        )
        buildings.extend(block_buildings)
        building_id += len(block_buildings)

    return buildings


HARD_CAP_AREA_MULTIPLIER = 4.0
RESIDENTIAL_SLACK = 1.25
GARDEN_CULL_FRACTION = 0.12
RESIDENTIAL_ZONE_TYPES = (ZoneType.POOR_RESIDENTIAL, ZoneType.RICH_RESIDENTIAL)
RESIDENTIAL_SPLIT_GAP_RANGE = (LOCAL_STREET_WIDTH * 0.5, LOCAL_STREET_WIDTH)
DEFAULT_HARD_CAP_AREA = (
    HARD_CAP_AREA_MULTIPLIER
    * LOT_FRONTAGE_BY_ZONE[ZoneType.POOR_RESIDENTIAL]
    * LOT_DEPTH_BY_ZONE[ZoneType.POOR_RESIDENTIAL]
)


def organic_subdivide(
    polygon: Polygon, target_area: float, hard_cap_area: float, rng, depth: int = 0, max_depth: int = 9,
    gap_range: Tuple[float, float] = (0.25, 0.6),
) -> List[Polygon]:
    """Recursively split `polygon` into building-sized leaves. Soft stop at
    a randomized fraction of target_area (size variance between leaves);
    but always splits further if area exceeds hard_cap_area regardless of
    that soft sample, so no leaf can end up "much much much" bigger than
    the rest of a zone just because its containing block happened to be
    smaller than target_area to begin with (the degenerate case an
    earlier version of this algorithm hit: an undersized block became one
    giant, unfinished single "building").

    max_depth only caps recursion in the soft-stop case -- once must_split
    is true (area > hard_cap_area), splitting keeps going past max_depth,
    since the hard-cap guarantee is depth-independent. The only remaining
    way it can be violated is if the polygon genuinely can't be split
    further (_split_polygon degenerates to a <3-vertex side below), an
    inherent geometric limit rather than a depth-budget bug.

    gap_range controls the party-wall gap between adjacent leaves at every
    split. The default (0.25, 0.6) suits splitting an already-small block
    into individual lots. Residential zones pass a wider range (see
    RESIDENTIAL_SPLIT_GAP_RANGE) because, since Task 8, organic_subdivide
    runs directly on a whole district part for those zones (no separate
    block-level street grid) -- every split here is the only thing
    visually separating two buildings, so it needs to read as a real
    street, not a hairline crack."""
    area = polygon_area(polygon)
    stop_area = target_area * rng.uniform(0.55, 1.4)
    must_split = area > hard_cap_area
    if len(polygon) < 3 or (depth >= max_depth and not must_split) or (area <= stop_area and not must_split):
        return [polygon]

    result = _split_polygon(polygon, rng, gap=rng.uniform(*gap_range))
    side_a, side_b = result
    if len(side_a) < 3 or len(side_b) < 3:
        return [polygon]

    return (
        organic_subdivide(side_a, target_area, hard_cap_area, rng, depth + 1, max_depth, gap_range)
        + organic_subdivide(side_b, target_area, hard_cap_area, rng, depth + 1, max_depth, gap_range)
    )


def notch_corner(polygon: Polygon, rng) -> Polygon:
    """Shave a small triangular notch off one random corner, ~35% of the
    time -- a straight-wall L-shaped front. Can only shrink the polygon,
    never grow it, so it can never introduce a new overlap with a
    neighbour."""
    if len(polygon) < 4 or rng.random() > 0.35:
        return polygon
    idx = rng.randrange(len(polygon))
    v = polygon[idx]
    prev_v = polygon[idx - 1]
    next_v = polygon[(idx + 1) % len(polygon)]
    frac = rng.uniform(0.25, 0.45)
    p1 = (v[0] + (prev_v[0] - v[0]) * frac, v[1] + (prev_v[1] - v[1]) * frac)
    p2 = (v[0] + (next_v[0] - v[0]) * frac, v[1] + (next_v[1] - v[1]) * frac)
    return polygon[:idx] + [p1, p2] + polygon[idx + 1:]


def add_appendage(polygon: Polygon, rng) -> Polygon:
    """Attach a small straight-walled porch/annex to one edge, at a
    slightly different orientation than the main body -- or, ~30% of the
    time, a curved bay/turret bulge instead of a rectangular one. Real
    building-shaped irregularity (real walls, a real addition), never
    edge noise. ~40% chance of doing anything at all; the caller
    (finish_leaves) is responsible for rejecting the result if it would
    overlap a sibling leaf -- this function only ever grows the polygon
    outward, it has no notion of neighbours."""
    if len(polygon) < 4 or rng.random() > 0.4:
        return polygon
    idx = rng.randrange(len(polygon))
    p1, p2 = polygon[idx], polygon[(idx + 1) % len(polygon)]
    edge_len = math.dist(p1, p2)
    if edge_len < 3.0:
        return polygon

    ex, ey = (p2[0] - p1[0]) / edge_len, (p2[1] - p1[1]) / edge_len
    angle_dev = rng.uniform(-0.2, 0.2)
    cos_d, sin_d = math.cos(angle_dev), math.sin(angle_dev)
    ex2, ey2 = ex * cos_d - ey * sin_d, ex * sin_d + ey * cos_d
    perp = (-ey2, ex2)

    frac = rng.uniform(0.3, 0.55)
    start_t = rng.uniform(0.0, 1.0 - frac)
    base1 = (p1[0] + ex * edge_len * start_t, p1[1] + ey * edge_len * start_t)
    base2 = (p1[0] + ex * edge_len * (start_t + frac), p1[1] + ey * edge_len * (start_t + frac))
    seg_len = edge_len * frac
    depth = max(0.8, rng.uniform(0.25, 0.6) * seg_len)
    out1 = (base1[0] + perp[0] * depth, base1[1] + perp[1] * depth)
    out2 = (base2[0] + perp[0] * depth, base2[1] + perp[1] * depth)

    if rng.random() < 0.3:
        mid = ((out1[0] + out2[0]) / 2.0, (out1[1] + out2[1]) / 2.0)
        bulge = depth * rng.uniform(0.3, 0.6)
        arc_peak = (mid[0] + perp[0] * bulge, mid[1] + perp[1] * bulge)
        appendage_pts = [base1, out1]
        for t in (0.25, 0.5, 0.75):
            appendage_pts.append((
                (1 - t) ** 2 * out1[0] + 2 * (1 - t) * t * arc_peak[0] + t ** 2 * out2[0],
                (1 - t) ** 2 * out1[1] + 2 * (1 - t) * t * arc_peak[1] + t ** 2 * out2[1],
            ))
        appendage_pts += [out2, base2]
    else:
        appendage_pts = [base1, out1, out2, base2]

    try:
        merged = ShapelyPolygon(polygon).buffer(0).union(ShapelyPolygon(appendage_pts).buffer(0))
        if merged.geom_type == "Polygon":
            return list(merged.exterior.coords)[:-1]
    except Exception:
        pass
    return polygon


def finish_leaves(leaves: List[Polygon], rng, seed_shapes: Optional[List[ShapelyPolygon]] = None) -> List[Polygon]:
    """Per-block finishing pass: notch (always safe -- never grows a
    leaf) then a candidate appendage per leaf, checked against every
    OTHER leaf already finished in this same block (and, via seed_shapes,
    every leaf already finished earlier in the same district -- so
    appendages can't bridge across block/part boundaries within a
    district); a candidate that would overlap a sibling is rejected
    outright (never shrunk -- the appendage is probabilistic in the first
    place, occasionally skipping one for lack of room is an acceptable,
    minor loss).

    Also checked against every sibling's RAW (pre-notch, pre-appendage)
    shape, not just ones already finished -- otherwise a leaf processed
    early could grow an appendage into a later sibling's own body before
    that sibling has been decided, since the "already finished" list is
    still empty for it at that point. The raw shape is a safe superset for
    this (notching only shrinks, so "doesn't overlap the raw leaf" implies
    "doesn't overlap its notched form either", and needs no extra rng draw
    to compute, so this doesn't change rng consumption order/count.

    seed_shapes is copied, never mutated -- the caller's list is unaffected."""
    finished: List[Polygon] = []
    shapes: List[ShapelyPolygon] = list(seed_shapes) if seed_shapes else []
    raw_shapes: List[ShapelyPolygon] = [ShapelyPolygon(leaf).buffer(0) for leaf in leaves]
    for idx, leaf in enumerate(leaves):
        notched = notch_corner(leaf, rng)
        candidate = add_appendage(notched, rng)
        candidate_shape = ShapelyPolygon(candidate).buffer(0)
        others = shapes + raw_shapes[:idx] + raw_shapes[idx + 1:]
        overlaps = any(candidate_shape.intersection(other).area > 1e-6 for other in others)
        final = notched if overlaps else candidate
        finished.append(final)
        shapes.append(ShapelyPolygon(final).buffer(0))
    return finished
