# town_shaper/water.py
import math
from typing import List, Sequence, Tuple

from shapely.geometry import LineString, Polygon

from town_shaper.geometry import chaikin_smooth
from town_shaper.models import WaterFeature
from town_shaper.seeding import rng_for

RIVER_WIDTH = 8.0
RIVER_WAYPOINT_JITTER_MIN = 0.12  # fraction of straight-line edge-to-edge distance
RIVER_WAYPOINT_JITTER_MAX = 0.20  # fraction of straight-line edge-to-edge distance
RIVER_WAYPOINT_JITTER_ABS_MIN = 2.0  # absolute floor on offset magnitude, in map units
ROOM_SAFETY_FACTOR = 0.9  # stay strictly inside available room to a bound, never touch it
COASTLINE_DEPTH_FRACTION = 0.12  # fraction of the shorter bounds dimension
COASTLINE_JITTER = 0.08  # fraction of the shorter bounds dimension
# A bearing-directed river crosses the town near (not exactly through) its
# centre: its course shifts sideways by up to this fraction of the
# half-width, so two towns with the same bearing don't share one axis.
RIVER_BEARING_OFFSET = 0.05
# ...and meanders this much less than a random river, so "crosses the town"
# stays true: the full meander can carry a river off the walled core.
RIVER_BEARING_MEANDER = 0.5

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


def _room_to_bounds(point: Tuple[float, float], direction: Tuple[float, float], bounds: Tuple[float, float, float, float]) -> float:
    px, py = point
    dx, dy = direction
    min_x, min_y, max_x, max_y = bounds
    limits = []
    if dx > 0:
        limits.append((max_x - px) / dx)
    elif dx < 0:
        limits.append((min_x - px) / dx)
    if dy > 0:
        limits.append((max_y - py) / dy)
    elif dy < 0:
        limits.append((min_y - py) / dy)
    if not limits:
        return float("inf")
    return max(0.0, min(limits))


def _bearing_endpoints(bearing_deg: float, bounds: Tuple[float, float, float, float], rng):
    """Entry and exit points for a river that comes in from compass bearing
    `bearing_deg` (0 = north, clockwise) and leaves on the opposite side,
    crossing near the centre. town_shaper is Y-up (north = max_y), so a
    bearing's direction is (sin, cos)."""
    min_x, min_y, max_x, max_y = bounds
    rad = math.radians(bearing_deg)
    direction = (math.sin(rad), math.cos(rad))
    offset = rng.uniform(-RIVER_BEARING_OFFSET, RIVER_BEARING_OFFSET) * (max_x - min_x) / 2.0
    centre = ((min_x + max_x) / 2.0 + direction[1] * offset, (min_y + max_y) / 2.0 - direction[0] * offset)
    ends = []
    for sign in (1.0, -1.0):
        d = (direction[0] * sign, direction[1] * sign)
        reach = _room_to_bounds(centre, d, bounds)
        ends.append((centre[0] + d[0] * reach, centre[1] + d[1] * reach))
    return ends[0], ends[1]


def _curved_strip(start: Tuple[float, float], end: Tuple[float, float], rng, width: float, bounds: Tuple[float, float, float, float], meander: float = 1.0) -> Polygon:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return LineString([start, end]).buffer(width / 2.0)

    perp = (-dy / length, dx / length)  # unit vector perpendicular to start->end
    waypoint_count = rng.randint(2, 3)

    points = [start]
    for i in range(1, waypoint_count + 1):
        t = i / (waypoint_count + 1)
        base_x = start[0] + dx * t
        base_y = start[1] + dy * t
        target_magnitude = rng.uniform(RIVER_WAYPOINT_JITTER_MIN, RIVER_WAYPOINT_JITTER_MAX) * length * meander
        # Near-corner start/end pairs can produce a chord so short that a
        # purely length-proportional target is negligible (the buffer's round
        # end-caps then dominate the polygon's area, masking any curvature).
        # An absolute floor keeps the offset meaningful regardless of length;
        # the room cap below still keeps it safely inside bounds.
        target_magnitude = max(target_magnitude, RIVER_WAYPOINT_JITTER_ABS_MIN)

        room_pos = _room_to_bounds((base_x, base_y), perp, bounds)
        room_neg = _room_to_bounds((base_x, base_y), (-perp[0], -perp[1]), bounds)
        sign, room = (1.0, room_pos) if room_pos >= room_neg else (-1.0, room_neg)
        magnitude = min(target_magnitude, room * ROOM_SAFETY_FACTOR)

        points.append((base_x + perp[0] * sign * magnitude, base_y + perp[1] * sign * magnitude))
    points.append(end)

    # A raw polyline through 3-5 points has a sharp angular kink at every
    # waypoint -- a river zigzags between straight segments instead of
    # curving. Chaikin-smoothed the same way artery roads are.
    smoothed = chaikin_smooth(points, iterations=3)
    return LineString(smoothed).buffer(width / 2.0)


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
    river_bearings: Sequence[float] = (),
) -> List[WaterFeature]:
    """`river_bearings[i]`, when given, is the compass bearing river i flows
    in from; it leaves on the opposite side. Rivers beyond the list keep a
    random edge-to-edge course."""
    features: List[WaterFeature] = []
    feature_id = 0

    for i in range(num_rivers):
        rng = rng_for(seed, "water", "river", i)
        meander = 1.0
        if i < len(river_bearings):
            start, end = _bearing_endpoints(river_bearings[i], bounds, rng)
            meander = RIVER_BEARING_MEANDER
        else:
            start_edge, end_edge = rng.sample(_EDGES, 2)
            start = _point_on_edge(start_edge, bounds, rng)
            end = _point_on_edge(end_edge, bounds, rng)
        polygon = _curved_strip(start, end, rng, RIVER_WIDTH, bounds, meander)
        features.append(WaterFeature(id=feature_id, kind="river", polygon=polygon))
        feature_id += 1

    if has_coastline:
        polygon = _generate_coastline(seed, bounds)
        features.append(WaterFeature(id=feature_id, kind="coastline", polygon=polygon))
        feature_id += 1

    return features
