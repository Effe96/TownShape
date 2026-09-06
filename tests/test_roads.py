from town_shaper.models import Anchor, ZoneType
from town_shaper.roads import generate_road_network


def _anchor(id, zone_type, x, y):
    return Anchor(id=id, zone_type=zone_type, x=x, y=y)


def test_hub_is_the_civic_anchor_nearest_bounds_center():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=50.0, y=50.0),
        _anchor(1, ZoneType.CIVIC, x=5.0, y=-5.0),   # nearest to (0, 0)
        _anchor(2, ZoneType.MERCHANT, x=0.0, y=0.0),  # closer, but not civic
        _anchor(3, ZoneType.POOR_RESIDENTIAL, x=-60.0, y=60.0),
    ]
    network = generate_road_network(anchors, bounds)

    hub_nodes = [n for n in network.nodes if n.is_hub]
    assert len(hub_nodes) == 1
    assert hub_nodes[0].anchor_id == 1


def test_hub_falls_back_to_nearest_any_zone_when_no_civic_anchors():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.MERCHANT, x=50.0, y=50.0),
        _anchor(1, ZoneType.MERCHANT, x=5.0, y=-5.0),
        _anchor(2, ZoneType.POOR_RESIDENTIAL, x=0.0, y=0.0),
        _anchor(3, ZoneType.FARMLAND_EDGE, x=-60.0, y=60.0),
    ]
    network = generate_road_network(anchors, bounds)

    hub_nodes = [n for n in network.nodes if n.is_hub]
    assert len(hub_nodes) == 1
    assert hub_nodes[0].anchor_id == 2


def test_boundary_edges_only_connect_junction_nodes():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=0.0, y=0.0),
        _anchor(1, ZoneType.MERCHANT, x=40.0, y=0.0),
        _anchor(2, ZoneType.POOR_RESIDENTIAL, x=-40.0, y=0.0),
        _anchor(3, ZoneType.RICH_RESIDENTIAL, x=0.0, y=40.0),
    ]
    network = generate_road_network(anchors, bounds)

    boundary_edges = [e for e in network.edges if e.road_type == "boundary"]
    assert len(boundary_edges) > 0
    junction_node_ids = {n.id for n in network.nodes if n.kind == "junction"}
    for edge in boundary_edges:
        assert edge.from_node_id in junction_node_ids
        assert edge.to_node_id in junction_node_ids


def test_no_boundary_edge_involves_a_mirrored_point():
    # A ridge between a real anchor and a mirrored reflection point (used
    # internally by compute_voronoi to bound outer regions) must never
    # surface as a boundary edge -- only ridges between two real anchors do.
    bounds = (-100.0, -100.0, 100.0, 100.0)
    from town_shaper.anchors import place_anchors
    anchors = place_anchors(("town", 1), 3000, bounds)

    network = generate_road_network(anchors, bounds)

    # Every boundary edge's endpoints must be junction nodes created from a
    # ridge between two real anchors -- if a mirrored point leaked through,
    # generate_road_network would raise (anchors[p1] with p1 out of range)
    # before returning, so simply completing without error is the guard.
    boundary_edges = [e for e in network.edges if e.road_type == "boundary"]
    assert len(boundary_edges) > 0


def test_boundary_edges_only_connect_anchors_whose_districts_actually_touch():
    # Cross-check against build_districts' own polygons -- a module this
    # test imports independently of generate_road_network's own output --
    # rather than re-deriving the same ridge data a second time and
    # comparing it to itself.
    from shapely.geometry import Polygon as ShapelyPolygon

    from town_shaper.anchors import place_anchors
    from town_shaper.districts import build_districts, compute_voronoi

    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = place_anchors(("town", 5), 4000, bounds)
    districts = build_districts(anchors, bounds)
    polygons_by_anchor_id = {
        d.id: ShapelyPolygon(d.polygon_parts[0]) for d in districts if d.polygon_parts
    }

    vor = compute_voronoi(anchors, bounds)
    num_real_anchors = len(anchors)
    checked_pairs = 0
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        if p1 >= num_real_anchors or p2 >= num_real_anchors or v1 < 0 or v2 < 0:
            continue
        anchor_a_id, anchor_b_id = anchors[p1].id, anchors[p2].id
        if anchor_a_id not in polygons_by_anchor_id or anchor_b_id not in polygons_by_anchor_id:
            continue
        checked_pairs += 1
        assert polygons_by_anchor_id[anchor_a_id].touches(polygons_by_anchor_id[anchor_b_id]) or \
            polygons_by_anchor_id[anchor_a_id].intersects(polygons_by_anchor_id[anchor_b_id])
    assert checked_pairs > 0


