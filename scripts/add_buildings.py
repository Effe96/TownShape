"""Usage: python scripts/add_buildings.py <db_path> <count> [--where roads|perimeter] [--type residence] [--near PLACE]

Builds new buildings on an existing town (DB + its .svg) -- see
town_db/construction.py and docs/narrative-construction.md."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from town_db.construction import PLACEMENT_MODES, add_buildings

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path")
    parser.add_argument("count", type=int)
    parser.add_argument("--where", choices=PLACEMENT_MODES, default="roads")
    parser.add_argument("--type", dest="building_type", default="residence")
    parser.add_argument("--near", default=None, help='e.g. "north gate", "The Rusty Anvil", "temple", "mill", "river", or a building id')
    args = parser.parse_args()
    ids = add_buildings(args.db_path, args.count, where=args.where, building_type=args.building_type, near=args.near)
    print(f"Built {len(ids)} of {args.count} {args.building_type} building(s): ids {ids[0] if ids else '-'}..{ids[-1] if ids else '-'}")
