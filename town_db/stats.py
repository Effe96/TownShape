import sqlite3

STRESS_PER_SKIRMISH = 0.1


def compute_stress(db_path: str) -> float:
    conn = sqlite3.connect(db_path)
    poor_count, total_count = conn.execute(
        "SELECT SUM(CASE WHEN ses = 'poor' THEN 1 ELSE 0 END), COUNT(*) FROM residents"
    ).fetchone()
    skirmish_count = conn.execute("SELECT COUNT(*) FROM skirmish_events").fetchone()[0]
    conn.close()

    if not total_count:
        return 0.0

    poor_fraction = poor_count / total_count
    return min(1.0, poor_fraction + skirmish_count * STRESS_PER_SKIRMISH)
