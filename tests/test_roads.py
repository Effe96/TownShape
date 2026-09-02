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
