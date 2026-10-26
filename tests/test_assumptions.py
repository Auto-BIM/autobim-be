"""docs/ASSUMPTIONS.md is the source of truth for defaults; code must match it."""

import re
from pathlib import Path

from app.core import defaults

DOC = Path(__file__).resolve().parents[1] / "docs" / "ASSUMPTIONS.md"


def _doc_values() -> dict[str, float]:
    rows = re.findall(r"^\|\s*([a-z_]+)\s*\|\s*([\d.]+)\s*\|", DOC.read_text(), flags=re.M)
    return {k: float(v) for k, v in rows}


def test_code_defaults_match_assumptions_doc():
    assert _doc_values() == defaults.ASSUMPTIONS


def test_agreed_baseline_values():
    # The five baseline values from the design brief.
    assert defaults.EXTERIOR_WALL_THICKNESS == 200
    assert defaults.INTERIOR_WALL_THICKNESS == 120
    assert defaults.WALL_HEIGHT == 2400
    assert (defaults.DOOR_WIDTH, defaults.DOOR_HEIGHT) == (900, 2100)
    assert (defaults.WINDOW_WIDTH, defaults.WINDOW_HEIGHT) == (1200, 1200)
