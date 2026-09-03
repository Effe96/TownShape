import json
import math
import sqlite3
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon

ZONE_COLORS: Dict[str, str] = {
    "civic": "#c9a0dc",
    "merchant": "#f4a460",
    "rich_residential": "#ffd700",
    "poor_residential": "#a9a9a9",
    "farmland_edge": "#9acd32",
    "port": "#87ceeb",
}
DEFAULT_ZONE_COLOR = "#dddddd"

WATER_COLOR = "#4a90d9"

ROAD_STYLE = {
    "radial": {"width": 2.5, "color": "#3a3a3a"},
    "boundary": {"width": 1.4, "color": "#5a5a5a"},
    "spur": {"width": 0.8, "color": "#7a7a7a"},
    "local": {"width": 0.5, "color": "#9a9a9a"},
}

# building_type -> (marker, color, marker_size). Everything else renders as a
# generic dot. Shop/tavern get a smaller size since there are usually many of
# them; the rarer civic landmarks stay large and easy to spot.
LANDMARK_BUILDING_TYPES: Dict[str, Tuple[str, str, int]] = {
    "temple": ("^", "#8b008b", 60),
    "town_hall": ("s", "#000080", 60),
    "school": ("D", "#008080", 60),
    "university": ("D", "#006400", 60),
    "garrison": ("P", "#8b0000", 60),
    "guard_post": ("P", "#cd5c5c", 60),
    "arcane_shop": ("*", "#9400d3", 60),
    "harbormaster_office": ("h", "#00008b", 60),
    "tavern": ("o", "#b5651d", 15),
    "shop": ("v", "#daa520", 15),
}
GENERIC_BUILDING_COLOR = "#555555"


def _rotated_rect_corners(cx: float, cy: float, width: float, height: float, rotation: float):
    hw, hh = width / 2.0, height / 2.0
    cos_r, sin_r = math.cos(rotation), math.sin(rotation)
    return [
        (cx + lx * cos_r - ly * sin_r, cy + lx * sin_r + ly * cos_r)
        for lx, ly in [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    ]


def render_town(db_path: str, output_path: str) -> None:
    conn = sqlite3.connect(db_path)
    districts = conn.execute("SELECT zone_type, polygon FROM districts").fetchall()
    buildings = conn.execute(
        "SELECT x, y, building_type, width, height, rotation FROM buildings"
    ).fetchall()
    water_features = conn.execute("SELECT kind, polygon FROM water_features").fetchall()
    road_nodes = conn.execute("SELECT id, x, y FROM road_nodes").fetchall()
    road_edges = conn.execute("SELECT from_node_id, to_node_id, road_type FROM road_edges").fetchall()
    conn.close()

    fig, ax = plt.subplots(figsize=(12, 12))

    for _kind, polygon_json in water_features:
        for ring in json.loads(polygon_json):
            ax.add_patch(MplPolygon(
                ring, closed=True, facecolor=WATER_COLOR, edgecolor="none", alpha=0.6, zorder=1,
            ))

    seen_zone_types: List[str] = []
    for zone_type, polygon_json in districts:
        color = ZONE_COLORS.get(zone_type, DEFAULT_ZONE_COLOR)
        for ring in json.loads(polygon_json):
            ax.add_patch(MplPolygon(
                ring, closed=True, facecolor=color, edgecolor="black", linewidth=0.5, alpha=0.6, zorder=2,
            ))
        if zone_type not in seen_zone_types:
            seen_zone_types.append(zone_type)

    node_coords = {node_id: (x, y) for node_id, x, y in road_nodes}
    for from_id, to_id, road_type in road_edges:
        from_xy = node_coords.get(from_id)
        to_xy = node_coords.get(to_id)
        if from_xy is None or to_xy is None:
            continue
        style = ROAD_STYLE.get(road_type, ROAD_STYLE["spur"])
        x1, y1 = from_xy
        x2, y2 = to_xy
        ax.plot([x1, x2], [y1, y2], color=style["color"], linewidth=style["width"], zorder=2.5)

    landmark_points: Dict[str, List[Tuple[float, float]]] = {}
    for x, y, building_type, width, height, rotation in buildings:
        if building_type in LANDMARK_BUILDING_TYPES:
            landmark_points.setdefault(building_type, []).append((x, y))
        else:
            corners = _rotated_rect_corners(x, y, width, height, rotation)
            ax.add_patch(MplPolygon(
                corners, closed=True, facecolor=GENERIC_BUILDING_COLOR, edgecolor="none", zorder=3,
            ))

    for building_type, points in landmark_points.items():
        marker, color, size = LANDMARK_BUILDING_TYPES[building_type]
        ax.scatter(
            [p[0] for p in points], [p[1] for p in points],
            s=size, c=color, marker=marker, zorder=4, label=building_type,
            edgecolors="black", linewidths=0.5,
        )

    if seen_zone_types:
        zone_handles = [
            plt.Rectangle((0, 0), 1, 1, facecolor=ZONE_COLORS.get(zt, DEFAULT_ZONE_COLOR), alpha=0.6, edgecolor="black")
            for zt in sorted(seen_zone_types)
        ]
        zone_legend = ax.legend(zone_handles, sorted(seen_zone_types), loc="upper left", title="Districts", fontsize=8)
        ax.add_artist(zone_legend)

    if landmark_points:
        ax.legend(loc="upper right", title="Landmarks", fontsize=8)

    ax.set_aspect("equal")
    ax.autoscale()
    ax.set_xticks([])
    ax.set_yticks([])
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
