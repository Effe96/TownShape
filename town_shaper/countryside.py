import math
from typing import List, Tuple

from shapely.geometry import Point, Polygon as ShapelyPolygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from town_shaper.blocks import notch_corner
from town_shaper.buildings import BUILDING_HOME_CAPACITY, BUILDING_NAME_POOLS, JOB_VACANCIES_BY_BUILDING_TYPE
from town_shaper.geometry import polygon_area, rotated_rect_corners
from town_shaper.models import Building, District, JobVacancy, WaterFeature, ZoneType
from town_shaper.seeding import rng_for

# Farmland is no longer a zone filled at a uniform density -- see the
# module docstring below. A building out here needs FARM_CLEARANCE (or
# less, tapering in near town) of open space in every direction, nothing
# else decides where one can go. That alone excludes the entire dense
# town (there's always a nearer building than that everywhere inside it)
# without any zone-boundary check, so density fades to zero exactly where
# existing buildings thin out on their own -- no seam, because there is
# no boundary to seam along.
#
# Attempts scale with map AREA, not a flat count -- a flat count
# calibrated against one town's map size undersamples a bigger one,
# which produced patchy random gaps (not enough attempts landed in some
# bands for the gradient to fill in reliably) on a second, larger town
# during validation.
COUNTRYSIDE_ATTEMPT_DENSITY = 9000 / 600_000  # calibrated against a 4000-population town
COUNTRYSIDE_MIN_CLEARANCE = 2.0    # right at the settled edge -- dense infill is fine here
COUNTRYSIDE_MAX_CLEARANCE = 16.0   # true countryside spacing
COUNTRYSIDE_GRADIENT_START_DIST = 5.0   # map units from the nearest real building -- gradient begins here
COUNTRYSIDE_GRADIENT_END_DIST = 80.0    # map units from the nearest real building -- full countryside spacing by here
COUNTRYSIDE_NOTCH_PROBABILITY = 0.4  # extra shape variety -- an isolated building needn't be a plain rectangle
COUNTRYSIDE_HOUSE_WIDTH = (3.0, 6.0)
COUNTRYSIDE_HOUSE_HEIGHT = (3.5, 7.0)

# A farm isn't one big rectangle -- it's a small compound: a main house
# plus a few outbuildings (barn, shed) clustered close together, each its
# own small rectangle at its own size/rotation. Reads as an actual
# farmstead from above; a single scaled-up rectangle never did, no matter
# how much it got notched. Building count and sizes are independent of
# distance from town -- only how far apart CLUSTERS have to be (the
# clearance gradient below) changes with distance, not what any
# individual cluster looks like -- making size grow with distance was a
# deliberate earlier attempt that read as an obviously algorithmic tell,
# not an organic one.
FARM_CLUSTER_BUILDING_COUNT = (2, 4)
FARM_MAIN_WIDTH, FARM_MAIN_HEIGHT = (2.5, 4.5), (3.0, 5.5)
FARM_OUTBUILDING_WIDTH, FARM_OUTBUILDING_HEIGHT = (1.5, 3.0), (1.8, 3.5)
# Must clear the two buildings' combined half-diagonals (main ~3.55,
# outbuilding ~2.3) or the retry loop below rejects almost every
# placement and silently falls back to a lone main house -- exactly what
# happened during validation at a smaller offset against bigger sizes.
FARM_OUTBUILDING_OFFSET = (6.5, 9.5)
FARM_OUTBUILDING_ATTEMPTS = 10


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _generate_farm_cluster(cx: float, cy: float, rng) -> List[List[Tuple[float, float]]]:
    """A small compound of 2-4 buildings (main house + outbuildings),
    close together, each its own small rectangle -- reads as an actual
    farmstead from above. Returns a list of rings (one footprint per
    building in the compound); the caller persists the whole thing as
    ONE Building with a multi-ring footprint (see
    town_shaper.blocks.ring_peel for the same one-building convention)."""
    rings: List[List[Tuple[float, float]]] = []
    shapes = []
    building_count = rng.randint(*FARM_CLUSTER_BUILDING_COUNT)
    for i in range(building_count):
        is_main = i == 0
        width = rng.uniform(*FARM_MAIN_WIDTH) if is_main else rng.uniform(*FARM_OUTBUILDING_WIDTH)
        height = rng.uniform(*FARM_MAIN_HEIGHT) if is_main else rng.uniform(*FARM_OUTBUILDING_HEIGHT)
        for _attempt in range(FARM_OUTBUILDING_ATTEMPTS):
            if is_main:
                bx, by = cx, cy
            else:
                offset = rng.uniform(*FARM_OUTBUILDING_OFFSET)
                angle = rng.uniform(0, 2 * math.pi)
                bx, by = cx + math.cos(angle) * offset, cy + math.sin(angle) * offset
            rotation = rng.uniform(0, 2 * math.pi)
            ring = rotated_rect_corners(bx, by, width, height, rotation)
            shape = ShapelyPolygon(ring).buffer(0.5)  # a little breathing room, not wall-to-wall
            if not any(shape.intersects(s) for s in shapes):
                rings.append(ring)
                shapes.append(shape)
                break
    return rings


def _building_shapes(building: Building) -> List[ShapelyPolygon]:
    """Every actual footprint ring for `building` as shapely polygons --
    a flat ring or a list of rings (a courtyard building's several wall
    pieces) if it has a real footprint, else a rectangle reconstructed
    from width/height/rotation."""
    if building.footprint is not None:
        rings = building.footprint if isinstance(building.footprint[0][0], (list, tuple)) else [building.footprint]
        return [ShapelyPolygon(r).buffer(0) for r in rings]
    return [ShapelyPolygon(rotated_rect_corners(building.x, building.y, building.width, building.height, building.rotation)).buffer(0)]


