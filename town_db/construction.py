"""Construction edits on an already-generated town's *physical* layer only:
the `buildings`/`districts`/`road_*` tables and the town's settlemaker SVG.
Never touches residents/households -- whatever decides a town needs new
buildings (a narrative request, an external simulation) calls in here; this
module only decides *where* they go and draws them.

Every edit is recorded in `construction_edits` (operation + params + the
building ids it produced), so a town's physical history is an ordered,
replayable log on top of its seed. Placement is deterministic: same DB +
same call -> same result.

Settlemaker towns don't persist roads or walls to the DB -- they only exist
in the SVG, so placement reads them from there (`_svg_lines`), and new side
streets are written back there (plus `road_nodes`/`road_edges`), where later
edits read them as roads too. The SVG's coordinates are the same local frame
the DB's footprints use, and its viewBox *is* `town_state`'s svg bounds (see
docs/superpowers/specs/2026-09-09-town-viewer-svg-overlay-design.md), so new
geometry is drawn by appending paths to settlemaker's own groups, styled by
its own stylesheet.

Growth is meant to read as medieval, not planned: side streets wander like
old field tracks and join other roads into a connected warren of lanes;
frontage has uneven setbacks, mixes eaves-to-street houses with gable-end
burgage plots, and thins out toward a lane's far end.

Fields: each settlemaker field plot is exactly one `farmland_edge` district.
A field new houses/streets cut into is trimmed back around them (the cut-off
part becomes a new `poor_residential` district) -- or converted outright
once most of it is built on. The lost field area is re-sown as new plots
just outside the farmland belt, widening the map frame if they need room.
"""
import heapq
import json
import math
import os
import re
import sqlite3
from typing import List, Optional, Tuple

import shapely
from shapely import affinity
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import nearest_points, unary_union
from shapely.prepared import prep

from town_db.schema import connect
from town_shaper.buildings import BUILDING_HOME_CAPACITY, JOB_VACANCIES_BY_BUILDING_TYPE
from town_shaper.seeding import rng_for

PLACEMENT_MODES = ("roads", "perimeter")

# Clearance kept around every existing building, wall and road edge. New
# houses stand almost wall-to-wall with each other (TERRACE_GAP), the way
# medieval street frontage was built up, not detached with yards.
BUILDING_GAP = 0.4
TERRACE_GAP = 0.12
WALL_CLEARANCE = 2.0
# Fallback house size (local units) for a town with no residence footprints
# to learn from -- roughly settlemaker's own small-house size.
DEFAULT_HOUSE_SIZE = (3.0, 2.2)
# Candidate lots are probed this often along a road/street; greedy placement
# then packs houses as tightly as BUILDING_GAP allows.
CANDIDATE_STEP = 0.5
# New non-residential buildings: this times a typical house, per side.
NONRESIDENTIAL_SCALE = 1.4
# Weight of distance-to-nearest-road when scoring non-residential lots, so
# taverns/shops stay on a road.
ROAD_AFFINITY = 2.0
# Ribbons along the roads stop this many town radii from the centre; the
# rest of the growth goes onto side streets. Side streets branch no farther
# out than STREET_REACH radii.
RIBBON_REACH = 1.6
STREET_REACH = 2.0
# Along every road/street, both sides, a lane-wide gap is kept free of houses
# every LANE_SPACING units (irregular, but seeded from the road's own start
# point so the gaps sit in the same place on every call), so a side street
# can branch through it later.
LANE_SPACING = (12.0, 28.0)
LANE_DEPTH = 8.0
# Side streets: start square through their lane gap for LANE_DEPTH, then
# veer up to STREET_BRANCH_ANGLE off square and wander, turning a smoothed
# random amount every STREET_STEP; they end by joining any other road they
# come within STREET_JOIN of, or when blocked / at their target length.
STREET_WIDTH = (1.2, 2.0)
STREET_LENGTH = (18.0, 40.0)
STREET_STEP = 3.0
STREET_TURN = 0.3
STREET_BRANCH_ANGLE = 0.6
STREET_JOIN = 5.0
MIN_STREET_LENGTH = 10.0
STREET_HOUSES = 14
# Frontage irregularity: extra setback, angle jitter, share of houses set
# gable-end to the street, and how much sparser a street gets by its far end.
SETBACK_JITTER = 0.5
ANGLE_JITTER = 0.08
GABLE_SHARE = 0.4
FAR_END_SPARSITY = 0.3
# Fields: a field is converted outright once more than FIELD_CONVERT_SHARE of
# it would be lost; otherwise trimmed back FIELD_CLEARANCE from new houses and
# streets. Plots get settlemaker-like chamfered corners of FIELD_ROUNDING.
FIELD_CONVERT_SHARE = 0.5
FIELD_CLEARANCE = 1.0
FIELD_SMOOTHING = 3.0
FIELD_ROUNDING = 1.0
# New fields: gap between plots, and how far outside the current belt the
# replacement band reaches, in typical-plot widths.
FIELD_GAP = 0.8
FIELD_BAND = 2.0
FRAME_MARGIN = 5.0

