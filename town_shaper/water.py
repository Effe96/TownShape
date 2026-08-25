# town_shaper/water.py
import math
from typing import List, Tuple

from shapely.geometry import LineString, Polygon

from town_shaper.models import WaterFeature
from town_shaper.seeding import rng_for

RIVER_WIDTH = 8.0
RIVER_WAYPOINT_JITTER = 0.15  # fraction of straight-line edge-to-edge distance
COASTLINE_DEPTH_FRACTION = 0.12  # fraction of the shorter bounds dimension
COASTLINE_JITTER = 0.08  # fraction of the shorter bounds dimension

_EDGES = ["north", "south", "east", "west"]


def _point_on_edge(edge: str, bounds: Tuple[float, float, float, float], rng) -> Tuple[float, float]:
    min_x, min_y, max_x, max_y = bounds
    if edge == "north":
        return (rng.uniform(min_x, max_x), max_y)
    if edge == "south":
        return (rng.uniform(min_x, max_x), min_y)
    if edge == "east":
        return (max_x, rng.uniform(min_y, max_y))
    return (min_x, rng.uniform(min_y, max_y))  # "west"


def _curved_strip(start: Tuple[float, float], end: Tuple[float, float], rng, width: float, bounds: Tuple[float, float, float, float]) -> Polygon:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return LineString([start, end]).buffer(width / 2.0)

    perp = (-dy / length, dx / length)  # unit vector perpendicular to start->end
    waypoint_count = rng.randint(2, 3)
    min_x, min_y, max_x, max_y = bounds

    points = [start]
    for i in range(1, waypoint_count + 1):
        t = i / (waypoint_count + 1)
        base_x = start[0] + dx * t
        base_y = start[1] + dy * t
        jitter = rng.uniform(-RIVER_WAYPOINT_JITTER, RIVER_WAYPOINT_JITTER) * length
        x = min(max(base_x + perp[0] * jitter, min_x), max_x)
        y = min(max(base_y + perp[1] * jitter, min_y), max_y)
        points.append((x, y))
    points.append(end)

    return LineString(points).buffer(width / 2.0)


def _generate_coastline(seed, bounds: Tuple[float, float, float, float]) -> Polygon:
    rng = rng_for(seed, "water", "coastline")
    min_x, min_y, max_x, max_y = bounds
    edge = rng.choice(_EDGES)
    short_dimension = min(max_x - min_x, max_y - min_y)
    depth = short_dimension * COASTLINE_DEPTH_FRACTION
    jitter = short_dimension * COASTLINE_JITTER

    if edge in ("north", "south"):
        base_y = max_y - depth if edge == "north" else min_y + depth
        start = (min_x, base_y + rng.uniform(-jitter, jitter))
        end = (max_x, base_y + rng.uniform(-jitter, jitter))
    else:
        base_x = max_x - depth if edge == "east" else min_x + depth
        start = (base_x + rng.uniform(-jitter, jitter), min_y)
        end = (base_x + rng.uniform(-jitter, jitter), max_y)

    strip = _curved_strip(start, end, rng, depth * 2.0, bounds)

    # Extend the strip past the chosen edge so the full area between the
    # strip and the map boundary is water, not just a buffered line near it.
    sea_box_bounds = {
        "north": (min_x - depth, max_y - depth, max_x + depth, max_y + depth * 4),
        "south": (min_x - depth, min_y - depth * 4, max_x + depth, min_y + depth),
        "east": (max_x - depth, min_y - depth, max_x + depth * 4, max_y + depth),
        "west": (min_x - depth * 4, min_y - depth, min_x + depth, max_y + depth),
    }[edge]
    sea_box = Polygon.from_bounds(*sea_box_bounds)
    return strip.union(sea_box)


def generate_water_features(
    seed, bounds: Tuple[float, float, float, float],
    num_rivers: int = 0, has_coastline: bool = False,
) -> List[WaterFeature]:
    features: List[WaterFeature] = []
    feature_id = 0

    for i in range(num_rivers):
        rng = rng_for(seed, "water", "river", i)
        start_edge, end_edge = rng.sample(_EDGES, 2)
        start = _point_on_edge(start_edge, bounds, rng)
        end = _point_on_edge(end_edge, bounds, rng)
        polygon = _curved_strip(start, end, rng, RIVER_WIDTH, bounds)
        features.append(WaterFeature(id=feature_id, kind="river", polygon=polygon))
        feature_id += 1

    if has_coastline:
        polygon = _generate_coastline(seed, bounds)
        features.append(WaterFeature(id=feature_id, kind="coastline", polygon=polygon))
        feature_id += 1

    return features
