import math
from typing import Dict, List, Tuple

from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.buildings import (
    BUILDING_HOME_CAPACITY, BUILDING_NAME_POOLS, JOB_VACANCIES_BY_BUILDING_TYPE,
    resolve_building_type_weights,
)
from town_shaper.geometry import clip_polygon_by_line, distance, point_in_polygon, polygon_area
from town_shaper.models import Building, District, JobVacancy, RoadEdge, RoadNode, ZoneType

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


def _split_polygon(polygon: Polygon, rng) -> Tuple[Polygon, Polygon, Tuple[Point, Point]]:
    """Split `polygon` into two halves along its longer OBB axis, offset by
    LOCAL_STREET_WIDTH, plus the unoffset cut line's two endpoints."""
    axis_dir = _longer_axis_direction(polygon)
    split_dir = (-axis_dir[1], axis_dir[0])  # perpendicular to the longer axis
    cx, cy = _polygon_centroid(polygon)

    span = max((distance(p, q) for p in polygon for q in polygon), default=0.0) + 1.0
    split_fraction = rng.uniform(0.4, 0.6)
    offset_along_axis = (split_fraction - 0.5) * span
    center = (cx + axis_dir[0] * offset_along_axis, cy + axis_dir[1] * offset_along_axis)

    line_start = (center[0] - split_dir[0] * span, center[1] - split_dir[1] * span)
    line_end = (center[0] + split_dir[0] * span, center[1] + split_dir[1] * span)

    half_width = LOCAL_STREET_WIDTH / 2.0
    offset_a = (axis_dir[0] * half_width, axis_dir[1] * half_width)
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
    return side_a, side_b, (line_start, line_end)


def subdivide_into_blocks(
    polygon_part: Polygon, zone_type: ZoneType, rng, next_node_id: int, next_edge_id: int,
) -> Tuple[List[Polygon], List[RoadNode], List[RoadEdge], int, int]:
    """Recursively split `polygon_part` into blocks for `zone_type`.

    Returns (blocks, local_road_nodes, local_road_edges, next_node_id,
    next_edge_id) -- the last two are the counters incremented past whatever
    this call consumed, threaded the same way generate.py already threads
    next_building_id across districts.
    """
    return _subdivide(
        polygon_part, TARGET_BLOCK_AREA_BY_ZONE[zone_type], rng, next_node_id, next_edge_id, depth=0,
    )


def _subdivide(
    polygon_part: Polygon, target_area: float, rng, next_node_id: int, next_edge_id: int, depth: int,
) -> Tuple[List[Polygon], List[RoadNode], List[RoadEdge], int, int]:
    if len(polygon_part) < 3 or polygon_area(polygon_part) <= target_area or depth >= MAX_SPLIT_DEPTH:
        return [polygon_part], [], [], next_node_id, next_edge_id

    side_a, side_b, (line_start, line_end) = _split_polygon(polygon_part, rng)
    if len(side_a) < 3 or len(side_b) < 3:
        # Degenerate split (e.g. a sliver too thin for the street gap) -- stop here.
        return [polygon_part], [], [], next_node_id, next_edge_id

    node_a = RoadNode(id=next_node_id, kind="junction", x=line_start[0], y=line_start[1])
    node_b = RoadNode(id=next_node_id + 1, kind="junction", x=line_end[0], y=line_end[1])
    edge = RoadEdge(id=next_edge_id, from_node_id=node_a.id, to_node_id=node_b.id, road_type="local")
    next_node_id += 2
    next_edge_id += 1

    blocks_a, nodes_a, edges_a, next_node_id, next_edge_id = _subdivide(
        side_a, target_area, rng, next_node_id, next_edge_id, depth + 1,
    )
    blocks_b, nodes_b, edges_b, next_node_id, next_edge_id = _subdivide(
        side_b, target_area, rng, next_node_id, next_edge_id, depth + 1,
    )
    return (
        blocks_a + blocks_b,
        [node_a, node_b] + nodes_a + nodes_b,
        [edge] + edges_a + edges_b,
        next_node_id, next_edge_id,
    )


