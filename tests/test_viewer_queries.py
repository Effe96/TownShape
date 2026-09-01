import json

from town_db.schema import connect, create_schema
from town_viewer.queries import get_map_data


def _build_minimal_map(db_path):
    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', ?)",
        (json.dumps([[[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]]),),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'temple', 10.0, 10.0, 0)"
    )
    conn.execute(
        "INSERT INTO water_features (id, kind, polygon) VALUES (1, 'river', ?)",
        (json.dumps([[[8.0, -2.0], [12.0, -2.0], [12.0, 22.0], [8.0, 22.0]]]),),
    )
    conn.commit()
    conn.close()


def test_get_map_data_returns_districts_buildings_and_water(tmp_path):
    db_path = str(tmp_path / "town.db")
    _build_minimal_map(db_path)

    conn = connect(db_path)
    data = get_map_data(conn)
    conn.close()

    assert data["districts"] == [
        {"id": 1, "zone_type": "civic", "polygon": [[[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]]}
    ]
    assert data["buildings"] == [
        {"id": 1, "district_id": 1, "zone_type": "civic", "building_type": "temple", "x": 10.0, "y": 10.0}
    ]
    assert data["water_features"] == [
        {"id": 1, "kind": "river", "polygon": [[[8.0, -2.0], [12.0, -2.0], [12.0, 22.0], [8.0, 22.0]]]}
    ]


def test_get_map_data_handles_a_town_with_no_water(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'merchant', ?)",
        (json.dumps([[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]]),),
    )
    conn.commit()
    conn.close()

    conn = connect(db_path)
    data = get_map_data(conn)
    conn.close()

    assert data["buildings"] == []
    assert data["water_features"] == []


from tests.town_viewer_fixtures import build_full_town
from town_viewer.queries import get_building_detail


def test_get_building_detail_lists_residents_who_live_and_work_there(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    building = get_building_detail(conn, 4)  # the residence, all 4 residents live here
    conn.close()

    assert building["id"] == 4
    assert building["building_type"] == "residence"
    assert building["capacity"] == 6
    residents_by_id = {r["id"]: r for r in building["residents"]}
    assert set(residents_by_id) == {1, 2, 3, 4}
    assert all(r["lives_here"] for r in residents_by_id.values())
    assert all(not r["works_here"] for r in residents_by_id.values())


def test_get_building_detail_flags_workers_not_residents(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    shop = get_building_detail(conn, 3)  # the shop, only Mira (id 1) works here
    conn.close()

    assert [r["id"] for r in shop["residents"]] == [1]
    assert shop["residents"][0]["lives_here"] is False
    assert shop["residents"][0]["works_here"] is True


def test_get_building_detail_returns_none_for_missing_building(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = get_building_detail(conn, 999)
    conn.close()

    assert result is None
