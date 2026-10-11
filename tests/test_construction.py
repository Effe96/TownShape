import pytest
import json
import re
import shutil

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from town_db.construction import add_buildings
from town_db.schema import connect, create_schema

# A 40x40 walled core around the origin, one road leaving east, and a ring of
# 18x18 field plots (each its own farmland_edge district, as settlemaker
# emits them) out to +-70. The frame is +-80, so re-sown fields must widen it.
CORE = [[-20, -20], [20, -20], [20, 20], [-20, 20]]
ROAD = Polygon([(0, -1.5), (150, -1.5), (150, 1.5), (0, 1.5)])
FIELDS = [
    [[x, y], [x + 18, y], [x + 18, y + 18], [x, y + 18]]
    for x in range(-70, 70, 20) for y in range(-70, 70, 20)
    if not (-30 < x + 9 < 30 and -30 < y + 9 < 30) and not (-10 < y + 9 < 10 and x > 0)
]


def _svg():
    plots = "\n".join(
        f'<path class="plot" d="M{"L".join(f"{x},{y}" for x, y in f)}Z"/>\n'
        f'<path class="hatch" d="M{"L".join(f"{x},{y}" for x, y in f)}Z" fill="url(#frame-clip-field-a0)"/>'
        for f in FIELDS
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-80.0 -80.0 160.0 160.0">
<defs><clipPath id="frame-clip"><rect x="-80.0" y="-80.0" width="160.0" height="160.0"/></clipPath>
<pattern id="frame-clip-field-a0"></pattern></defs>
<rect data-bg="paper" x="-80.0" y="-80.0" width="160.0" height="160.0" fill="#fff2c8"/>
<g id="fields">
{plots}
</g>
<g id="roads" clip-path="url(#frame-clip)"><path class="casing" d="M0,0L150,0" stroke-width="3.00"/><path class="core" d="M0,0L150,0" stroke-width="2.40"/></g>
<g id="shadows"><path d="M-2,-1L2,-1L2,1L-2,1Z"/></g>
<g id="buildings"><path class="slum" d="M-2,-1L2,-1L2,1L-2,1Z"/></g>
<g id="walls"><path d="M-20,-20L20,-20L20,20L-20,20L-20,-20"/></g>
<g id="symbols"><use href="#glyph-sm-mill-wind" transform="translate(30.00,5.00) scale(0.1000) rotate(0) translate(-32,-32)"/></g>
</svg>"""


def _make_town(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.execute("INSERT INTO districts VALUES (1, 'poor_residential', ?)", (json.dumps([CORE]),))
    for i, field in enumerate(FIELDS, start=2):
        conn.execute("INSERT INTO districts VALUES (?, 'farmland_edge', ?)", (i, json.dumps([field])))
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, footprint) "
        "VALUES (1, 1, 'poor_residential', 'residence', 0, 0, 6, ?)",
        (json.dumps([[-2, -1], [2, -1], [2, 1], [-2, 1]]),),
    )
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence, "
        "svg_min_x, svg_min_y, svg_max_x, svg_max_y) VALUES (1, '1000-01-01', '1000-01-01', 0, 0, -80, -80, 80, 80)"
    )
    conn.commit()
    conn.close()
    (tmp_path / "town.svg").write_text(_svg(), encoding="utf-8")
    return db_path


def _footprints(db_path, ids):
    conn = connect(db_path)
    rows = conn.execute(
        f"SELECT footprint FROM buildings WHERE id IN ({','.join('?' * len(ids))}) ORDER BY id", ids
    ).fetchall()
    conn.close()
    return [Polygon(json.loads(f)) for (f,) in rows]


def _edit(db_path, edit_id):
    conn = connect(db_path)
    params = conn.execute("SELECT params FROM construction_edits WHERE id = ?", (edit_id,)).fetchone()[0]
    conn.close()
    return json.loads(params)


def _assert_no_overlaps(shapes):
    for i, shape in enumerate(shapes):
        assert all(not shape.intersects(other) for other in shapes[i + 1:])


def test_ribbon_houses_front_the_road_outside_the_core(tmp_path):
    db_path = _make_town(tmp_path)
    ids = add_buildings(db_path, 4, where="roads")
    assert len(ids) == 4

    shapes = _footprints(db_path, ids)
    for shape in shapes:
        assert not shape.intersects(Polygon(CORE))
        assert not shape.intersects(ROAD)
        assert shape.distance(ROAD) < 2
    _assert_no_overlaps(shapes)

    svg = (tmp_path / "town.svg").read_text(encoding="utf-8")
    assert all(f'data-building-id="{i}"' in svg for i in ids)
    conn = connect(db_path)
    assert conn.execute("SELECT building_ids FROM construction_edits").fetchone() == (json.dumps(ids),)
    conn.close()


def test_ribbons_stop_at_reach_and_overflow_onto_side_streets(tmp_path):
    db_path = _make_town(tmp_path)
    ids = add_buildings(db_path, 30, where="roads")
    assert len(ids) == 30
    shapes = _footprints(db_path, ids)
    _assert_no_overlaps(shapes)
    # Growth stays near town instead of running down the 150-unit road...
    assert max(s.bounds[2] for s in shapes) < 75
    # ...and the overflow lines new side streets, drawn into the SVG.
    assert any(s.distance(ROAD) > 4 for s in shapes)
    assert _edit(db_path, 1)["streets"] >= 1
    svg = (tmp_path / "town.svg").read_text(encoding="utf-8")
    assert len(re.findall(r'class="casing"', svg)) == 1 + _edit(db_path, 1)["streets"]


def test_side_streets_grow_on_later_calls(tmp_path):
    db_path = _make_town(tmp_path)
    first = add_buildings(db_path, 8, where="perimeter")
    second = add_buildings(db_path, 8, where="perimeter")
    assert len(first) == len(second) == 8
    assert set(first).isdisjoint(second)
    _assert_no_overlaps(_footprints(db_path, first + second))


def _farmland(db_path, exclude=()):
    conn = connect(db_path)
    rows = conn.execute("SELECT id, polygon FROM districts WHERE zone_type = 'farmland_edge'").fetchall()
    conn.close()
    return {d_id: Polygon(json.loads(p)[0]) for d_id, p in rows if d_id not in exclude}


def test_built_over_fields_become_living_areas_and_are_resown_outside(tmp_path):
    db_path = _make_town(tmp_path)
    farmland_before = sum(p.area for p in _farmland(db_path).values())
    add_buildings(db_path, 30, where="roads")
    edit = _edit(db_path, 1)
    assert edit["converted_district_ids"] or edit["trimmed_district_ids"]
    assert edit["new_field_district_ids"]

    conn = connect(db_path)
    zones = dict(conn.execute("SELECT id, zone_type FROM districts").fetchall())
    frame = conn.execute("SELECT svg_min_x, svg_min_y, svg_max_x, svg_max_y FROM town_state").fetchone()
    conn.close()
    assert all(zones[d] == "poor_residential" for d in edit["converted_district_ids"] + edit["living_district_ids"])

    # Field area lost to building is re-sown (roughly), outside the old ring.
    new_fields = [p for d_id, p in _farmland(db_path).items() if d_id in edit["new_field_district_ids"]]
    lost = farmland_before - sum(p.area for p in _farmland(db_path, exclude=edit["new_field_district_ids"]).values())
    assert lost > 0
    assert sum(f.area for f in new_fields) >= 0.6 * lost
    assert all(max(abs(c) for c in f.centroid.coords[0]) > 50 for f in new_fields)
    # No remaining field overlaps a new house.
    houses = _footprints(db_path, json.loads(connect(db_path).execute(
        "SELECT building_ids FROM construction_edits").fetchone()[0]))
    assert not any(f.intersects(h) for f in _farmland(db_path).values() for h in houses)
    # The re-sown fields needed a wider frame, written to the DB and the SVG alike.
    assert frame[0] < -80 or frame[1] < -80 or frame[2] > 80 or frame[3] > 80
    svg = (tmp_path / "town.svg").read_text(encoding="utf-8")
    view_box = tuple(map(float, re.search(r'viewBox="([^"]+)"', svg).group(1).split()))
    assert view_box == (frame[0], frame[1], round(frame[2] - frame[0], 1), round(frame[3] - frame[1], 1))
    assert svg.count('class="plot"') == len(_farmland(db_path))


def test_streets_are_persisted_to_the_road_graph(tmp_path):
    db_path = _make_town(tmp_path)
    add_buildings(db_path, 30, where="roads")
    conn = connect(db_path)
    edges = conn.execute("SELECT COUNT(*) FROM road_edges WHERE road_type = 'street'").fetchone()[0]
    conn.close()
    assert edges >= _edit(db_path, 1)["streets"] >= 1


def test_tavern_takes_the_most_central_road_lot(tmp_path):
    db_path = _make_town(tmp_path)
    (tavern,) = add_buildings(db_path, 1, building_type="tavern")
    tavern_shape = _footprints(db_path, [tavern])[0]
    # Right outside the gate (core edge is x=20, wall clearance 2), on the road.
    assert tavern_shape.bounds[0] < 30
    assert tavern_shape.distance(ROAD) < 1


def test_new_buildings_avoid_settlemaker_landscape_symbols(tmp_path):
    db_path = _make_town(tmp_path)
    ids = add_buildings(db_path, 30, where="roads")
    mill = Point(30, 5).buffer(3.2)  # 64-unit glyph at scale 0.1, centred
    assert not any(s.intersects(mill) for s in _footprints(db_path, ids))


def test_new_tavern_is_house_sized_not_a_whole_lot(tmp_path):
    db_path = _make_town(tmp_path)
    (tavern,) = add_buildings(db_path, 1, building_type="tavern")
    # The town's only house is 4x2; a new tavern is 1.4x that per side.
    assert abs(_footprints(db_path, [tavern])[0].area - 4 * 2 * 1.4 ** 2) < 0.1


def test_add_buildings_is_deterministic(tmp_path):
    db_path = _make_town(tmp_path)
    other = tmp_path / "copy"
    other.mkdir()
    shutil.copy(db_path, other / "town.db")
    shutil.copy(tmp_path / "town.svg", other / "town.svg")

    a = add_buildings(db_path, 20, where="roads")
    b = add_buildings(str(other / "town.db"), 20, where="roads")
    assert [s.wkt for s in _footprints(db_path, a)] == [s.wkt for s in _footprints(str(other / "town.db"), b)]
    assert (tmp_path / "town.svg").read_text(encoding="utf-8") == (other / "town.svg").read_text(encoding="utf-8")


# --- editing existing buildings ---------------------------------------------

from town_db.construction import demolish_building, reshape_building, resize_building

HOUSE_A = [[-12, -8], [-8, -8], [-8, -6], [-12, -6]]   # shares its x=-8 wall with B
HOUSE_B = [[-8, -8], [-4, -8], [-4, -6], [-8, -6]]


def _town_with_pair(tmp_path):
    db_path = _make_town(tmp_path)
    conn = connect(db_path)
    for b_id, ring in ((2, HOUSE_A), (3, HOUSE_B)):
        conn.execute(
            "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, name, footprint) "
            "VALUES (?, 1, 'poor_residential', 'residence', ?, ?, 6, ?, ?)",
            (b_id, Polygon(ring).centroid.x, Polygon(ring).centroid.y, f"House {b_id}", json.dumps(ring)))
    conn.commit()
    conn.close()
    svg_file = tmp_path / "town.svg"
    svg = svg_file.read_text(encoding="utf-8")
    for ring in (HOUSE_A, HOUSE_B):
        d = "M" + "L".join(f"{x:.2f},{y:.2f}" for x, y in ring) + "Z"
        svg = svg.replace('<g id="buildings">', f'<g id="buildings"><path class="slum" d="{d}"/>', 1)
        svg = svg.replace('<g id="shadows">', f'<g id="shadows"><path d="{d}"/>', 1)
    svg_file.write_text(svg, encoding="utf-8")
    return db_path


def _row(db_path, b_id):
    conn = connect(db_path)
    row = conn.execute("SELECT building_type, capacity, name, footprint FROM buildings WHERE id = ?", (b_id,)).fetchone()
    conn.close()
    return row


def test_demolish_clears_the_building_off_the_map_but_keeps_its_row(tmp_path):
    db_path = _town_with_pair(tmp_path)
    demolish_building(db_path, 2)
    assert _row(db_path, 2)[:2] == ("demolished", 0)
    svg = (tmp_path / "town.svg").read_text(encoding="utf-8")
    assert "M-12.00,-8.00" not in svg  # building and its shadow both gone
    assert "M-8.00,-8.00" in svg       # the neighbour untouched
    # Its land is free again: new construction ignores demolished rows.
    conn = connect(db_path)
    assert conn.execute("SELECT operation FROM construction_edits").fetchone() == ("demolish_building",)
    conn.close()


def test_ruin_stays_on_the_map_restyled(tmp_path):
    db_path = _town_with_pair(tmp_path)
    demolish_building(db_path, 2, ruin=True)
    b_type, capacity, name, _ = _row(db_path, 2)
    assert (b_type, capacity, name) == ("ruin", 0, "Ruins of House 2")
    svg = (tmp_path / "town.svg").read_text(encoding="utf-8")
    assert '<path class="ruin" d="M-12.00,-8.00' in svg
    assert svg.count('<path d="M-12.00,-8.00') == 0  # no shadow under a ruin


def test_enlarging_stops_at_a_neighbour_unless_it_absorbs_it(tmp_path):
    db_path = _town_with_pair(tmp_path)
    outcome = resize_building(db_path, 2, 2.0)
    grown = Polygon(json.loads(_row(db_path, 2)[3]))
    assert outcome["absorbed"] == []
    assert grown.area > Polygon(HOUSE_A).area
    assert grown.intersection(Polygon(HOUSE_B)).area < 1e-6
    assert outcome["area_factor_achieved"] < 2.0

    (tmp_path / "again").mkdir()
    db_path2 = _town_with_pair(tmp_path / "again")
    outcome = resize_building(db_path2, 2, 2.0, absorb_neighbors=True)
    assert outcome["absorbed"] == [3]
    assert _row(db_path2, 3)[0] == "demolished"
    # It builds across B's whole lot, so it can exceed the request.
    assert outcome["area_factor_achieved"] >= 2.0
    assert Polygon(json.loads(_row(db_path2, 2)[3])).buffer(1e-6).contains(Polygon(HOUSE_B))


def test_shrinking_keeps_the_shape_about_its_centre(tmp_path):
    db_path = _town_with_pair(tmp_path)
    outcome = resize_building(db_path, 2, 0.5)
    shrunk = Polygon(json.loads(_row(db_path, 2)[3]))
    assert abs(shrunk.area - 4.0) < 0.05
    assert shrunk.centroid.distance(Polygon(HOUSE_A).centroid) < 1e-6
    assert outcome["area_factor_achieved"] == 0.5
    svg = (tmp_path / "town.svg").read_text(encoding="utf-8")
    assert "M-12.00,-8.00" not in svg  # redrawn


def test_reshape_round_and_square(tmp_path):
    db_path = _town_with_pair(tmp_path)
    # Same area, round: narrower than the 4x2 house, so it never reaches B.
    outcome = reshape_building(db_path, 2, "round")
    tower = Polygon(json.loads(_row(db_path, 2)[3]))
    assert len(tower.exterior.coords) > 12  # actually round
    assert abs(tower.area - 8.0) < 0.5
    assert outcome["absorbed"] == []
    # Twice as big it overlaps B: clipped flat against it by default...
    flattened = reshape_building(db_path, 2, "round", area_factor=2.0)
    assert flattened["absorbed"] == [] and flattened["area_factor_achieved"] < 2.0
    assert Polygon(json.loads(_row(db_path, 2)[3])).intersection(Polygon(HOUSE_B)).area < 1e-6
    # ...or taking B's lot when allowed to.
    absorbed = reshape_building(db_path, 2, "round", area_factor=2.0, absorb_neighbors=True)
    assert absorbed["absorbed"] == [3]
    tower = Polygon(json.loads(_row(db_path, 2)[3]))
    reshape_building(db_path, 2, "square")
    square_shape = Polygon(json.loads(_row(db_path, 2)[3]))
    assert len(square_shape.exterior.coords) == 5
    assert abs(square_shape.area - tower.area) < 0.5


def _town_with_cloister(tmp_path):
    """One DB building (a merged cathedral) drawn as four #landmarks pieces
    around an open courtyard: outline -12..-4 x -18..-10, courtyard
    -10..-6 x -16..-12."""
    db_path = _make_town(tmp_path)
    pieces = [
        [[-12, -18], [-4, -18], [-4, -16], [-12, -16]],   # south range
        [[-12, -12], [-4, -12], [-4, -10], [-12, -10]],   # north range
        [[-12, -16], [-10, -16], [-10, -12], [-12, -12]],  # west range
        [[-6, -16], [-4, -16], [-4, -12], [-6, -12]],     # east range
    ]
    whole = [[-12, -18], [-4, -18], [-4, -10], [-12, -10]]
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, name, footprint) "
        "VALUES (5, 1, 'civic', 'temple', -8, -14, 0, 'Temple', ?)", (json.dumps(whole),))
    conn.commit()
    conn.close()
    svg_file = tmp_path / "town.svg"
    paths = "".join('<path class="cathedral" d="M' + "L".join(f"{x:.2f},{y:.2f}" for x, y in ring) + 'Z"/>'
                    for ring in pieces)
    svg_file.write_text(svg_file.read_text(encoding="utf-8").replace(
        "</svg>", f'<g id="landmarks">{paths}</g>\n</svg>'), encoding="utf-8")
    return db_path, svg_file


def _landmark_shapes(svg_file):
    svg = svg_file.read_text(encoding="utf-8")
    section = svg[svg.index('<g id="landmarks">'):]
    return [Polygon([tuple(map(float, xy.split(","))) for xy in re.findall(r"-?[\d.]+,-?[\d.]+", d)])
            for d in re.findall(r'<path[^>]*\sd="([^"]+)"', section)]


def test_resizing_a_multi_piece_building_keeps_its_courtyard(tmp_path):
    db_path, svg_file = _town_with_cloister(tmp_path)
    resize_building(db_path, 5, 1.5)
    shapes = _landmark_shapes(svg_file)
    assert len(shapes) == 4                                     # still four ranges...
    assert not any(s.contains(Point(-8, -14)) for s in shapes)  # ...around an open courtyard
    assert unary_union(shapes).area > 1.3 * (64 - 16)           # and bigger
    demolish_building(db_path, 5, ruin=True)
    assert svg_file.read_text(encoding="utf-8").count('class="ruin"') == 4


def test_reshaping_a_multi_piece_building_redraws_one_outline(tmp_path):
    db_path, svg_file = _town_with_cloister(tmp_path)
    reshape_building(db_path, 5, "round")
    assert len(_landmark_shapes(svg_file)) == 1


# --- building near a named place ---------------------------------------------

from town_db.construction import resolve_place


def _town_with_gates(tmp_path):
    """The test town plus a second road leaving north (SVG is Y-down: north
    is -y), gates where both roads cross the wall, and a named barn."""
    db_path = _make_town(tmp_path)
    svg_file = tmp_path / "town.svg"
    svg = svg_file.read_text(encoding="utf-8")
    svg = svg.replace('<path class="core" d="M0,0L150,0"',
                      '<path class="casing" d="M0,0L0,-150" stroke-width="3.00"/><path class="core" d="M0,0L150,0"')
    svg = svg.replace('<path d="M-20,-20L20,-20L20,20L-20,20L-20,-20"/>',
                      '<path d="M-20,-20L20,-20L20,20L-20,20L-20,-20"/>'
                      '<line class="gate" x1="20.00" y1="-2.00" x2="20.00" y2="2.00"/>'
                      '<line class="gate" x1="-2.00" y1="-20.00" x2="2.00" y2="-20.00"/>')
    svg_file.write_text(svg, encoding="utf-8")
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, name, footprint) "
        "VALUES (9, 2, 'farmland_edge', 'farmstead', 12, 40, 8, 'Old Barn', ?)",
        (json.dumps([[10, 39], [14, 39], [14, 41], [10, 41]]),))
    conn.commit()
    conn.close()
    return db_path


def test_resolve_place_understands_gates_names_types_and_glyphs(tmp_path):
    db_path = _town_with_gates(tmp_path)
    svg = (tmp_path / "town.svg").read_text(encoding="utf-8")
    conn = connect(db_path)
    try:
        assert resolve_place(conn, svg, "north gate", (0, 0)).distance(Point(0, -20)) < 1e-6
        assert resolve_place(conn, svg, "East Gate", (0, 0)).distance(Point(20, 0)) < 1e-6
        assert resolve_place(conn, svg, "old barn", (0, 0)).distance(Point(12, 40)) < 1e-6
        assert resolve_place(conn, svg, "farmstead", (0, 0)).distance(Point(12, 40)) < 1e-6
        assert resolve_place(conn, svg, 9, (0, 0)).distance(Point(12, 40)) < 1e-6
        assert resolve_place(conn, svg, "mill", (0, 0)).distance(Point(30, 5)) < 1e-6
        for bad in ("west gate", "the dragon's lair", "river"):
            with pytest.raises(ValueError):
                resolve_place(conn, svg, bad, (0, 0))
    finally:
        conn.close()


def test_tavern_by_the_north_gate_goes_to_the_north_gate(tmp_path):
    db_path = _town_with_gates(tmp_path)
    (tavern,) = add_buildings(db_path, 1, building_type="tavern", near="north gate")
    shape = _footprints(db_path, [tavern])[0]
    assert shape.distance(Point(0, -20)) < 8
    assert _edit(db_path, 1)["near"] == "north gate"


def test_houses_near_a_named_building_get_a_lane_out_to_it(tmp_path):
    def distances(near):
        sub = tmp_path / str(near)
        sub.mkdir()
        db_path = _town_with_gates(sub)
        ids = add_buildings(db_path, 12, where="perimeter", near=near)
        return sorted(s.distance(Point(12, 40)) for s in _footprints(db_path, ids))
    near, default = distances("Old Barn"), distances(None)
    assert near[0] < 4               # a lane reaches the barn, houses beside it
    assert near[0] < default[0] / 2  # which default growth doesn't do
    assert sum(near) < sum(default)
