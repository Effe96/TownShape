import json
import math
import sqlite3
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch, Polygon as MplPolygon
from matplotlib.ticker import MultipleLocator
from shapely.geometry import Polygon as ShapelyPolygon, LineString
from shapely.ops import unary_union

from town_shaper.geometry import polygon_area, rotated_rect_corners

# Ink-on-parchment palette, styled after hand-drawn fantasy city maps
# (e.g. Watabou's town generator) rather than a GIS zoning overlay: one
# muted building color for the whole city, a walled inner core, and
# faint cartographic furniture (grid, scale bar, compass). No zone-color
# tint anywhere, farmland included: a hard-edged tinted polygon reads as
# "a zone boundary" to the eye regardless of how continuous the actual
# building density is, and farmland isn't zone-filled any more anyway
# (see town_shaper/countryside.py) -- density and building character
# alone tell the story, the same way civic/merchant/residential already
# do.
PARCHMENT_COLOR = "#dcd6c3"
GRID_COLOR = "#5a5648"
INK_COLOR = "#3d372c"

WATER_COLOR = "#8fa6ad"

# Districts that count as the "walled" inner city -- administrative,
# mercantile and wealthy quarters -- versus the unwalled outer sprawl
# (poor_residential slums, farmland_edge countryside). Mirrors the
# historic-core-vs-suburbs read of the reference map this style is
# based on.
WALLED_ZONE_TYPES = {"civic", "merchant", "rich_residential", "port"}
WALL_COLOR = INK_COLOR
WALL_TOWER_COUNT = 20

# building_type -> (marker, color, marker_size). Everything else renders as a
# generic dot. Shop/tavern get a smaller size since there are usually many of
# them; the rarer civic landmarks stay large and easy to spot.
LANDMARK_BUILDING_TYPES: Dict[str, Tuple[str, str, int]] = {
    "temple": ("^", "#5b3a5e", 60),
    "town_hall": ("s", "#1f2937", 60),
    "school": ("D", "#2f5d5a", 60),
    "university": ("D", "#2f4d2f", 60),
    "garrison": ("P", "#6b1f1f", 60),
    "guard_post": ("P", "#8a3a3a", 60),
    "arcane_shop": ("*", "#5a2d7a", 60),
    "harbormaster_office": ("h", "#1f2937", 60),
    "tavern": ("o", "#6b4423", 15),
    "shop": ("v", "#8a6d1f", 15),
}
GENERIC_BUILDING_COLOR = "#8f8a72"
BUILDING_EDGE_COLOR = "#4a4636"


def _polygon_with_holes_patch(rings: List, **kwargs) -> PathPatch:
    """A water feature's stored rings are exterior-then-holes (see
    town_db.generate._water_feature_rings), not disconnected separate
    shapes -- drawing each ring as its own filled MplPolygon paints every
    hole (e.g. an island in a lake or bay) solid water instead of leaving
    it as land. A single Path with one MOVETO/CLOSEPOLY loop per ring
    punches the later rings out of the first, same as any polygon-with-
    holes rendering."""
    vertices: List[Tuple[float, float]] = []
    codes: List[int] = []
    for ring in rings:
        if len(ring) < 3:
            continue
        vertices.extend(ring)
        vertices.append(ring[0])
        codes.append(MplPath.MOVETO)
        codes.extend([MplPath.LINETO] * (len(ring) - 1))
        codes.append(MplPath.CLOSEPOLY)
    return PathPatch(MplPath(vertices, codes), **kwargs)


def _is_multi_ring(footprint) -> bool:
    """True if `footprint` is a list of rings (a courtyard building's
    several disconnected wall pieces -- see town_shaper.blocks.ring_peel)
    rather than one flat ring."""
    return isinstance(footprint[0][0], (list, tuple))


def _nice_round_number(target: float) -> float:
    """Smallest of {1,2,5} x 10^n that is >= target/1.5-ish -- the classic
    map-scale-bar rounding so the bar reads e.g. "200 m" instead of "187 m"."""
    if target <= 0:
        return 1.0
    exponent = math.floor(math.log10(target))
    fraction = target / (10 ** exponent)
    if fraction < 1.5:
        nice = 1
    elif fraction < 3.5:
        nice = 2
    elif fraction < 7.5:
        nice = 5
    else:
        nice = 10
    return nice * (10 ** exponent)


def _draw_wall(ax, districts: List[Tuple[str, str]]) -> None:
    # Only each district's largest ring goes into the wall: a district's
    # `polygon` column can hold several polygon_parts (a river or
    # coastline can split a Voronoi cell), and unioning every part used
    # to draw a real, separate wall ring -- towers included -- around a
    # stranded secondary fragment whose buildings belong to a different
    # part entirely. Matches the same largest-part-only rule
    # town_shaper.blocks.compute_district_blocks and
    # generate_organic_residential_buildings already apply to buildings.
    walled_polygons = []
    for zone_type, polygon_json in districts:
        if zone_type not in WALLED_ZONE_TYPES:
            continue
        rings = [r for r in json.loads(polygon_json) if len(r) >= 3]
        if not rings:
            continue
        main_ring = max(rings, key=polygon_area)
        walled_polygons.append(ShapelyPolygon(main_ring).buffer(0))
    if not walled_polygons:
        return

    union = unary_union(walled_polygons)
    parts = list(union.geoms) if union.geom_type == "MultiPolygon" else [union]
    total_area = sum(part.area for part in parts)
    if total_area <= 0:
        return

    for part in parts:
        # Drop slivers left over from unioning clipped Voronoi cells --
        # not a real separate walled district.
        if part.area < 0.01 * total_area:
            continue
        ring = LineString(list(part.exterior.coords))
        xs, ys = zip(*part.exterior.coords)
        ax.plot(xs, ys, color=WALL_COLOR, linewidth=2.2, zorder=5)

        for i in range(WALL_TOWER_COUNT):
            point = ring.interpolate(i / WALL_TOWER_COUNT, normalized=True)
            ax.scatter([point.x], [point.y], s=18, c=WALL_COLOR, marker="s", zorder=5.5)