CONSTRUCTION_EDITS_SQL = """
CREATE TABLE IF NOT EXISTS construction_edits (
    id INTEGER PRIMARY KEY,
    operation TEXT NOT NULL,
    params TEXT NOT NULL,
    building_ids TEXT NOT NULL
)
"""

_COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")


# --- SVG helpers -------------------------------------------------------------

def _svg_group(svg: str, group_id: str) -> Tuple[int, int]:
    """(start, end) of a flat `<g id=...>` group's inner content, end being
    the index of its closing `</g>`; (-1, -1) if absent. Settlemaker's
    groups this module reads/writes are flat (no nested <g>)."""
    start = svg.find(f'<g id="{group_id}"')
    if start < 0:
        return -1, -1
    start = svg.index(">", start) + 1
    return start, svg.index("</g>", start)


def _svg_insert(svg: str, group_id: str, paths: List[str], before: Optional[str] = None) -> str:
    """Append paths to a group -- or insert them before the group's first
    occurrence of `before`, if present."""
    start, end = _svg_group(svg, group_id)
    if start < 0 or not paths:
        return svg
    at = end
    if before:
        found = svg.find(before, start, end)
        if found >= 0:
            at = found
    return svg[:at] + "\n".join(paths) + "\n" + svg[at:]


def _points(d: str) -> List[Tuple[float, float]]:
    return [(float(x), float(y)) for x, y in _COORD_RE.findall(d)]


def _svg_lines(svg: str, group_id: str, path_class: Optional[str] = None) -> List[Tuple[LineString, float]]:
    """Every `<path>` in a group (optionally only those of `path_class`) as
    (polyline, stroke width). Settlemaker emits only absolute M/L(/Z) paths
    in #roads and #walls."""
    start, end = _svg_group(svg, group_id)
    if start < 0:
        return []
    lines = []
    for match in re.finditer(r"<path\b([^>]*)/?>", svg[start:end]):
        attrs = match.group(1)
        if path_class and f'class="{path_class}"' not in attrs:
            continue
        d = re.search(r'\sd="([^"]+)"', attrs)
        if not d:
            continue
        points = _points(d.group(1))
        if len(points) < 2:
            continue
        width = re.search(r'stroke-width="([\d.]+)"', attrs)
        lines.append((LineString(points), float(width.group(1)) if width else 0.0))
    return lines


def _svg_field_plots(svg: str) -> List[Tuple[str, Polygon]]:
    """(d, polygon) of every field plot in #fields."""
    start, end = _svg_group(svg, "fields")
    if start < 0:
        return []
    return [(d, Polygon(_points(d)).buffer(0)) for d in re.findall(r'class="plot" d="([^"]+)"', svg[start:end])]


def _svg_landscape(svg: str):
    """Footprints of settlemaker's drawn landscape features the DB doesn't
    know about: glyphs placed by `<use transform="translate(x,y) scale(s)
    ...">` in #symbols (mills, wells), #canopy (trees) and #marks, each a
    disc of the glyph's half-size; plus #greens' polygons (orchards)."""
    shapes = []
    for group_id in ("symbols", "canopy", "marks"):
        start, end = _svg_group(svg, group_id)
        if start < 0:
            continue
        for x, y, scale, size in re.findall(
                r'<use href="#[^"]+" transform="translate\((-?[\d.]+),(-?[\d.]+)\) scale\(([\d.]+)\)[^"]*'
                r'translate\((-?[\d.]+),', svg[start:end]):
            shapes.append(Point(float(x), float(y)).buffer(abs(float(size)) * float(scale)))
    start, end = _svg_group(svg, "greens")
    if start >= 0:
        shapes += [Polygon(_points(d)).buffer(0) for d in re.findall(r'\sd="([^"]+)"', svg[start:end])
                   if len(_points(d)) >= 3]
    return unary_union(shapes)


def _svg_frame(svg: str) -> Optional[Tuple[float, float, float, float]]:
    """(min_x, min_y, width, height) from the viewBox."""
    match = re.search(r'viewBox="([^"]+)"', svg)
    return tuple(map(float, match.group(1).split())) if match else None


