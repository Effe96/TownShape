import os

from flask import Flask, jsonify, request, send_from_directory

from town_db.schema import connect
from town_viewer.queries import get_building_detail, get_map_data, get_resident_detail, search_residents

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def create_app(db_path: str) -> Flask:
    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/api/town.svg")
    def town_svg():
        svg_path = os.path.splitext(db_path)[0] + ".svg"
        return send_from_directory(os.path.dirname(svg_path) or ".", os.path.basename(svg_path))

    @app.get("/api/map")
    def map_data():
        conn = connect(db_path)
        try:
            return jsonify(get_map_data(conn))
        finally:
            conn.close()

    @app.get("/api/buildings/<int:building_id>")
    def building_detail(building_id):
        conn = connect(db_path)
        try:
            data = get_building_detail(conn, building_id)
        finally:
            conn.close()
        if data is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(data)

    @app.get("/api/residents")
    def residents_list():
        query = request.args.get("q", "")
        try:
            page = int(request.args.get("page", 1))
        except ValueError:
            page = 1
        page = max(page, 1)
        conn = connect(db_path)
        try:
            return jsonify(search_residents(conn, query, page))
        finally:
            conn.close()

    @app.get("/api/residents/<int:resident_id>")
    def resident_detail(resident_id):
        conn = connect(db_path)
        try:
            data = get_resident_detail(conn, resident_id)
        finally:
            conn.close()
        if data is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(data)

    return app