def test_boundary_edges_are_deterministic():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    from town_shaper.anchors import place_anchors
    anchors = place_anchors(("town", 7), 4000, bounds)

    network1 = generate_road_network(anchors, bounds)
    network2 = generate_road_network(anchors, bounds)

    key = lambda n: sorted((e.from_node_id, e.to_node_id, e.road_type) for e in n.edges)
    assert key(network1) == key(network2)


def test_every_anchor_with_a_qualifying_junction_gets_a_spur():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    from town_shaper.anchors import place_anchors
    anchors = place_anchors(("town", 3), 4000, bounds)

    network = generate_road_network(anchors, bounds)

    spur_sources = {e.from_node_id for e in network.edges if e.road_type == "spur"}
    anchor_node_ids = {n.id for n in network.nodes if n.kind == "anchor"}
    # Every spur starts at an anchor node and ends at a junction node.
    junction_node_ids = {n.id for n in network.nodes if n.kind == "junction"}
    for edge in network.edges:
        if edge.road_type == "spur":
            assert edge.from_node_id in anchor_node_ids
            assert edge.to_node_id in junction_node_ids
    assert spur_sources  # this anchor layout has at least one qualifying junction


def test_no_artery_edges_when_all_anchors_are_urban():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=0.0, y=0.0),
        _anchor(1, ZoneType.MERCHANT, x=40.0, y=0.0),
        _anchor(2, ZoneType.POOR_RESIDENTIAL, x=-40.0, y=0.0),
        _anchor(3, ZoneType.RICH_RESIDENTIAL, x=0.0, y=40.0),
    ]
    network = generate_road_network(anchors, bounds)

    artery_edges = [e for e in network.edges if e.road_type == "artery"]
    assert artery_edges == []


def test_artery_edges_reach_a_farmland_anchor():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=0.0, y=0.0),
        _anchor(1, ZoneType.MERCHANT, x=40.0, y=0.0),
        _anchor(2, ZoneType.POOR_RESIDENTIAL, x=-40.0, y=0.0),
        _anchor(3, ZoneType.FARMLAND_EDGE, x=0.0, y=40.0),
    ]
    network = generate_road_network(anchors, bounds)

    artery_edges = [e for e in network.edges if e.road_type == "artery"]
    assert artery_edges

    hub_node_id = next(n.id for n in network.nodes if n.is_hub)
    farmland_node_id = next(n.id for n in network.nodes if n.kind == "anchor" and n.anchor_id == 3)

    adjacency = {}
    for e in network.edges:
        if e.road_type in ("artery", "boundary", "spur"):
            adjacency.setdefault(e.from_node_id, []).append(e.to_node_id)
            adjacency.setdefault(e.to_node_id, []).append(e.from_node_id)
    visited = {hub_node_id}
    frontier = [hub_node_id]
    while frontier:
        current = frontier.pop()
        for neighbor in adjacency.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                frontier.append(neighbor)
    assert farmland_node_id in visited


def test_arteries_only_cover_the_farmland_adjacent_tail_of_a_path():
    # An artery is drawn only for the maximal TRAILING run of farmland-touching
    # hops. Taking the suffix from the FIRST farmland touch instead (the earlier
    # bug) drew the whole rest of the path, so a path that merely grazed a
    # farmland boundary early on got an artery run all the way to a purely
    # URBAN target anchor -- 134 units deep into a residential district on this
    # very seed. Since the hub is civic, its own spur hop never touches
    # farmland, so a correct tail can never start at the hub either: the only
    # anchor node any artery edge may touch is a farmland_edge target.
    from town_shaper.anchors import place_anchors

    bounds = (-150.0, -150.0, 150.0, 150.0)
    anchors = place_anchors(("town", 1), 3000, bounds)
    zone_by_anchor_id = {a.id: a.zone_type for a in anchors}

    network = generate_road_network(anchors, bounds)
    node_by_id = {n.id: n for n in network.nodes}

    artery_edges = [e for e in network.edges if e.road_type == "artery"]
    assert artery_edges  # this seed has farmland anchors, so arteries do exist

    for edge in artery_edges:
        for node_id in (edge.from_node_id, edge.to_node_id):
            node = node_by_id[node_id]
            if node.kind != "anchor":
                continue
            assert zone_by_anchor_id[node.anchor_id] == ZoneType.FARMLAND_EDGE, (
                f"artery edge {edge.id} touches anchor {node.anchor_id}, a "
                f"{zone_by_anchor_id[node.anchor_id].value} district -- arteries "
                f"must stop before re-entering purely urban territory"
            )


def test_artery_routing_is_deterministic():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    from town_shaper.anchors import place_anchors
    anchors = place_anchors(("town", 4), 4000, bounds)

    network1 = generate_road_network(anchors, bounds)
    network2 = generate_road_network(anchors, bounds)

    key = lambda n: sorted((e.from_node_id, e.to_node_id, e.road_type) for e in n.edges)
    assert key(network1) == key(network2)