def _set_svg_frame(svg: str, old, new) -> str:
    """Settlemaker writes its frame three times: the viewBox, the frame
    clipPath rect and the paper background rect."""
    def fmt(v):
        return f"{v:.1f}"
    ox, oy, ow, oh = old
    nx, ny, nw, nh = new
    svg = svg.replace(f'viewBox="{fmt(ox)} {fmt(oy)} {fmt(ow)} {fmt(oh)}"',
                      f'viewBox="{fmt(nx)} {fmt(ny)} {fmt(nw)} {fmt(nh)}"', 1)
    return svg.replace(f'x="{fmt(ox)}" y="{fmt(oy)}" width="{fmt(ow)}" height="{fmt(oh)}"',
                       f'x="{fmt(nx)}" y="{fmt(ny)}" width="{fmt(nw)}" height="{fmt(nh)}"')


def _path_d(coords) -> str:
    return "M" + "L".join(f"{x:.2f},{y:.2f}" for x, y in coords)


# --- geometry helpers --------------------------------------------------------

def _rect(center: Tuple[float, float], width: float, depth: float, angle: float) -> Polygon:
    """A width x depth rectangle centred on `center`, its width axis along
    `angle` (radians)."""
    cx, cy = center
    shape = Polygon([(-width / 2, -depth / 2), (width / 2, -depth / 2), (width / 2, depth / 2), (-width / 2, depth / 2)])
    return affinity.translate(affinity.rotate(shape, angle, origin=(0, 0), use_radians=True), cx, cy)


def _largest(geometry) -> Optional[Polygon]:
    parts = [g for g in getattr(geometry, "geoms", [geometry]) if isinstance(g, Polygon) and not g.is_empty]
    return max(parts, key=lambda p: p.area) if parts else None


def _chamfer(plot: Polygon) -> Optional[Polygon]:
    """Settlemaker-style field outline: corners cut, no holes."""
    shape = _largest(plot.buffer(-FIELD_ROUNDING, join_style=2).buffer(FIELD_ROUNDING, join_style=1, quad_segs=1))
    return Polygon(shape.exterior).simplify(0.1) if shape is not None else None


