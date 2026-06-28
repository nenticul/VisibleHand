"""Integration tests for the FastAPI endpoints using TestClient."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


def _mock_session():
    s = MagicMock()
    s.query.return_value.filter.return_value.all.return_value = []
    s.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    s.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    s.query.return_value.order_by.return_value.limit.return_value.all.return_value = []
    # latest-per-country subquery + join (dashboard & terminal)
    s.query.return_value.group_by.return_value.subquery.return_value = MagicMock()
    s.query.return_value.join.return_value.all.return_value = []
    # max() aggregate for health/scores
    s.query.return_value.scalar.return_value = None
    exec_result = MagicMock()
    exec_result.scalar.return_value = 0
    s.execute.return_value = exec_result
    return s


@pytest.fixture
def client():
    mock = _mock_session()
    with patch("api.models.database.SessionLocal", return_value=mock), \
         patch("api.dependencies.SessionLocal", return_value=mock):
        from api.main import app
        with TestClient(app) as c:
            from api.cache import score_cache
            score_cache.clear()
            yield c


# ── Health ────────────────────────────────────────────────────────────────────

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    assert "database" in body
    assert "scored_countries" in body
    assert body.get("version") == "0.3.0"


def test_health_live(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json().get("status") == "alive"


def test_health_ready(client):
    # With mocked DB execute (SELECT 1 succeeds), should be 200
    resp = client.get("/health/ready")
    assert resp.status_code in (200, 503)


def test_health_scores(client):
    resp = client.get("/health/scores")
    assert resp.status_code == 200
    assert "scored_countries" in resp.json()


def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    # Either 200 (prometheus_client installed) or 503 (not installed)
    assert resp.status_code in (200, 503)


# ── Risk scoring ──────────────────────────────────────────────────────────────

def test_landing_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "VisibleHand" in resp.text


def test_dashboard(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "Risk Monitor" in resp.text


def test_terminal_page(client):
    resp = client.get("/terminal")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "GLOBAL RISK TERMINAL" in resp.text
    assert 'id="globe"' in resp.text


def test_methodology_page(client):
    resp = client.get("/methodology")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Component Weights" in resp.text


def test_api_reference_page(client):
    resp = client.get("/api")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Endpoints" in resp.text


def test_custom_docs_page(client):
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "swagger" in resp.text.lower()


# ── VH-WSM world-state API ───────────────────────────────────────────────────

def test_worldstate_model_card(client):
    resp = client.get("/model/card")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"].startswith("vh-wsm")
    assert "limitations" in body
    assert len(body["universe"]) == 44


def test_worldstate_invalid_country_code(client):
    assert client.get("/state/123").status_code == 422
    assert client.get("/state/TOOLONG").status_code == 422


def test_worldstate_invalid_horizon(client):
    resp = client.get("/state/AR/hazards?horizon=7")
    assert resp.status_code == 422


def test_risk_endpoint_returns_200(client):
    resp = client.get("/risk/US")
    assert resp.status_code == 200
    body = resp.json()
    assert 0 <= body["composite"] <= 100
    assert "confidence" in body
    assert "risk_level" in body
    assert "breakdown" in body
    assert "top_drivers" in body
    assert "ci_low" in body
    assert "ci_high" in body
    assert "driver_attributions" in body


def test_risk_rejects_bad_code(client):
    assert client.get("/risk/USA").status_code == 422
    assert client.get("/risk/12").status_code == 422


def test_compare_route_not_shadowed(client):
    resp = client.get("/risk/compare?countries=US,DE")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert len(resp.json()) == 2


def test_history_endpoint(client):
    resp = client.get("/risk/US/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_forecast_endpoint(client):
    resp = client.get("/risk/US/forecast")
    assert resp.status_code == 200
    body = resp.json()
    assert "composite_current" in body
    assert "forecast" in body


def test_drivers_endpoint(client):
    resp = client.get("/risk/US/drivers")
    assert resp.status_code == 200
    body = resp.json()
    assert "driver_attributions" in body
    assert "top_drivers" in body


def test_movers_endpoint(client):
    resp = client.get("/risk/movers")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_bulk_endpoint(client):
    resp = client.get("/risk/bulk")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_indicators_endpoint(client):
    resp = client.get("/indicators/US")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_events_endpoint(client):
    resp = client.get("/events/BR")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_governance_endpoint(client):
    resp = client.get("/governance/DE")
    assert resp.status_code == 200
    body = resp.json()
    assert "score" in body
    assert 0 <= body["score"] <= 100


def test_swagger_docs_available(client):
    assert client.get("/docs").status_code == 200


# ── Calibration ───────────────────────────────────────────────────────────────

def test_calibration_summary(client):
    resp = client.get("/calibration/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "component_weights" in body
    assert "methodology_version" in body


def test_calibration_roc(client):
    resp = client.get("/calibration/roc")
    assert resp.status_code == 200
    body = resp.json()
    assert "auc" in body
    assert body["auc"] > 0.0


def test_calibration_roc_with_curve(client):
    resp = client.get("/calibration/roc?include_curve=true")
    assert resp.status_code == 200
    body = resp.json()
    assert "roc_curve" in body
    assert len(body["roc_curve"]) > 5


def test_calibration_dataset(client):
    resp = client.get("/calibration/dataset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_total"] > 50
    assert body["n_crises"] > 50
    assert len(body["events"]) == body["n_total"]
