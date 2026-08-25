from typing import List, Tuple

import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import Polygon as ShapelyPolygon

from town_shaper.geometry import clip_polygon_to_bounds
from town_shaper.models import Anchor, District


def _mirrored_points(points: np.ndarray, bounds: Tuple[float, float, float, float]) -> np.ndarray:
    min_x, min_y, max_x, max_y = bounds
    reflections = []
    for x, y in points:
        reflections.append((2 * min_x - x, y))
        reflections.append((2 * max_x - x, y))
        reflections.append((x, 2 * min_y - y))
        reflections.append((x, 2 * max_y - y))
    return np.vstack([points, np.array(reflections)])


def _polygon_to_parts(shapely_geom) -> List[List[Tuple[float, float]]]:
    if shapely_geom.is_empty:
        return []
    if shapely_geom.geom_type == "Polygon":
        return [list(shapely_geom.exterior.coords)[:-1]]
    if shapely_geom.geom_type == "MultiPolygon":
        return [list(part.exterior.coords)[:-1] for part in shapely_geom.geoms]
    return []  # a degenerate difference (e.g. a LineString sliver) contributes no land


def build_districts(
    anchors: List[Anchor], bounds: Tuple[float, float, float, float], water_polygon=None
) -> List[District]:
    if len(anchors) < 4:
        raise ValueError("At least 4 anchors are required to compute a stable Voronoi diagram")

    anchor_points = np.array([(a.x, a.y) for a in anchors])
    all_points = _mirrored_points(anchor_points, bounds)
    vor = Voronoi(all_points)

    districts: List[District] = []
    for i, anchor in enumerate(anchors):
        region_index = vor.point_region[i]
        region = vor.regions[region_index]
        if -1 in region or len(region) == 0:
            raise ValueError(f"Anchor {anchor.id} produced an unbounded Voronoi region")
        raw_polygon = [tuple(vor.vertices[v]) for v in region]
        polygon = clip_polygon_to_bounds(raw_polygon, bounds)

        if water_polygon is not None:
            shapely_polygon = ShapelyPolygon(polygon).buffer(0)
            land = shapely_polygon.difference(water_polygon)
            polygon_parts = _polygon_to_parts(land)
        else:
            polygon_parts = [polygon]

        districts.append(District(id=anchor.id, zone_type=anchor.zone_type, anchor=anchor, polygon_parts=polygon_parts))

    return districts
