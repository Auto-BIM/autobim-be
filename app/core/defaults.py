"""Default dimensions (mm). Source of truth: docs/ASSUMPTIONS.md — keep in sync.

tests/test_assumptions.py fails if these drift from the document.
"""

EXTERIOR_WALL_THICKNESS = 200.0
INTERIOR_WALL_THICKNESS = 120.0
WALL_HEIGHT = 2400.0
DOOR_WIDTH = 900.0
DOOR_HEIGHT = 2100.0
WINDOW_WIDTH = 1200.0
WINDOW_HEIGHT = 1200.0
WINDOW_SILL_HEIGHT = 900.0

# key in docs/ASSUMPTIONS.md -> value
ASSUMPTIONS: dict[str, float] = {
    "exterior_wall_thickness": EXTERIOR_WALL_THICKNESS,
    "interior_wall_thickness": INTERIOR_WALL_THICKNESS,
    "wall_height": WALL_HEIGHT,
    "door_width": DOOR_WIDTH,
    "door_height": DOOR_HEIGHT,
    "window_width": WINDOW_WIDTH,
    "window_height": WINDOW_HEIGHT,
    "window_sill_height": WINDOW_SILL_HEIGHT,
}
