import json
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


def render_town(db_path: str, output_path: str) -> None:
    conn = sqlite3.connect(db_path)
    districts = conn.execute("SELECT zone_type, polygon FROM districts").fetchall()
    buildings = conn.execute("SELECT x, y, building_type FROM buildings").fetchall()
    water_features = conn.execute("SELECT kind, polygon FROM water_features").fetchall()
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

    generic_x: List[float] = []
    generic_y: List[float] = []
    landmark_points: Dict[str, List[Tuple[float, float]]] = {}
    for x, y, building_type in buildings:
        if building_type in LANDMARK_BUILDING_TYPES:
            landmark_points.setdefault(building_type, []).append((x, y))
        else:
            generic_x.append(x)
            generic_y.append(y)

    if generic_x:
        ax.scatter(generic_x, generic_y, s=4, c=GENERIC_BUILDING_COLOR, zorder=3)

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
