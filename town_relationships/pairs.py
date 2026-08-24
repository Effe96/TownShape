from typing import Any, Dict, Optional


def canonical_pair(
    resident_a_id: int, resident_b_id: int, relationship_type: str, detail: Optional[str] = None
) -> Dict[str, Any]:
    lo, hi = (resident_a_id, resident_b_id) if resident_a_id < resident_b_id else (resident_b_id, resident_a_id)
    return {"resident_a_id": lo, "resident_b_id": hi, "relationship_type": relationship_type, "detail": detail}
