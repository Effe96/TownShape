import math
from typing import Dict, List, Optional, Tuple

from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.buildings import (
    BUILDING_HOME_CAPACITY, BUILDING_NAME_POOLS, JOB_VACANCIES_BY_BUILDING_TYPE, pick_building_type_with_cap,
)
from town_shaper.geometry import clip_polygon_by_line, distance, inset_polygon, polygon_area
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
FOOTPRINT_FILL_FRACTION = 0.8
LOCAL_STREET_WIDTH = 4.0
DISTRICT_INSET_DISTANCE = 2.0
BUILDING_GAP = 0.4
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
    """Split `polygon` into two halves along its longer OBB axis, offset by `gap`."""
    axis_dir = _longer_axis_direction(polygon)
    split_dir = (-axis_dir[1], axis_dir[0])  # perpendicular to the longer axis
    cx, cy = _polygon_centroid(polygon)

    span = max((distance(p, q) for p in polygon for q in polygon), default=0.0) + 1.0
    split_fraction = rng.uniform(0.4, 0.6)
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


def _subdivide_into_buildings(block_polygon: Polygon, target_area: float, rng, depth: int = 0) -> List[Polygon]:
    if len(block_polygon) < 3 or depth >= MAX_SPLIT_DEPTH or polygon_area(block_polygon) <= target_area:
        return [block_polygon]

    side_a, side_b = _split_polygon(block_polygon, rng, BUILDING_GAP)
    if len(side_a) < 3 or len(side_b) < 3:
        return [block_polygon]

    return (
        _subdivide_into_buildings(side_a, target_area, rng, depth + 1)
        + _subdivide_into_buildings(side_b, target_area, rng, depth + 1)
    )


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
    center = obb.centroid
    return (center.x, center.y, width, height, rotation)


def place_buildings_in_block(
    block_polygon: Polygon, district: District, rng,
    next_building_id: int, target_population: int, magic_prevalence: float,
    notable_building_counts: Optional[Dict[str, int]] = None,
    density_multiplier: float = 1.0,
) -> List[Building]:
    if notable_building_counts is None:
        notable_building_counts = {}

    zone_type = district.zone_type
    target_area = (
        (LOT_FRONTAGE_BY_ZONE[zone_type] / density_multiplier)
        * (LOT_DEPTH_BY_ZONE[zone_type] / density_multiplier)
    )

    leaves = _subdivide_into_buildings(block_polygon, target_area, rng)

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
        ))
        building_id += 1

    return buildings


def generate_blocks_and_buildings(
    district: District, town_seed, next_building_id: int,
    target_population: int = 0, density_multiplier: float = 1.0, magic_prevalence: float = 0.0,
    notable_building_counts: Optional[Dict[str, int]] = None,
) -> List[Building]:
    rng = rng_for(town_seed, "blocks", district.id)
    if notable_building_counts is None:
        notable_building_counts = {}

    buildings: List[Building] = []
    building_id = next_building_id

    for part in district.polygon_parts:
        inset_part = inset_polygon(part, DISTRICT_INSET_DISTANCE)
        if len(inset_part) < 3:
            continue
        blocks = subdivide_into_blocks(inset_part, district.zone_type, rng)
        for block in blocks:
            block_buildings = place_buildings_in_block(
                block, district, rng, building_id, target_population, magic_prevalence,
                notable_building_counts, density_multiplier,
            )
            buildings.extend(block_buildings)
            building_id += len(block_buildings)

    return buildings