def _draw_map_furniture(ax) -> None:
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    map_width, map_height = xlim[1] - xlim[0], ylim[1] - ylim[0]
    if map_width <= 0 or map_height <= 0:
        return

    spacing = _nice_round_number(map_width / 5)
    ax.xaxis.set_major_locator(MultipleLocator(spacing))
    ax.yaxis.set_major_locator(MultipleLocator(spacing))
    ax.set_axisbelow(True)
    ax.grid(True, color=GRID_COLOR, linewidth=0.4, alpha=0.4)
    ax.tick_params(axis="both", which="both", labelbottom=False, labelleft=False, length=0)

    bar_x0 = xlim[0] + 0.04 * map_width
    bar_y0 = ylim[0] + 0.04 * map_height
    tick_h = 0.01 * map_height
    ax.plot([bar_x0, bar_x0 + spacing], [bar_y0, bar_y0], color=INK_COLOR, linewidth=2, zorder=10)
    for x in (bar_x0, bar_x0 + spacing):
        ax.plot([x, x], [bar_y0 - tick_h, bar_y0 + tick_h], color=INK_COLOR, linewidth=2, zorder=10)
    label = f"{spacing / 1000:g} km" if spacing >= 1000 else f"{spacing:g} m"
    ax.text(bar_x0 + spacing / 2, bar_y0 + 0.02 * map_height, label, ha="center", va="bottom",
            fontsize=8, color=INK_COLOR, zorder=10)

    arrow_x = xlim[1] - 0.06 * map_width
    arrow_y0 = ylim[0] + 0.04 * map_height
    arrow_y1 = arrow_y0 + 0.05 * map_height
    ax.annotate(
        "", xy=(arrow_x, arrow_y1), xytext=(arrow_x, arrow_y0),
        arrowprops=dict(arrowstyle="-|>", color=INK_COLOR, linewidth=1.5), zorder=10,
    )
    ax.text(arrow_x, arrow_y1 + 0.01 * map_height, "N", ha="center", va="bottom",
            fontsize=10, color=INK_COLOR, zorder=10)


def render_town(db_path: str, output_path: str) -> None:
    conn = sqlite3.connect(db_path)
    districts = conn.execute("SELECT zone_type, polygon FROM districts").fetchall()
    buildings = conn.execute(
        "SELECT x, y, building_type, width, height, rotation, footprint FROM buildings"
    ).fetchall()
    water_features = conn.execute("SELECT kind, polygon FROM water_features").fetchall()
    conn.close()

    fig, ax = plt.subplots(figsize=(12, 12))
    fig.patch.set_facecolor(PARCHMENT_COLOR)
    ax.set_facecolor(PARCHMENT_COLOR)

    for _kind, polygon_json in water_features:
        ax.add_patch(_polygon_with_holes_patch(
            json.loads(polygon_json), facecolor=WATER_COLOR, edgecolor="none", zorder=2,
        ))

    # No road lines are drawn at all any more. The old "boundary" (raw
    # Voronoi mesh between every pair of adjacent district anchors),
    # "artery" (always routed toward a farmland anchor -- meaningless now
    # that farms aren't anchor-based, see town_shaper/countryside.py) and
    # "spur" (one per anchor, to its nearest junction) each went through
    # rounds of filtering attempts -- zone checks, length caps, proximity
    # checks against the nearest building, even sampling proximity along
    # a line's entire length -- and every one of them still left a real
    # generated town somewhere with a visible stray line. The last spur
    # case: a line whose every sampled point was within 0-6 units of SOME
    # building still rendered as a plainly visible mark, because "a
    # building is nearby" is not "a building's own footprint covers this
    # exact pixel" -- nothing short of that would actually hide it, and a
    # real spur essentially never satisfies it. The block-cutting
    # algorithm's own building gaps are the only street texture this
    # renders now.

    landmark_points: Dict[str, List[Tuple[float, float]]] = {}
    for x, y, building_type, width, height, rotation, footprint_json in buildings:
        if building_type in LANDMARK_BUILDING_TYPES:
            landmark_points.setdefault(building_type, []).append((x, y))
            continue
        footprint = json.loads(footprint_json) if footprint_json else None
        rings = footprint if footprint and _is_multi_ring(footprint) else \
            [footprint] if footprint else [rotated_rect_corners(x, y, width, height, rotation)]
        for ring in rings:
            ax.add_patch(MplPolygon(
                ring, closed=True, facecolor=GENERIC_BUILDING_COLOR,
                edgecolor=BUILDING_EDGE_COLOR, linewidth=0.25, zorder=3,
            ))

    _draw_wall(ax, districts)

    for building_type, points in landmark_points.items():
        marker, color, size = LANDMARK_BUILDING_TYPES[building_type]
        ax.scatter(
            [p[0] for p in points], [p[1] for p in points],
            s=size, c=color, marker=marker, zorder=4, label=building_type,
            edgecolors="black", linewidths=0.5,
        )

    if landmark_points:
        legend = ax.legend(loc="upper right", title="Landmarks", fontsize=8, framealpha=0.85)
        legend.get_frame().set_facecolor(PARCHMENT_COLOR)
        legend.get_frame().set_edgecolor(INK_COLOR)

    ax.set_aspect("equal")
    ax.autoscale()
    _draw_map_furniture(ax)
    for spine in ax.spines.values():
        spine.set_color(INK_COLOR)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, facecolor=PARCHMENT_COLOR)
    plt.close(fig)
