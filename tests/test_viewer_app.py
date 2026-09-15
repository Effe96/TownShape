from tests.town_viewer_fixtures import build_full_town
from town_viewer.app import create_app


def _client(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)
    app = create_app(db_path)
    app.testing = True
    return app.test_client()


def test_index_serves_the_frontend_page(tmp_path):
    client = _client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert b"Town Viewer" in response.data


def test_map_endpoint_returns_districts_and_buildings(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/map")
    assert response.status_code == 200
    body = response.get_json()
    assert len(body["districts"]) == 2
    assert len(body["buildings"]) == 4


def test_building_endpoint_returns_detail(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/buildings/4")
    assert response.status_code == 200
    body = response.get_json()
    assert body["building_type"] == "residence"
    assert len(body["residents"]) == 4


def test_building_endpoint_404s_for_missing_building(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/buildings/999")
    assert response.status_code == 404


def test_residents_endpoint_searches_and_paginates(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/residents?q=stonebrook&page=1")
    assert response.status_code == 200
    body = response.get_json()
    assert body["total"] == 4
    assert len(body["residents"]) == 4


def test_resident_detail_endpoint_returns_full_profile(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/residents/1")
    assert response.status_code == 200
    body = response.get_json()
    assert body["first_name"] == "Mira"
    assert len(body["relationships"]) == 3
    assert len(body["shopping"]) == 1


def test_resident_detail_endpoint_404s_for_missing_resident(tmp_path):
    client = _client(tmp_path)
    response = client.get("/api/residents/999")
    assert response.status_code == 404


def test_town_svg_endpoint_serves_the_persisted_svg(tmp_path):
    db_path = str(tmp_path / "town.db")
    build_full_town(db_path)
    svg_path = str(tmp_path / "town.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write("<svg xmlns=\"http://www.w3.org/2000/svg\"><rect/></svg>")

    app = create_app(db_path)
    app.testing = True
    client = app.test_client()
    response = client.get("/api/town.svg")

    assert response.status_code == 200
    assert b"<svg" in response.data
    assert "svg" in response.content_type


def test_town_svg_endpoint_serves_the_persisted_svg_with_relative_db_path(tmp_path, monkeypatch):
    db_path = tmp_path / "town.db"
    build_full_town(str(db_path))
    svg_path = tmp_path / "town.svg"
    svg_path.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\"><rect/></svg>", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    app = create_app("town.db")
    app.testing = True
    client = app.test_client()
    response = client.get("/api/town.svg")

    assert response.status_code == 200
    assert b"<svg" in response.data
    assert "svg" in response.content_type