def _perpendicular_into_polygon(edge_start: Point, edge_end: Point, polygon: Polygon) -> Point:
    dx, dy = edge_end[0] - edge_start[0], edge_end[1] - edge_start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 0.0)
    direction = (dx / length, dy / length)
    candidate_a = (-direction[1], direction[0])
    midpoint = ((edge_start[0] + edge_end[0]) / 2.0, (edge_start[1] + edge_end[1]) / 2.0)
    probe = (midpoint[0] + candidate_a[0] * 0.1, midpoint[1] + candidate_a[1] * 0.1)
    return candidate_a if point_in_polygon(probe, polygon) else (-candidate_a[0], -candidate_a[1])


def _building_footprint_polygon(building: Building) -> ShapelyPolygon:
    """Compute the rotated footprint polygon of a building."""
    hw, hh = building.width / 2.0, building.height / 2.0
    cos_r, sin_r = math.cos(building.rotation), math.sin(building.rotation)
    corners = [
        (building.x + lx * cos_r - ly * sin_r, building.y + lx * sin_r + ly * cos_r)
        for lx, ly in [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    ]
    return ShapelyPolygon(corners)


def place_buildings_in_block(
    block_polygon: Polygon, district: District, rng,
    next_building_id: int, target_population: int, magic_prevalence: float,
    density_multiplier: float = 1.0,
) -> List[Building]:
    zone_type = district.zone_type
    frontage = LOT_FRONTAGE_BY_ZONE[zone_type] / density_multiplier
    depth = LOT_DEPTH_BY_ZONE[zone_type] / density_multiplier
    skip_distance = depth * FOOTPRINT_FILL_FRACTION / 2.0 + 1.0

    buildings: List[Building] = []
    building_id = next_building_id
    n = len(block_polygon)
    for i in range(n):
        edge_start = block_polygon[i]
        edge_end = block_polygon[(i + 1) % n]
        edge_length = distance(edge_start, edge_end)
        available_length = edge_length - 2.0 * skip_distance
        if available_length <= 0:
            continue
        num_lots = int(available_length // frontage)
        if num_lots == 0:
            continue
        dx = (edge_end[0] - edge_start[0]) / edge_length
        dy = (edge_end[1] - edge_start[1]) / edge_length
        inward = _perpendicular_into_polygon(edge_start, edge_end, block_polygon)
        rotation = math.atan2(dy, dx)

        for lot_index in range(num_lots):
            along = skip_distance + frontage * (lot_index + 0.5)
            lot_center_x = edge_start[0] + dx * along + inward[0] * (depth / 2.0)
            lot_center_y = edge_start[1] + dy * along + inward[1] * (depth / 2.0)

            type_weights = resolve_building_type_weights(zone_type, target_population, magic_prevalence, rng)
            subtypes = list(type_weights.keys())
            weights = list(type_weights.values())
            building_type = rng.choices(subtypes, weights=weights, k=1)[0]
            capacity = BUILDING_HOME_CAPACITY.get(building_type, 0)
            vacancies = [
                JobVacancy(building_id=building_id, occupation=occupation)
                for occupation, count in JOB_VACANCIES_BY_BUILDING_TYPE[building_type]
                for _ in range(count)
            ]
            name_pool = BUILDING_NAME_POOLS.get(building_type)
            name = rng.choice(name_pool) if name_pool else None

            building = Building(
                id=building_id,
                district_id=district.id,
                district_zone_type=zone_type,
                x=lot_center_x,
                y=lot_center_y,
                building_type=building_type,
                capacity=capacity,
                vacancies=vacancies,
                name=name,
                width=frontage * FOOTPRINT_FILL_FRACTION,
                height=depth * FOOTPRINT_FILL_FRACTION,
                rotation=rotation,
            )

            # Check for overlap with existing buildings
            new_footprint = _building_footprint_polygon(building)
            overlaps = False
            for existing in buildings:
                existing_footprint = _building_footprint_polygon(existing)
                if new_footprint.intersection(existing_footprint).area > 1e-6:
                    overlaps = True
                    break

            if not overlaps:
                buildings.append(building)
                building_id += 1

    return buildings
