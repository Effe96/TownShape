from typing import Optional, Tuple

FAR_FUTURE_DATE = "9999-12-31"


def dates_overlap(
    start_a: str, end_a: Optional[str], start_b: str, end_b: Optional[str]
) -> Optional[Tuple[str, Optional[str]]]:
    effective_end_a = end_a or FAR_FUTURE_DATE
    effective_end_b = end_b or FAR_FUTURE_DATE
    if start_a > effective_end_b or start_b > effective_end_a:
        return None
    overlap_start = max(start_a, start_b)
    overlap_end_raw = min(effective_end_a, effective_end_b)
    overlap_end = None if overlap_end_raw == FAR_FUTURE_DATE else overlap_end_raw
    return overlap_start, overlap_end
