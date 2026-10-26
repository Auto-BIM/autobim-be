"""Contract guard: the committed docs/openapi.json must match the running app.

If this fails you changed the Plan schema or the API. That belongs in a contract PR:
regenerate with `python scripts/export_openapi.py` and update docs/api.md.
"""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_openapi.py"


def _exporter():
    spec = importlib.util.spec_from_file_location("export_openapi", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_openapi_snapshot_is_current():
    exporter = _exporter()
    assert exporter.OUT.read_text(encoding="utf-8") == exporter.render()


def test_plan_schema_version_is_in_openapi():
    import json

    spec = json.loads(_exporter().OUT.read_text(encoding="utf-8"))
    version = spec["components"]["schemas"]["Plan"]["properties"]["schema_version"]
    assert version["const"] == "1.0"
