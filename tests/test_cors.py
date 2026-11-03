from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import CorsSettings, load_settings
from app.main import create_app

FRONT = "http://localhost:5173"


def _client(settings, *origins: str) -> TestClient:
    return TestClient(create_app(settings.model_copy(update={"cors": CorsSettings(allow_origins=list(origins))})))


def _preflight(client: TestClient, origin: str = FRONT):
    return client.options(
        "/api/jobs",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_any_origin_is_allowed_by_default(client):
    response = _preflight(client)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_actual_response_carries_the_header(client):
    response = client.get("/health", headers={"Origin": FRONT})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_error_responses_carry_the_header_too(client):
    response = client.get("/api/jobs/nope", headers={"Origin": FRONT})
    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == "*"


def test_listed_origin_is_echoed_and_others_are_refused(settings):
    client = _client(settings, FRONT)
    assert _preflight(client).headers["access-control-allow-origin"] == FRONT
    other = _preflight(client, "http://evil.example")
    assert other.status_code == 400
    assert "access-control-allow-origin" not in other.headers


def test_empty_list_turns_cors_off(settings):
    client = _client(settings)
    assert "access-control-allow-origin" not in client.get("/health", headers={"Origin": FRONT}).headers


def test_env_overrides_the_origins(monkeypatch):
    monkeypatch.setenv("AUTOBIM_CORS_ORIGINS", f" {FRONT} , https://app.example.com ,")
    assert load_settings().cors.allow_origins == [FRONT, "https://app.example.com"]
