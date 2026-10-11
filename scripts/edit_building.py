"""Usage:
  python scripts/edit_building.py <db_path> demolish <building_id> [--ruin]
  python scripts/edit_building.py <db_path> resize <building_id> <area_factor> [--absorb]
  python scripts/edit_building.py <db_path> reshape <building_id> rectangle|square|round [--area-factor F] [--absorb]

Edits one existing building of a town (DB + its .svg) -- see
town_db/construction.py and docs/narrative-construction.md."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from town_db.construction import RESHAPES, demolish_building, reshape_building, resize_building

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path")
    sub = parser.add_subparsers(dest="op", required=True)
    p = sub.add_parser("demolish")
    p.add_argument("building_id", type=int)
    p.add_argument("--ruin", action="store_true")
    p = sub.add_parser("resize")
    p.add_argument("building_id", type=int)
    p.add_argument("area_factor", type=float)
    p.add_argument("--absorb", action="store_true")
    p = sub.add_parser("reshape")
    p.add_argument("building_id", type=int)
    p.add_argument("shape", choices=RESHAPES)
    p.add_argument("--area-factor", type=float, default=1.0)
    p.add_argument("--absorb", action="store_true")
    args = parser.parse_args()

    if args.op == "demolish":
        demolish_building(args.db_path, args.building_id, ruin=args.ruin)
        print(f"Building {args.building_id} {'left as a ruin' if args.ruin else 'demolished'}")
    elif args.op == "resize":
        print(resize_building(args.db_path, args.building_id, args.area_factor, absorb_neighbors=args.absorb))
    else:
        print(reshape_building(args.db_path, args.building_id, args.shape,
                               area_factor=args.area_factor, absorb_neighbors=args.absorb))
