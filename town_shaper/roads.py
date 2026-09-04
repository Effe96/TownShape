import math
from collections import deque
from typing import Dict, FrozenSet, List, Optional, Tuple

from town_shaper.districts import compute_voronoi
from town_shaper.geometry import distance
from town_shaper.models import Anchor, RoadEdge, RoadNetwork, RoadNode, ZoneType


def _choose_hub_anchor(anchors: List[Anchor], bounds: Tuple[float, float, float, float]) -> Anchor:
    min_x, min_y, max_x, max_y = bounds
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    civic_anchors = [a for a in anchors if a.zone_type == ZoneType.CIVIC]
    candidates = civic_anchors if civic_anchors else anchors
    return min(candidates, key=lambda a: distance(center, (a.x, a.y)))


def _bfs_path(adjacency: Dict[int, List[int]], start: int, goal: int) -> Optional[List[int]]:
    if start == goal:
        return [start]
    visited = {start}
    parent: Dict[int, int] = {}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            parent[neighbor] = current
            if neighbor == goal:
                path = [goal]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                path.reverse()
                return path
            queue.append(neighbor)
    return None


def _chaikin_smooth(points: List[Tuple[float, float]], iterations: int = 2) -> List[Tuple[float, float]]:
    """Corner-cutting smoothing that keeps the first and last point fixed
    (an anchor's own position shouldn't move), same spirit as the
    reference generator's post-routing street smoothing."""
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


def generate_road_network(
    anchors: List[Anchor], bounds: Tuple[float, float, float, float], water_polygon=None,
) -> RoadNetwork:
    vor = compute_voronoi(anchors, bounds)
    hub = _choose_hub_anchor(anchors, bounds)

    nodes: List[RoadNode] = []
    edges: List[RoadEdge] = []
    next_node_id = 0
    next_edge_id = 0

    anchor_node_by_id: Dict[int, RoadNode] = {}
    for anchor in anchors:
        node = RoadNode(
            id=next_node_id, kind="anchor", x=anchor.x, y=anchor.y,
            anchor_id=anchor.id, is_hub=(anchor.id == hub.id),
        )
        next_node_id += 1
        nodes.append(node)
        anchor_node_by_id[anchor.id] = node

    junction_node_by_vertex: Dict[int, RoadNode] = {}

    def _junction_node(vertex_index: int) -> RoadNode:
        nonlocal next_node_id
        node = junction_node_by_vertex.get(vertex_index)
        if node is None:
            x, y = vor.vertices[vertex_index]
            node = RoadNode(id=next_node_id, kind="junction", x=float(x), y=float(y))
            next_node_id += 1
            nodes.append(node)
            junction_node_by_vertex[vertex_index] = node
        return node

    # Adjacency graph of boundary+spur edges only -- what artery routing
    # (below) paths through -- plus, per hop, whether either side touches
    # a zone with no block-inset (farmland_edge), which decides whether
    # that hop needs an actual drawn line.
    adjacency: Dict[int, List[int]] = {}
    hop_touches_farmland: Dict[FrozenSet[int], bool] = {}

    def _add_adjacency(a: int, b: int, touches_farmland: bool) -> None:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
        hop_touches_farmland[frozenset((a, b))] = touches_farmland

    num_real_anchors = len(anchors)
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        if p1 >= num_real_anchors or p2 >= num_real_anchors:
            continue
        if v1 < 0 or v2 < 0:
            continue
        node1 = _junction_node(v1)
        node2 = _junction_node(v2)
        edges.append(RoadEdge(
            id=next_edge_id, from_node_id=node1.id, to_node_id=node2.id, road_type="boundary",
        ))
        next_edge_id += 1
        touches_farmland = (
            anchors[p1].zone_type == ZoneType.FARMLAND_EDGE or anchors[p2].zone_type == ZoneType.FARMLAND_EDGE
        )
        _add_adjacency(node1.id, node2.id, touches_farmland)

    qualifying_junction_vertices_by_anchor_id: Dict[int, List[int]] = {a.id: [] for a in anchors}
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        if p1 >= num_real_anchors or p2 >= num_real_anchors:
            continue
        if v1 < 0 or v2 < 0:
            continue
        qualifying_junction_vertices_by_anchor_id[anchors[p1].id].extend([v1, v2])
        qualifying_junction_vertices_by_anchor_id[anchors[p2].id].extend([v1, v2])

    for anchor in anchors:
        candidate_vertices = set(qualifying_junction_vertices_by_anchor_id[anchor.id])
        if not candidate_vertices:
            continue
        nearest_vertex = min(
            candidate_vertices,
            key=lambda v: distance((anchor.x, anchor.y), tuple(vor.vertices[v])),
        )
        anchor_node = anchor_node_by_id[anchor.id]
        junction_node = junction_node_by_vertex[nearest_vertex]
        edges.append(RoadEdge(
            id=next_edge_id, from_node_id=anchor_node.id,
            to_node_id=junction_node.id, road_type="spur",
        ))
        next_edge_id += 1
        _add_adjacency(anchor_node.id, junction_node.id, anchor.zone_type == ZoneType.FARMLAND_EDGE)

    # Artery routing -- replaces straight radial edges. Drawn only for the
    # tail of a path that actually touches farmland_edge; everywhere else
    # the gap between inset urban blocks already reads as a street.
    #
    # Known limitation: two nearby farmland anchors routed via a shared
    # urban gateway will each draw their own full tail from that gateway,
    # which can produce a short overlapping stretch rather than a single
    # shared one. Cosmetic (renders as a slightly thicker stretch, not a
    # wrong one), not fixed in this pass.
    hub_node = anchor_node_by_id[hub.id]
    node_by_id: Dict[int, RoadNode] = {n.id: n for n in nodes}

    for anchor in anchors:
        if anchor.id == hub.id:
            continue
        target_node = anchor_node_by_id[anchor.id]
        path = _bfs_path(adjacency, hub_node.id, target_node.id)
        if path is None or len(path) < 2:
            continue

        tail_start_index = None
        for i in range(len(path) - 1):
            if hop_touches_farmland.get(frozenset((path[i], path[i + 1]))):
                tail_start_index = i
                break
        if tail_start_index is None:
            continue

        tail_node_ids = path[tail_start_index:]
        tail_points = [(node_by_id[nid].x, node_by_id[nid].y) for nid in tail_node_ids]
        smoothed_points = _chaikin_smooth(tail_points, iterations=2)

        artery_node_ids = [tail_node_ids[0]]
        for point in smoothed_points[1:-1]:
            new_node = RoadNode(id=next_node_id, kind="junction", x=point[0], y=point[1])
            next_node_id += 1
            nodes.append(new_node)
            artery_node_ids.append(new_node.id)
        artery_node_ids.append(tail_node_ids[-1])

        for a, b in zip(artery_node_ids, artery_node_ids[1:]):
            edges.append(RoadEdge(id=next_edge_id, from_node_id=a, to_node_id=b, road_type="artery"))
            next_edge_id += 1

    return RoadNetwork(nodes=nodes, edges=edges)
