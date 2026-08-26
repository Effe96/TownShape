import json

from town_db.render import render_town
from town_db.schema import connect, create_schema


def _build_minimal_town(db_path):
    conn = connect(db_path)
    create_schema(conn)

    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', ?)",
        (json.dumps([[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]]),),
    )
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (2, 'poor_residential', ?)",
        (json.dumps([[[10.0, 0.0], [20.0, 0.0], [20.0, 10.0], [10.0, 10.0]]]),),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'temple', 5.0, 5.0, 0)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (2, 2, 'poor_residential', 'residence', 15.0, 5.0, 6)"
    )
    conn.execute(
        "INSERT INTO water_features (id, kind, polygon) VALUES (1, 'river', ?)",
        (json.dumps([[[8.0, -2.0], [12.0, -2.0], [12.0, 12.0], [8.0, 12.0]]]),),
    )
    conn.commit()
    conn.close()


def test_render_town_produces_a_real_image_file(tmp_path):
    db_path = str(tmp_path / "town.db")
    output_path = str(tmp_path / "town.png")
    _build_minimal_town(db_path)

    render_town(db_path, output_path)

    with open(output_path, "rb") as f:
        header = f.read(8)
    assert header == b"\x89PNG\r\n\x1a\n"

    import os
    assert os.path.getsize(output_path) > 1000


def test_render_town_handles_a_town_with_no_water_or_landmarks(tmp_path):
    db_path = str(tmp_path / "town.db")
    output_path = str(tmp_path / "town.png")

    conn = connect(db_path)
    create_schema(conn)
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'merchant', ?)",
        (json.dumps([[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0], [0.0, 5.0]]]),),
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'merchant', 'shop', 2.5, 2.5, 0)"
    )
    conn.commit()
    conn.close()

    render_town(db_path, output_path)

    with open(output_path, "rb") as f:
        header = f.read(8)
    assert header == b"\x89PNG\r\n\x1a\n"
