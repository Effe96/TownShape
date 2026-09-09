import math
from typing import List, Tuple

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


def chaikin_smooth(points: List[Point], iterations: int = 2) -> List[Point]:
    """Corner-cutting smoothing that keeps the first and last point fixed
    (an endpoint anchor shouldn't move) -- turns a jagged polyline through
    a handful of waypoints into a smooth curve. Used for both artery-road
    smoothing and river-path smoothing."""
    for _ in range(iterations):
        if len(points) < 3:
            return points
        smoothed = [points[0]]
        for i in range(len(points) - 1):
            p0, p1 = points[i], points[i + 1]
            smoothed.append((0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]))
            smoothed.append((0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]))
        smoothed.append(points[-1])
        points = smoothed
    return points
