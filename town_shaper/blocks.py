import math
from typing import Dict, List, Tuple

from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.geometry import clip_polygon_by_line, distance, polygon_area
from town_shaper.models import RoadEdge, RoadNode, ZoneType

TARGET_BLOCK_AREA_BY_ZONE: Dict[ZoneType, float] = {
    ZoneType.CIVIC: 2000.0,
    ZoneType.MERCHANT: 600.0,
    ZoneType.RICH_RESIDENTIAL: 1500.0,
    ZoneType.POOR_RESIDENTIAL: 250.0,
    ZoneType.PORT: 600.0,
}
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
        (line_start[0] + offset_a[0], line_start[1] + offset_a[1]),
        (line_end[0] + offset_a[0], line_end[1] + offset_a[1]),
    )
    side_b = clip_polygon_by_line(
        polygon,
        (line_end[0] + offset_b[0], line_end[1] + offset_b[1]),
        (line_start[0] + offset_b[0], line_start[1] + offset_b[1]),
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
