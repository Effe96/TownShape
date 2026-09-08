"""Subprocess boundary to the settlemaker Node bridge (generate.mjs).

See docs/superpowers/specs/2026-09-08-settlemaker-integration-design.md,
"Architecture -- the integration boundary": a plain `node generate.mjs`
subprocess, JSON over stdin/stdout, run synchronously (~150ms per call).
"""
import json
import subprocess
from pathlib import Path
from typing import Any, Dict

BRIDGE_DIR = Path(__file__).resolve().parent
GENERATE_SCRIPT = BRIDGE_DIR / "generate.mjs"


def call_settlemaker(burg: Dict[str, Any], seed: int) -> Dict[str, Any]:
    """Run settlemaker's generateSettlement via the Node bridge and return
    `{"geojson": ..., "svg": ...}` (geojson.metadata.generated_at already
    stripped by generate.mjs -- never persisted or compared, per the
    design's Determinism & Testing section)."""
    payload = json.dumps({"burg": burg, "seed": seed})
    result = subprocess.run(
        ["node", str(GENERATE_SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(BRIDGE_DIR),
    )
    if result.returncode != 0:
        raise RuntimeError(f"settlemaker bridge failed (exit {result.returncode}): {result.stderr}")
    return json.loads(result.stdout)
