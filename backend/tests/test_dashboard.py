import pytest
from app.db.database import SessionLocal
from app.db.models import AuditEventModel


@pytest.mark.anyio
async def test_dashboard_root_html(async_client):
    """Verifies that the root path serves the dashboard HTML successfully."""
    response = await async_client.get("/")
    assert response.status_code == 200
    assert "AEGIS" in response.text
    assert "style.css" in response.text


@pytest.mark.anyio
async def test_dashboard_api_endpoints(async_client):
    """Verifies that administrative API GET endpoints return structured metadata."""
    # Check metrics
    metrics_res = await async_client.get("/api/v1/governance/metrics")
    assert metrics_res.status_code == 200
    data = metrics_res.json()
    assert "total_requests" in data
    assert "decision_counts" in data
    assert "session_counts" in data

    # Check sessions listing
    sess_res = await async_client.get("/api/v1/governance/sessions")
    assert sess_res.status_code == 200
    assert isinstance(sess_res.json(), list)

    # Check active policies listing
    pol_res = await async_client.get("/api/v1/governance/policies")
    assert pol_res.status_code == 200
    assert isinstance(pol_res.json(), list)

    # Check audit events listing
    audit_res = await async_client.get("/api/v1/governance/audit_events")
    assert audit_res.status_code == 200
    assert isinstance(audit_res.json(), list)


@pytest.mark.anyio
async def test_seed_session_endpoint(async_client):
    """Verifies that the simulator can provision a custom session on the fly."""
    payload = {
        "session_id": "simulated-custom-session-999",
        "user_role": "nurse",
        "data_classification": "phi"
    }
    response = await async_client.post("/api/v1/governance/sessions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "simulated-custom-session-999"
    assert data["user_role"] == "nurse"
    assert data["data_classification"] == "phi"
    assert data["status"] == "active"


@pytest.mark.anyio
async def test_seed_session_endpoint_with_violations(async_client):
    """Verifies that the simulator can seed violations and trigger dynamic suspension status."""
    payload = {
        "session_id": "simulated-custom-session-999",
        "user_role": "nurse",
        "data_classification": "phi",
        "previous_violations": 3
    }
    response = await async_client.post("/api/v1/governance/sessions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["previous_violations"] == 3
    assert data["status"] == "suspended"
