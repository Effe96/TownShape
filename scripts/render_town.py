"""Usage: python scripts/render_town.py <db_path> [output_path]

If output_path is omitted, it defaults to the db_path with a .png extension.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from town_db.render import render_town

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    db_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(db_path)[0] + ".png"

    render_town(db_path, output_path)
    print(f"Wrote {output_path}")
