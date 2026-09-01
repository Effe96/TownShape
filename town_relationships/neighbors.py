import itertools
import json
from typing import Any, Dict, List, Tuple

from town_shaper.geometry import distance

from town_relationships.pairs import canonical_pair

K_NEAREST_BUILDINGS = 4


def _connected_building_pairs(
    building_coords: Dict[int, Tuple[float, float]], k: int
) -> List[Tuple[int, int, float]]:
    building_ids = sorted(building_coords)
    connected: Dict[Tuple[int, int], float] = {}
    for building_id in building_ids:
        candidates = [
            (other_id, distance(building_coords[building_id], building_coords[other_id]))
            for other_id in building_ids if other_id != building_id
        ]
        candidates.sort(key=lambda pair: (pair[1], pair[0]))
        for other_id, dist in candidates[:k]:
            lo, hi = (building_id, other_id) if building_id < other_id else (other_id, building_id)
            connected[(lo, hi)] = dist
    return [(lo, hi, dist) for (lo, hi), dist in connected.items()]


def derive_neighbor_relationships(
    residents: List[Dict[str, Any]], buildings: List[Dict[str, Any]], k: int = K_NEAREST_BUILDINGS
) -> List[Dict[str, Any]]:
    building_coords = {b["id"]: (b["x"], b["y"]) for b in buildings}

    residents_by_building: Dict[int, List[Dict[str, Any]]] = {}
    for resident in residents:
        home_id = resident.get("home_building_id")
        if home_id is not None:
            residents_by_building.setdefault(home_id, []).append(resident)

    relationships: List[Dict[str, Any]] = []

    # Same building, different household: distance 0, always neighbors.
    for occupants in residents_by_building.values():
        for a, b in itertools.combinations(occupants, 2):
            if a["household_id"] != b["household_id"]:
                detail = json.dumps({"distance": 0.0})
                relationships.append(canonical_pair(a["id"], b["id"], "neighbor", detail))

    # Cross-building K-nearest union graph.
    occupied_coords = {bid: building_coords[bid] for bid in residents_by_building if bid in building_coords}
    if len(occupied_coords) >= 2:
        for building_a, building_b, dist in _connected_building_pairs(occupied_coords, k):
            detail = json.dumps({"distance": dist})
            for resident_a in residents_by_building[building_a]:
                for resident_b in residents_by_building[building_b]:
                    relationships.append(canonical_pair(resident_a["id"], resident_b["id"], "neighbor", detail))

    return relationships
