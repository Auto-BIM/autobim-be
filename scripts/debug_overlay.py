"""Draw a Plan over the image it was recognised from (docs/recognition.md section 7).

    python scripts/debug_overlay.py plan.png plan.json -o overlay.png

Exterior walls are red, interior walls blue, with their thickness outlined; doors are green and
windows sky blue. Elements with a review item get an orange outline and their reason. The
overlay is for looking at, not for committing.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.plan import OpeningType, Plan, WallKind  # noqa: E402

WALL_COLORS = {WallKind.exterior: "red", WallKind.interior: "blue", WallKind.unknown: "gray"}
OPENING_COLORS = {OpeningType.door: "green", OpeningType.window: "deepskyblue"}
REVIEW_COLOR = "orange"


class _Projection:
    """Plan mm (y up) -> image px (y down); the inverse of image_to_plan's conversion."""

    def __init__(self, plan: Plan, image: Image.Image) -> None:
        assert plan.scale.mm_per_px, "the overlay needs an image plan with mm_per_px"
        self.s = plan.scale.mm_per_px
        self.height_px = plan.source.height_px or image.height
        # the image may have been resized since recognition
        self.fx = image.width / (plan.source.width_px or image.width)
        self.fy = image.height / self.height_px

    def __call__(self, x_mm: float, y_mm: float) -> tuple[float, float]:
        return x_mm / self.s * self.fx, (self.height_px - y_mm / self.s) * self.fy


def _strip(a, b, half_width, project):
    """Corners of the rectangle along the mm segment a-b, `half_width` mm to each side."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length * half_width, dx / length * half_width
    return [
        project(a[0] + nx, a[1] + ny),
        project(b[0] + nx, b[1] + ny),
        project(b[0] - nx, b[1] - ny),
        project(a[0] - nx, a[1] - ny),
    ]


def draw_overlay(plan: Plan, image: Image.Image) -> Image.Image:
    out = image.convert("RGB")
    draw = ImageDraw.Draw(out)
    project = _Projection(plan, out)
    flagged: dict[str, list[str]] = {}
    for item in plan.review_items:
        flagged.setdefault(item.element_id, []).append(item.reason.value)

    def outline(corners, element_id, color):
        draw.polygon(corners, outline=color)
        if element_id in flagged:
            draw.polygon(corners, outline=REVIEW_COLOR, width=3)
            cx = sum(c[0] for c in corners) / 4
            cy = sum(c[1] for c in corners) / 4
            draw.text((cx, cy + 10), ", ".join(flagged[element_id]), fill=REVIEW_COLOR)

    walls = {w.id: w for w in plan.walls}
    for w in plan.walls:
        a, b = (w.start.x, w.start.y), (w.end.x, w.end.y)
        color = WALL_COLORS[w.kind]
        draw.line([project(*a), project(*b)], fill=color, width=2)
        outline(_strip(a, b, w.thickness / 2, project), w.id, color)
        mid = project((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        draw.text((mid[0] + 4, mid[1] + 4), w.id, fill=color)

    for o in plan.openings:
        w = walls[o.wall_id]
        length = math.hypot(w.end.x - w.start.x, w.end.y - w.start.y)
        ux, uy = (w.end.x - w.start.x) / length, (w.end.y - w.start.y) / length
        s0, s1 = o.position - o.width / 2, o.position + o.width / 2
        a = (w.start.x + ux * s0, w.start.y + uy * s0)
        b = (w.start.x + ux * s1, w.start.y + uy * s1)
        color = OPENING_COLORS[o.type]
        outline(_strip(a, b, w.thickness / 2, project), o.id, color)
        draw.text(project(*a), o.id, fill=color)

    if "plan" in flagged:
        draw.text((8, 8), "plan: " + ", ".join(flagged["plan"]), fill=REVIEW_COLOR)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path, help="the drawing that was recognised")
    parser.add_argument("plan", type=Path, help="plan.json from the job's files")
    parser.add_argument("-o", "--out", type=Path, default=Path("overlay.png"))
    args = parser.parse_args()
    plan = Plan.model_validate_json(args.plan.read_text(encoding="utf-8"))
    with Image.open(args.image) as image:
        draw_overlay(plan, image).save(args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