def _house_sizes(footprints: List[Polygon]) -> List[Tuple[float, float]]:
    """(width, depth) of every existing footprint's minimum rotated
    rectangle, long side first -- new houses are sampled from these so they
    match the town's own grain."""
    sizes = []
    for footprint in footprints:
        corners = list(footprint.minimum_rotated_rectangle.exterior.coords)[:4]
        a = math.dist(corners[0], corners[1])
        b = math.dist(corners[1], corners[2])
        if min(a, b) > 0:
            sizes.append((max(a, b), min(a, b)))
    if not sizes:
        return [DEFAULT_HOUSE_SIZE]
    # Middle half by area only: settlemaker's block subdivision leaves
    # slivers and merged lots at both tails that read as noise when copied.
    sizes.sort(key=lambda s: s[0] * s[1])
    return sizes[len(sizes) // 4: max(len(sizes) * 3 // 4, 1)]


def _at(line: LineString, distance: float):
    """(point, tangent angle) at an arc length along a line."""
    p = line.interpolate(distance)
    q = line.interpolate(min(distance + 0.1, line.length))
    r = line.interpolate(max(distance - 0.1, 0))
    return (p.x, p.y), math.atan2(q.y - r.y, q.x - r.x)


def _normal(angle: float, side: int) -> Tuple[float, float]:
    return -math.sin(angle) * side, math.cos(angle) * side


def _frontage(line: LineString, stroke: float):
    """(arc length, road-edge point, outward normal, road angle) for lots
    along both sides of a road, every CANDIDATE_STEP."""
    distance = CANDIDATE_STEP / 2
    while distance < line.length:
        (px, py), angle = _at(line, distance)
        for side in (1, -1):
            nx, ny = _normal(angle, side)
            yield distance, (px + nx * stroke / 2, py + ny * stroke / 2), (nx, ny), angle
        distance += CANDIDATE_STEP


def _lanes(line: LineString, stroke: float):
    """(edge point, outward unit normal, reservation rect) for every lane
    slot along a road, both sides. The rect is the strip a branching street
    needs kept free of frontage houses. Spacing is irregular but seeded from
    the line's own (rounded) start point, so it's stable across calls."""
    x0, y0 = line.coords[0]
    lane_rng = rng_for("lanes", round(x0, 1), round(y0, 1))
    distance = lane_rng.uniform(*LANE_SPACING) / 2
    while distance < line.length:
        (px, py), angle = _at(line, distance)
        for side in (1, -1):
            nx, ny = _normal(angle, side)
            edge = (px + nx * stroke / 2, py + ny * stroke / 2)
            centre = (edge[0] + nx * LANE_DEPTH / 2, edge[1] + ny * LANE_DEPTH / 2)
            yield edge, (nx, ny), _rect(centre, max(STREET_WIDTH) + 4 * BUILDING_GAP, LANE_DEPTH, angle)
        distance += lane_rng.uniform(*LANE_SPACING)


def _ring_candidates(built, depth):
    """Lot centres in one row just outside the built-up edge, long side
    along it."""
    ring = built.buffer(BUILDING_GAP + depth / 2)
    candidates = []
    for polygon in getattr(ring, "geoms", [ring]):
        distance = 0.0
        while distance < polygon.exterior.length:
            candidates.append(_at(polygon.exterior, distance))
            distance += CANDIDATE_STEP
    return candidates


def _new_fields(occupied, obstacles, area_needed, plot_area, centre, rng) -> List[Polygon]:
    """Field plots totalling ~area_needed in a band just outside `occupied`
    (town + current farmland), nearest the town first: Voronoi cells of
    random points in the band, clipped to it, inset and chamfered."""
    if area_needed <= 0:
        return []
    band_width = FIELD_BAND * math.sqrt(plot_area)
    # Only the *outer* edge counts: close small gaps between pieces and fill
    # holes, so open ground between the town and its fields never gets sown.
    closed = occupied.buffer(band_width / 2).buffer(-band_width / 2)
    occupied = unary_union([Polygon(p.exterior) for p in getattr(closed, "geoms", [closed])] + [occupied])
    band = occupied.buffer(band_width).difference(occupied.buffer(FIELD_GAP)).difference(obstacles)
    if band.is_empty:
        return []
    min_x, min_y, max_x, max_y = band.bounds
    target = max(8, int(band.area / plot_area * 0.8))
    prepared = prep(band)
    points = []
    for _ in range(target * 20):
        if len(points) >= target:
            break
        p = Point(rng.uniform(min_x, max_x), rng.uniform(min_y, max_y))
        if prepared.contains(p):
            points.append(p)
    if len(points) < 2:
        return []
    pieces = []
    for cell in shapely.voronoi_polygons(MultiPoint(points), extend_to=band.envelope).geoms:
        clipped = cell.intersection(band)
        for part in getattr(clipped, "geoms", [clipped]):
            if not isinstance(part, Polygon) or not 0.6 * plot_area <= part.area <= 1.8 * plot_area:
                continue
            plot = _largest(part.buffer(-FIELD_GAP / 2, join_style=2))
            plot = _chamfer(plot) if plot is not None else None
            if plot is not None and not plot.is_empty:
                pieces.append(plot)
    pieces.sort(key=lambda p: p.centroid.distance(Point(centre)))
    fields, total = [], 0.0
    for plot in pieces:
        if total >= area_needed:
            break
        fields.append(plot)
        total += plot.area
    return fields


# --- the edit ----------------------------------------------------------------

def add_buildings(
    db_path: str,
    count: int,
    where: str = "roads",
    building_type: str = "residence",
    svg_path: Optional[str] = None,
) -> List[int]:
    """Build up to `count` new `building_type` buildings outside the town's
    existing built-up area, and return their ids (fewer than `count` if the
    frame runs out of room).

    where="roads": ribbon development -- lots fronting the approach roads,
    nearest the town first, up to RIBBON_REACH town radii out; the rest goes
    onto side streets. where="perimeter": side streets only -- new lanes
    branch off the roads (and off each other) through the gaps ribbons
    leave, wander, and join other roads, lined with houses on both sides.

    Non-residential types (capacity 0: tavern, shop, workshop...) ignore
    `where` and take the most central free lot on a road.

    "Built-up area" = every generation-time non-farmland district, the walls
    and every building, so new construction never lands in a plaza, park or
    inside the walls -- it extends the town outward, onto its fields, which
    are trimmed or converted and re-sown further out."""
    if count < 1:
        raise ValueError("count must be >= 1")
    if where not in PLACEMENT_MODES:
        raise ValueError(f"where must be one of {PLACEMENT_MODES}")
    if building_type not in JOB_VACANCIES_BY_BUILDING_TYPE:
        raise ValueError(f"unknown building_type {building_type!r}")
    if svg_path is None:
        svg_path = os.path.splitext(db_path)[0] + ".svg"
    svg = ""
    if os.path.exists(svg_path):
        with open(svg_path, encoding="utf-8") as f:
            svg = f.read()

    conn = connect(db_path)
    try:
        conn.execute(CONSTRUCTION_EDITS_SQL)
        edit_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM construction_edits").fetchone()[0]
        try:
            seed_row = conn.execute("SELECT seed FROM generation_parameters WHERE id = 1").fetchone()
        except sqlite3.OperationalError:  # town_db-only town, no narrative parameters table
            seed_row = None
        rng = rng_for(seed_row[0] if seed_row else "town", "construction", edit_id)
        # Districts earlier edits turned into living areas: buildable, unlike
        # the generation-time town core.
        grown_before = set()
        for (params,) in conn.execute("SELECT params FROM construction_edits"):
            params = json.loads(params)
            grown_before.update(params.get("converted_district_ids", []) + params.get("living_district_ids", []))

        rows = conn.execute("SELECT building_type, x, y, width, height, rotation, footprint FROM buildings").fetchall()
        existing = []
        for b_type, x, y, w, h, rot, footprint in rows:
            if footprint:
                existing.append((b_type, Polygon(json.loads(footprint))))
            elif w and h:
                existing.append((b_type, _rect((x, y), w, h, rot)))
        if BUILDING_HOME_CAPACITY.get(building_type, 0) == 0:
            # Settlemaker gives taverns/shops whatever lot they landed on --
            # often several houses' worth -- so copying those makes new ones
            # oversized squares. A new one is a larger-than-average house.
            sizes = [(w * NONRESIDENTIAL_SCALE, d * NONRESIDENTIAL_SCALE) for w, d in _house_sizes(
                [p for t, p in existing if t == "residence"] or [p for _, p in existing])]
        else:
            sizes = _house_sizes([p for t, p in existing if t == building_type] or [p for _, p in existing])
        footprints = [p for _, p in existing]

        districts = [(d_id, zone, unary_union([Polygon(part).buffer(0) for part in json.loads(poly) if len(part) >= 3]))
                     for d_id, zone, poly in conn.execute("SELECT id, zone_type, polygon FROM districts")]
        core = unary_union([poly for d_id, zone, poly in districts
                            if zone != "farmland_edge" and d_id not in grown_before])
        water = unary_union([Polygon(json.loads(poly)[0], json.loads(poly)[1:])
                             for (poly,) in conn.execute("SELECT polygon FROM water_features")])

        # Casing and core paths trace the same centreline; the wider casing
        # is the road's real visual footprint.
        roads = [(line, width) for line, width in _svg_lines(svg, "roads", "casing") if width > 0]
        walls = unary_union([line.buffer(WALL_CLEARANCE) for line, _ in _svg_lines(svg, "walls")])
        raw_frame = _svg_frame(svg)
        if raw_frame:
            fx, fy, fw, fh = raw_frame
            frame = Polygon([(fx, fy), (fx + fw, fy), (fx + fw, fy + fh), (fx, fy + fh)])
        else:
            frame = unary_union(footprints + [core]).envelope.buffer(20)
        house_frame = frame.buffer(-max(DEFAULT_HOUSE_SIZE))

        centre_point = unary_union(footprints).centroid if footprints else Point(0, 0)
        centre = (centre_point.x, centre_point.y)
        radius = math.sqrt(unary_union([core, walls]).area / math.pi) or 20.0
        depth = sizes[len(sizes) // 2][1]

        static_blocked = prep(unary_union([p.buffer(BUILDING_GAP) for p in footprints]
                                          + [core, water, walls, _svg_landscape(svg).buffer(BUILDING_GAP)]))
        road_union = unary_union([line.buffer(w / 2) for line, w in roads])
        lane_slots = []  # (edge, normal, rect, parent line, parent width)
        for line, w in roads:
            lane_slots += [(e, n, r, line, w) for e, n, r in _lanes(line, w) if not static_blocked.intersects(r)]
        state = {"roads": prep(road_union), "lanes": prep(unary_union([s[2] for s in lane_slots]))}

        placed: List[Polygon] = []
        streets: List[Tuple[LineString, float]] = []

        def fits(shape) -> bool:
            return (house_frame.contains(shape) and not static_blocked.intersects(shape)
                    and not state["roads"].intersects(shape) and not state["lanes"].intersects(shape)
                    and all(shape.distance(other) >= TERRACE_GAP for other in placed))

        def place_centred(candidates, limit) -> int:
            """Greedy, best score first: (score, lot centre, angle)."""
            before = len(placed)
            for _, c, angle in sorted(candidates, key=lambda sca: sca[0]):
                if len(placed) >= count or len(placed) - before >= limit:
                    break
                w, d = rng.choice(sizes)
                shape = _rect(c, w, d, angle + rng.uniform(-0.05, 0.05))
                if fits(shape):
                    placed.append(shape)
            return len(placed) - before

        def place_frontage(candidates, limit, length=None) -> int:
            """Greedy, best score first: (score, arc length, road-edge point,
            normal, angle). Each house gets its own setback and tilt, ~40%
            stand gable-end to the street, and if `length` is given, lots
            thin out toward the street's far end."""
            before = len(placed)
            for _, s, (ex, ey), (nx, ny), angle in sorted(candidates, key=lambda c: c[0]):
                if len(placed) >= count or len(placed) - before >= limit:
                    break
                if length and rng.random() < FAR_END_SPARSITY * s / length:
                    continue
                w, d = rng.choice(sizes)
                along, across = (d, w) if rng.random() < GABLE_SHARE else (w, d)
                setback = BUILDING_GAP + rng.uniform(0, SETBACK_JITTER) + across / 2
                shape = _rect((ex + nx * setback, ey + ny * setback), along, across,
                              angle + rng.uniform(-ANGLE_JITTER, ANGLE_JITTER))
                if fits(shape):
                    placed.append(shape)
            return len(placed) - before

        def open_street(edge, normal, parent_line, parent_width) -> Optional[Tuple[LineString, float]]:
            """A wandering lane from a lane slot: straight through the gap,
            then veering and turning; ends on joining another road, when
            blocked, or at its target length. None if under MIN_STREET_LENGTH
            without having joined anything."""
            width = rng.uniform(*STREET_WIDTH)
            target = rng.uniform(*STREET_LENGTH)
            start_disk = Point(edge).buffer(parent_width / 2 + 0.6)
            others = road_union.difference(parent_line.buffer(parent_width / 2 + 0.05))
            prepared_others = prep(others)

            def clear(segment, end_disk=None) -> bool:
                corridor = segment.buffer(width / 2 + BUILDING_GAP).difference(start_disk)
                if end_disk is not None:
                    corridor = corridor.difference(end_disk)
                return (house_frame.contains(segment) and not static_blocked.intersects(corridor)
                        and not prepared_others.intersects(corridor)
                        and not any(corridor.intersects(p) for p in placed))

            nx, ny = normal
            points = [edge, (edge[0] + nx * LANE_DEPTH, edge[1] + ny * LANE_DEPTH)]
            if not clear(LineString(points)):
                return None
            heading = math.atan2(ny, nx) + rng.uniform(-STREET_BRANCH_ANGLE, STREET_BRANCH_ANGLE)
            turn, length, joined = 0.0, LANE_DEPTH, False
            while length < target:
                turn = 0.6 * turn + rng.uniform(-STREET_TURN, STREET_TURN)
                heading += turn
                last = points[-1]
                p = (last[0] + STREET_STEP * math.cos(heading), last[1] + STREET_STEP * math.sin(heading))
                if not others.is_empty and others.distance(Point(p)) < STREET_JOIN:
                    q = nearest_points(others, Point(p))[0]
                    q = (q.x, q.y)
                    if clear(LineString([last, q]), Point(q).buffer(width + 0.6)):
                        points.append(q)
                        joined = True
                    break
                if not clear(LineString([last, p])):
                    break
                points.append(p)
                length += STREET_STEP
            if length < MIN_STREET_LENGTH and not joined:
                return None
            return LineString(points), width

        if BUILDING_HOME_CAPACITY.get(building_type, 0) == 0:
            # Taverns, shops, workshops...: the most central free lot that
            # still sits on a road -- by the gates, not at the end of a ribbon.
            reach = RIBBON_REACH * radius
            candidates = []
            for line, w in roads:
                for _, (ex, ey), (nx, ny), angle in _frontage(line, w):
                    c = (ex + nx * (BUILDING_GAP + depth / 2), ey + ny * (BUILDING_GAP + depth / 2))
                    if math.dist(c, centre) <= reach:
                        candidates.append((c, angle))
            candidates += _ring_candidates(unary_union([core, walls] + footprints), depth)
            place_centred([(math.dist(c, centre) + ROAD_AFFINITY * road_union.distance(Point(c)), c, a)
                           for c, a in candidates], count)
        else:
            if where == "roads":
                reach = RIBBON_REACH * radius
                place_frontage([(math.dist(e, centre), s, e, n, a) for line, w in roads
                                for s, e, n, a in _frontage(line, w) if math.dist(e, centre) <= reach], count)
            # Overflow goes onto side streets, innermost lane slots first;
            # each new street adds its own lane slots, so the warren grows
            # outward branch by branch.
            queue = []

            def push(slot):
                distance = math.dist(slot[0], centre)
                if distance <= STREET_REACH * radius:
                    heapq.heappush(queue, (distance + rng.uniform(0, radius / 3), len(queue), slot))

            for slot in lane_slots:
                push(slot)
            while queue and len(placed) < count:
                _, _, (edge, normal, _, parent_line, parent_width) = heapq.heappop(queue)
                opened = open_street(edge, normal, parent_line, parent_width)
                if opened is None:
                    continue
                street, width = opened
                streets.append(opened)
                road_union = road_union.union(street.buffer(width / 2))
                new_slots = [(e, n, r, street, width) for e, n, r in _lanes(street, width)
                             if not static_blocked.intersects(r)]
                lane_slots += new_slots
                state["roads"] = prep(road_union)
                state["lanes"] = prep(unary_union([s[2] for s in lane_slots]))
                place_frontage([(s + rng.uniform(0, 2), s, e, n, a) for s, e, n, a in _frontage(street, width)],
                               STREET_HOUSES, street.length)
                for slot in new_slots:
                    push(slot)

        # Fields new houses/streets cut into: trimmed back around them, the
        # cut-off part becoming a living-area district -- or converted
        # outright if most of the field would go. Lost area is re-sown.
        # Closed (grow, then shrink) so fields recede in soft curves around
        # groups of houses rather than showing a house-shaped bite per house.
        cleared = unary_union(placed + [s.buffer(w / 2) for s, w in streets]).buffer(
            FIELD_CLEARANCE + FIELD_SMOOTHING).buffer(-FIELD_SMOOTHING)
        plots = _svg_field_plots(svg)
        plot_area = (sum(p.area for _, p in plots) / len(plots)) if plots else 0.0
        converted, trimmed, living = [], {}, []  # trimmed: district id -> kept polygon
        lost_area = 0.0
        for d_id, zone, poly in districts:
            if zone != "farmland_edge" or d_id in grown_before or not poly.intersects(cleared):
                continue
            kept = _largest(poly.difference(cleared))
            kept = _chamfer(kept) if kept is not None else None
            if kept is None or kept.area < (1 - FIELD_CONVERT_SHARE) * poly.area:
                converted.append(d_id)
                lost_area += poly.area
            else:
                trimmed[d_id] = kept
                lost_area += poly.area - kept.area

        next_district = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM districts").fetchone()[0]
        if converted:
            marks = ",".join("?" * len(converted))
            conn.execute(f"UPDATE districts SET zone_type = 'poor_residential' WHERE id IN ({marks})", converted)
            conn.execute(f"UPDATE buildings SET zone_type = 'poor_residential' WHERE district_id IN ({marks})", converted)
        polys = {d_id: poly for d_id, _, poly in districts}
        zones = {d_id: zone for d_id, zone, _ in districts}
        for d_id in converted:
            zones[d_id] = "poor_residential"
        for d_id, kept in trimmed.items():
            conn.execute("UPDATE districts SET polygon = ? WHERE id = ?",
                         (json.dumps([[list(pt) for pt in kept.exterior.coords[:-1]]]), d_id))
            cut = polys[d_id].difference(kept)
            parts = [p for p in getattr(cut, "geoms", [cut]) if isinstance(p, Polygon) and p.area > 0.5]
            if parts:
                conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (?, 'poor_residential', ?)",
                             (next_district, json.dumps([[list(pt) for pt in p.exterior.coords[:-1]] for p in parts])))
                polys[next_district], zones[next_district] = unary_union(parts), "poor_residential"
                living.append(next_district)
                next_district += 1
            polys[d_id] = kept

        def plot_for(d_id):
            return next((d for d, p in plots if polys_before[d_id].contains(p.representative_point())), None)

        polys_before = {d_id: poly for d_id, _, poly in districts}
        removed_plot_ds = [d for d in (plot_for(d_id) for d_id in converted) if d]
        replaced_plot_ds = {d: trimmed[d_id] for d_id in trimmed for d in [plot_for(d_id)] if d}

        fields = []
        if lost_area and plot_area:
            occupied = unary_union(list(polys.values()) + [cleared, walls] + footprints)
            fields = _new_fields(occupied, unary_union([water, road_union.buffer(FIELD_GAP)]),
                                 lost_area, plot_area, centre, rng)
        field_ids = list(range(next_district, next_district + len(fields)))
        for field_id, field in zip(field_ids, fields):
            conn.execute("INSERT INTO districts (id, zone_type, polygon) VALUES (?, 'farmland_edge', ?)",
                         (field_id, json.dumps([[list(pt) for pt in field.exterior.coords[:-1]]])))
            polys[field_id], zones[field_id] = field, "farmland_edge"

        next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM buildings").fetchone()[0]
        new_ids = []
        svg_buildings, svg_shadows = [], []
        for offset, shape in enumerate(placed):
            building_id = next_id + offset
            centroid = shape.centroid
            district_id = min(polys, key=lambda d_id: polys[d_id].distance(centroid))
            corners = [list(pt) for pt in list(shape.exterior.coords)[:4]]
            w = math.dist(corners[0], corners[1])
            d = math.dist(corners[1], corners[2])
            angle = math.atan2(corners[1][1] - corners[0][1], corners[1][0] - corners[0][0])
            conn.execute(
                "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, name, "
                "width, height, rotation, footprint) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                (building_id, district_id, zones[district_id], building_type, centroid.x, centroid.y,
                 BUILDING_HOME_CAPACITY.get(building_type, 0), w, d, angle, json.dumps(corners)),
            )
            new_ids.append(building_id)
            path = _path_d(corners) + "Z"
            svg_buildings.append(f'<path data-building-id="{building_id}" d="{path}"/>')
            svg_shadows.append(f'<path d="{path}"/>')

        # Streets go into the DB road graph too (settlemaker's own roads
        # never did), so consumers other than the SVG can see them.
        next_node = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM road_nodes").fetchone()[0]
        next_edge = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM road_edges").fetchone()[0]
        for street, _ in streets:
            node_ids = list(range(next_node, next_node + len(street.coords)))
            conn.executemany("INSERT INTO road_nodes (id, kind, x, y) VALUES (?, 'street', ?, ?)",
                             [(n, x, y) for n, (x, y) in zip(node_ids, street.coords)])
            conn.executemany("INSERT INTO road_edges (id, from_node_id, to_node_id, road_type) VALUES (?, ?, ?, 'street')",
                             [(next_edge + i, a, b) for i, (a, b) in enumerate(zip(node_ids, node_ids[1:]))])
            next_node += len(node_ids)
            next_edge += len(node_ids) - 1

        # Widen the frame if new fields spill past it.
        new_frame = None
        if raw_frame and fields:
            fx, fy, fw, fh = raw_frame
            bx0, by0, bx1, by1 = unary_union(fields).bounds
            nx0, ny0 = min(fx, bx0 - FRAME_MARGIN), min(fy, by0 - FRAME_MARGIN)
            nx1, ny1 = max(fx + fw, bx1 + FRAME_MARGIN), max(fy + fh, by1 + FRAME_MARGIN)
            if (nx0, ny0, nx1, ny1) != (fx, fy, fx + fw, fy + fh):
                new_frame = (round(nx0, 1), round(ny0, 1), round(nx1 - nx0, 1), round(ny1 - ny0, 1))
                conn.execute(
                    "UPDATE town_state SET svg_min_x = ?, svg_min_y = ?, svg_max_x = ?, svg_max_y = ? WHERE id = 1",
                    (new_frame[0], new_frame[1], new_frame[0] + new_frame[2], new_frame[1] + new_frame[3]),
                )

        conn.execute(
            "INSERT INTO construction_edits (id, operation, params, building_ids) VALUES (?, ?, ?, ?)",
            (edit_id, "add_buildings",
             json.dumps({"count": count, "where": where, "building_type": building_type,
                         "streets": len(streets), "converted_district_ids": converted,
                         "trimmed_district_ids": sorted(trimmed), "living_district_ids": living,
                         "new_field_district_ids": field_ids}),
             json.dumps(new_ids)),
        )
        conn.commit()
    finally:
        conn.close()

    if svg and (new_ids or fields or removed_plot_ds or replaced_plot_ds):
        for d in removed_plot_ds:
            svg = re.sub(r'<path class="(?:plot|hatch)" d="' + re.escape(d) + r'"[^>]*/>\n?', "", svg)
        for d, kept in replaced_plot_ds.items():
            svg = svg.replace(f'd="{d}"', f'd="{_path_d(kept.exterior.coords[:-1])}Z"')
        patterns = sorted(set(re.findall(r'<pattern id="([^"]*field-a\d+)"', svg))) or [None]
        field_paths = []
        for field in fields:
            d = _path_d(field.exterior.coords[:-1]) + "Z"
            field_paths.append(f'<path class="plot" d="{d}"/>')
            pattern = rng.choice(patterns)
            if pattern:
                field_paths.append(f'<path class="hatch" d="{d}" fill="url(#{pattern})"/>')
        svg = _svg_insert(svg, "fields", field_paths)
        svg = _svg_insert(svg, "roads", [f'<path class="casing" d="{_path_d(s.coords)}" stroke-width="{w:.2f}"/>'
                                         for s, w in streets], before='<path class="core"')
        svg = _svg_insert(svg, "roads", [f'<path class="core" d="{_path_d(s.coords)}" stroke-width="{w * 0.7:.2f}"/>'
                                         for s, w in streets])
        svg = _svg_insert(svg, "buildings", svg_buildings)
        svg = _svg_insert(svg, "shadows", svg_shadows)
        if new_frame:
            svg = _set_svg_frame(svg, raw_frame, new_frame)
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg)
    return new_ids
