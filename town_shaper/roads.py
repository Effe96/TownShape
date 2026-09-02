from typing import Dict, List, Tuple

from town_shaper.districts import compute_voronoi
from town_shaper.geometry import distance
from town_shaper.models import Anchor, RoadEdge, RoadNetwork, RoadNode, ZoneType


def _choose_hub_anchor(anchors: List[Anchor], bounds: Tuple[float, float, float, float]) -> Anchor:
    min_x, min_y, max_x, max_y = bounds
    center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    civic_anchors = [a for a in anchors if a.zone_type == ZoneType.CIVIC]
    candidates = civic_anchors if civic_anchors else anchors
    return min(candidates, key=lambda a: distance(center, (a.x, a.y)))


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

    hub_node = anchor_node_by_id[hub.id]
    for anchor in anchors:
        if anchor.id == hub.id:
            continue
        edges.append(RoadEdge(
            id=next_edge_id, from_node_id=hub_node.id,
            to_node_id=anchor_node_by_id[anchor.id].id, road_type="radial",
        ))
        next_edge_id += 1

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

    return RoadNetwork(nodes=nodes, edges=edges)
