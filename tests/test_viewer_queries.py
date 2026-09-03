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
        {
            "id": 1, "district_id": 1, "zone_type": "civic", "building_type": "temple",
            "x": 10.0, "y": 10.0, "name": None,
            "width": 0.0, "height": 0.0, "rotation": 0.0,
        }
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


def test_get_map_data_returns_roads(tmp_path):
    db_path = str(tmp_path / "town.db")
    _build_minimal_map(db_path)

    conn = connect(db_path)
    conn.execute("INSERT INTO road_nodes (id, kind, anchor_id, is_hub, x, y) VALUES (1, 'anchor', 1, 1, 10.0, 10.0)")
    conn.execute("INSERT INTO road_nodes (id, kind, anchor_id, is_hub, x, y) VALUES (2, 'junction', NULL, 0, 12.0, 8.0)")
    conn.execute("INSERT INTO road_edges (id, from_node_id, to_node_id, road_type) VALUES (1, 1, 2, 'spur')")
    conn.commit()

    data = get_map_data(conn)
    conn.close()

    assert data["roads"] == {
        "nodes": [
            {"id": 1, "x": 10.0, "y": 10.0},
            {"id": 2, "x": 12.0, "y": 8.0},
        ],
        "edges": [
            {"from_node_id": 1, "to_node_id": 2, "road_type": "spur"},
        ],
    }


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


def test_get_building_detail_returns_empty_residents_list_for_an_empty_building(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    temple = get_building_detail(conn, 1)  # the temple, nobody lives or works here in the fixture
    conn.close()

    assert temple["residents"] == []


from town_viewer.queries import search_residents


def test_search_residents_with_no_query_returns_all_paginated(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = search_residents(conn, page=1, page_size=2)
    conn.close()

    assert result["total"] == 4
    assert result["page"] == 1
    assert result["page_size"] == 2
    assert len(result["residents"]) == 2


def test_search_residents_filters_by_name_case_insensitively(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = search_residents(conn, query="mira")
    conn.close()

    assert result["total"] == 1
    assert result["residents"][0]["first_name"] == "Mira"


def test_search_residents_second_page_is_the_remainder(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = search_residents(conn, page=2, page_size=3)
    conn.close()

    assert result["total"] == 4
    assert len(result["residents"]) == 1


def test_search_residents_with_no_matches_returns_empty_with_zero_total(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = search_residents(conn, query="nonexistentname")
    conn.close()

    assert result["total"] == 0
    assert result["residents"] == []


from town_viewer.queries import get_resident_detail


def test_get_resident_detail_includes_household_and_core_fields(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    mira = get_resident_detail(conn, 1)
    conn.close()

    assert mira["first_name"] == "Mira"
    assert mira["occupation"] == "merchant"
    assert mira["home_building_id"] == 4
    assert mira["workplace_building_id"] == 3
    assert mira["household"] == {"id": 1, "family_name": "Stonebrook", "race": "human", "wealth": 120.0}


def test_get_resident_detail_includes_relationships_both_directions(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    mira = get_resident_detail(conn, 1)  # stored as resident_a in all her relationship rows
    elin = get_resident_detail(conn, 3)  # stored as resident_b in her parent relationships
    conn.close()

    mira_types = {(r["resident_id"], r["relationship_type"], r["role"]) for r in mira["relationships"]}
    assert (2, "spouse", "a") in mira_types
    assert (3, "parent", "a") in mira_types
    assert (4, "parent", "a") in mira_types

    elin_types = {(r["resident_id"], r["relationship_type"], r["role"]) for r in elin["relationships"]}
    assert (1, "parent", "b") in elin_types
    assert (2, "parent", "b") in elin_types
    assert (4, "sibling", "a") in elin_types


def test_get_resident_detail_includes_shopping_history(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    mira = get_resident_detail(conn, 1)
    rian = get_resident_detail(conn, 4)
    conn.close()

    assert mira["shopping"] == [
        {"shop_building_id": 3, "purchase_count": 12, "total_spent": 340.5, "is_primary": True}
    ]
    assert rian["shopping"] == []


def test_get_resident_detail_returns_none_for_missing_resident(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    result = get_resident_detail(conn, 999)
    conn.close()

    assert result is None


def test_get_map_data_includes_building_footprints(tmp_path):
    db_path = str(tmp_path / "town.db")
    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', ?)",
        (json.dumps([[[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]]),),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, width, height, rotation) "
        "VALUES (1, 1, 'civic', 'temple', 10.0, 10.0, 0, 12.0, 14.4, 0.0)"
    )
    conn.commit()

    data = get_map_data(conn)
    conn.close()

    building = data["buildings"][0]
    assert building["width"] == 12.0
    assert building["height"] == 14.4
    assert building["rotation"] == 0.0


def test_get_building_detail_includes_footprint(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)

    conn = connect(db_path)
    conn.execute("UPDATE buildings SET width = 5.0, height = 6.0, rotation = 1.5 WHERE id = 4")
    conn.commit()
    building = get_building_detail(conn, 4)
    conn.close()

    assert building["width"] == 5.0
    assert building["height"] == 6.0
    assert building["rotation"] == 1.5
