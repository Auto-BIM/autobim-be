"""DXF path: .dxf -> Plan. Placeholder until next-tasks #2.

Planned: read with ezdxf, classify walls/doors/windows by layer and block names,
merge double-line walls (parallel pairs) into centerline + thickness, units from $INSUNITS.
"""

from __future__ import annotations

from app.schemas.plan import Plan


def dxf_to_plan(data: bytes, *, filename: str | None = None) -> Plan:
    raise NotImplementedError("DXF input is not implemented yet (see docs/next-tasks.md #2)")