def _water_union(water_features: List[WaterFeature]):
    if not water_features:
        return None
    return unary_union([f.polygon for f in water_features])


def remove_buildings_in_water(districts: List[District], water_features: List[WaterFeature]) -> None:
    """Defensive invariant, enforced once after all generation: no building
    anywhere may intersect water. Each generation path (residential's v4
    cutting, merchant/civic blocks, countryside) has its own water check,
    but coastal edge cases still slipped through each of them independently
    -- patching every path individually is a rabbit hole; one shared filter
    at the end catches all of them regardless of source. Mutates each
    district's `buildings` list in place."""
    water = _water_union(water_features)
    if water is None:
        return
    for district in districts:
        district.buildings = [
            b for b in district.buildings
            if not any(shape.intersects(water) for shape in _building_shapes(b))
        ]


def generate_countryside_buildings(
    districts: List[District], water_features: List[WaterFeature],
    bounds: Tuple[float, float, float, float], seed, next_building_id: int, owning_district_id: int,
) -> List[Building]:
    """Replaces the old uniform-density farmland-zone fill entirely: no
    zone/anchor decides where a countryside building can go, only local
    clearance from every other building already placed anywhere in town
    (`districts`) does. Must run AFTER every other district's buildings
    already exist, since it needs to know where they all are.

    The required clearance itself grows smoothly with distance to the
    nearest existing building -- small (dense infill) right at the
    settled edge, full farm spacing once well clear of it. One continuous
    function, so there's no handoff point for a seam to form at, and no
    reliance on the town's (usually very irregular) overall shape either:
    an earlier version drove this off distance from the map's geometric
    CENTER instead, which silently assumed a roughly circular town --
    fine on the side where a district happened to end close to center,
    a visible dead gap on the side where it extended further out first."""
    min_x, min_y, max_x, max_y = bounds
    attempts = int((max_x - min_x) * (max_y - min_y) * COUNTRYSIDE_ATTEMPT_DENSITY)
    rng = rng_for(seed, "countryside")
    water = _water_union(water_features)

    static_shapes = [shape for d in districts for b in d.buildings for shape in _building_shapes(b)]
    static_tree = STRtree(static_shapes) if static_shapes else None
    dynamic_shapes: List[ShapelyPolygon] = []

    placed: List[Building] = []
    building_id = next_building_id
    for _ in range(attempts):
        x, y = rng.uniform(min_x, max_x), rng.uniform(min_y, max_y)
        point = Point(x, y)
        if water is not None and water.contains(point):
            continue

        if static_tree is not None:
            dist_to_settled = point.distance(static_shapes[static_tree.nearest(point)])
        else:
            dist_to_settled = COUNTRYSIDE_GRADIENT_END_DIST
        t = _smoothstep((dist_to_settled - COUNTRYSIDE_GRADIENT_START_DIST) / (COUNTRYSIDE_GRADIENT_END_DIST - COUNTRYSIDE_GRADIENT_START_DIST))
        clearance = COUNTRYSIDE_MIN_CLEARANCE + t * (COUNTRYSIDE_MAX_CLEARANCE - COUNTRYSIDE_MIN_CLEARANCE)

        is_farm = t > 0.5
        if is_farm:
            rings = _generate_farm_cluster(x, y, rng)
            if not rings:
                continue
        else:
            width, height = rng.uniform(*COUNTRYSIDE_HOUSE_WIDTH), rng.uniform(*COUNTRYSIDE_HOUSE_HEIGHT)
            rotation = rng.uniform(0, 2 * math.pi)
            ring = rotated_rect_corners(x, y, width, height, rotation)
            if rng.random() < COUNTRYSIDE_NOTCH_PROBABILITY:
                ring = notch_corner(ring, rng)
            rings = [ring]

        footprint_union = unary_union([ShapelyPolygon(r).buffer(0) for r in rings])
        # The initial water check above only tested the ONE sample point --
        # a farm cluster's outbuildings are offset from it by several
        # units, and a main house right at the coast can still have an
        # outbuilding land in the water even though its own center point
        # didn't. Confirmed on a real generated coastline: a handful of
        # buildings sitting visibly in open water.
        if water is not None and footprint_union.intersects(water):
            continue
        candidate_shape = footprint_union.buffer(clearance)

        if static_tree is not None:
            nearby_idx = static_tree.query(candidate_shape)
            if any(candidate_shape.intersects(static_shapes[i]) for i in nearby_idx):
                continue
        if any(candidate_shape.intersects(o) for o in dynamic_shapes):
            continue
        dynamic_shapes.append(candidate_shape)

        building_type = "farmstead" if is_farm else "residence"
        vacancies = [
            JobVacancy(building_id=building_id, occupation=occupation)
            for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[building_type]
            for _ in range(count)
        ]
        name_pool = BUILDING_NAME_POOLS.get(building_type)
        footprint = rings if len(rings) > 1 else rings[0]
        placed.append(Building(
            id=building_id,
            district_id=owning_district_id,
            district_zone_type=ZoneType.FARMLAND_EDGE,
            x=x, y=y,
            building_type=building_type,
            capacity=BUILDING_HOME_CAPACITY.get(building_type, 0),
            vacancies=vacancies,
            name=rng.choice(name_pool) if name_pool else None,
            footprint=footprint,
        ))
        building_id += 1

    return placed
