"""Usage: python scripts/serve_town_viewer.py <db_path> [--port PORT]"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from town_viewer.app import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    app = create_app(args.db_path)
    print(f"Serving {args.db_path} at http://127.0.0.1:{args.port}")
    app.run(port=args.port)
