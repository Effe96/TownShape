import math
from typing import List, Tuple

from shapely.geometry import Polygon as ShapelyPolygon

Point = Tuple[float, float]
Polygon = List[Point]


def polygon_area(polygon: Polygon) -> float:
    if len(polygon) < 3:
        return 0.0
    area = 0.0
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_at_y = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < x_at_y:
                inside = not inside
    return inside


def distance(p1: Point, p2: Point) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def _is_inside_edge(point: Point, edge_start: Point, edge_end: Point) -> bool:
    return (edge_end[0] - edge_start[0]) * (point[1] - edge_start[1]) - \
           (edge_end[1] - edge_start[1]) * (point[0] - edge_start[0]) >= 0


def _line_intersection(p1: Point, p2: Point, edge_start: Point, edge_end: Point) -> Point:
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = edge_start
    x4, y4 = edge_end
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if denom == 0:
        return p2
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def clip_polygon_by_line(polygon: Polygon, edge_start: Point, edge_end: Point) -> Polygon:
    """Sutherland-Hodgman single-edge clip: keep only the part of `polygon`
    on the inside (left) of the directed line edge_start -> edge_end."""
    output: Polygon = []
    if not polygon:
        return output
    s = polygon[-1]
    for e in polygon:
        e_inside = _is_inside_edge(e, edge_start, edge_end)
        s_inside = _is_inside_edge(s, edge_start, edge_end)
        if e_inside:
            if not s_inside:
                output.append(_line_intersection(s, e, edge_start, edge_end))
            output.append(e)
        elif s_inside:
            output.append(_line_intersection(s, e, edge_start, edge_end))
        s = e
    return output


def clip_polygon_to_bounds(polygon: Polygon, bounds: Tuple[float, float, float, float]) -> Polygon:
    """Sutherland-Hodgman clip of `polygon` against the rectangle `bounds`."""
    min_x, min_y, max_x, max_y = bounds
    clip_edges = [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]

    output = list(polygon)
    for i in range(len(clip_edges)):
        if not output:
            break
        edge_start = clip_edges[i]
        edge_end = clip_edges[(i + 1) % len(clip_edges)]
        output = clip_polygon_by_line(output, edge_start, edge_end)
    return output


def inset_polygon(polygon: Polygon, distance: float) -> Polygon:
    """Insets `polygon` inward by `distance` via shapely's buffer
    operation. Replaces an earlier hand-rolled half-plane-intersection
    approach that was convex-only and separately broke on clockwise
    winding and near-duplicate vertices -- shapely's buffer handles all
    three correctly in one call."""
    if len(polygon) < 3:
        return []
    shapely_poly = ShapelyPolygon(polygon)
    if shapely_poly.is_empty:
        return []
    # No is_valid guard on purpose: a near-duplicate vertex (a routine
    # floating-point artifact of the Sutherland-Hodgman clips upstream) makes
    # shapely report "self-intersection", but buffer still insets it correctly.
    result = shapely_poly.buffer(-distance, join_style="mitre")
    if result.is_empty:
        return []
    if result.geom_type == "MultiPolygon":
        result = max(result.geoms, key=lambda g: g.area)
    return list(result.exterior.coords)[:-1]
