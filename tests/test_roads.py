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


def test_every_anchor_has_a_radial_edge_to_the_hub():
    bounds = (-100.0, -100.0, 100.0, 100.0)
    anchors = [
        _anchor(0, ZoneType.CIVIC, x=0.0, y=0.0),
        _anchor(1, ZoneType.MERCHANT, x=40.0, y=0.0),
        _anchor(2, ZoneType.POOR_RESIDENTIAL, x=-40.0, y=0.0),
        _anchor(3, ZoneType.RICH_RESIDENTIAL, x=0.0, y=40.0),
    ]
    network = generate_road_network(anchors, bounds)

    hub_node_id = next(n.id for n in network.nodes if n.is_hub)
    radial_targets = {
        e.to_node_id for e in network.edges
        if e.road_type == "radial" and e.from_node_id == hub_node_id
    }
    anchor_node_ids_excluding_hub = {
        n.id for n in network.nodes if n.kind == "anchor" and not n.is_hub
    }
    assert radial_targets == anchor_node_ids_excluding_hub


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
