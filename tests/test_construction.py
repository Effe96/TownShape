import json
import re
import shutil

from shapely.geometry import Point, Polygon

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
