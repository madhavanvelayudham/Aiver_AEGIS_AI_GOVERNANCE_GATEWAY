import pytest
from datetime import datetime
from sqlalchemy import select
from app.config import get_settings
from app.db.database import SessionLocal
from app.db.models import AuditEventModel, SessionModel


@pytest.mark.anyio
async def test_health_endpoint(async_client):
    """TEST 12: Health endpoint works."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "aegis-api"}


@pytest.mark.anyio
async def test_valid_allowed_action(async_client):
    """TEST 1: Valid allowed action -> 200 + ALLOW."""
    payload = {
        "session_id": "test-session-allow",
        "action": {
            "tool": "search_patients",
            "arguments": {},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "ALLOW"
    assert data["session_id"] == "test-session-allow"
    assert "request_id" in data  # TEST 11: Response contains request_id


@pytest.mark.anyio
async def test_after_hours_write_requires_hitl(async_client):
    """TEST 2: After-hours write -> 200 + REQUIRE_HITL."""
    # Force after-hours by overriding business hours start/end settings
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "23:59"
    settings.BUSINESS_HOURS_END = "23:59"
    
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "update_record",
            "arguments": {"notes": "test notes"},
            "action_type": "write",
            "data_scope_size": 1
        }
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "REQUIRE_HITL"
    assert "after_hours_write_hitl" in data["matched_rules"]


@pytest.mark.anyio
async def test_phi_restricted_action_blocks(async_client):
    """TEST 3: PHI restricted action -> 200 + BLOCK (healthcare policy restricts)."""
    payload = {
        "session_id": "test-session-phi",
        "action": {
            "tool": "view_phi_record",
            "arguments": {"record_id": "r101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "BLOCK"
    assert "phi_restricted_access" in data["matched_rules"]


@pytest.mark.anyio
async def test_third_violation_suspends_session(async_client):
    """TEST 4: Third violation -> 200 + SUSPEND_SESSION."""
    # test-session-violation has previous_violations = 2
    # Non-admin delete action triggers BLOCK -> escalates to SUSPEND_SESSION
    payload = {
        "session_id": "test-session-violation",
        "action": {
            "tool": "delete_patient_chart",
            "arguments": {"chart_id": "c909"},
            "action_type": "delete",
            "data_scope_size": 1
        }
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "SUSPEND_SESSION"
    assert data["violation_count"] == 3
    assert data["session_status"] == "suspended"


@pytest.mark.anyio
async def test_already_suspended_session_rejection(async_client):
    """TEST 5: Suspended session -> action evaluated to SUSPEND_SESSION (Correction 2)."""
    payload = {
        "session_id": "test-session-suspended",
        "action": {
            "tool": "search_patients",
            "arguments": {},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "SUSPEND_SESSION"
    assert "suspended" in data["explanation"].lower()


@pytest.mark.anyio
async def test_unknown_session_returns_404(async_client):
    """TEST 6: Unknown session -> 404."""
    payload = {
        "session_id": "nonexistent-session-id",
        "action": {
            "tool": "search_patients",
            "arguments": {},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_malformed_action_returns_422(async_client):
    """TEST 7: Malformed action -> 422."""
    payload = {
        "session_id": "test-session-allow",
        "action": {
            "tool": "",  # Empty tool is validation error
            "arguments": {},
            "action_type": "invalid_type",  # Invalid enum value
            "data_scope_size": -1  # Invalid size
        }
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 422


@pytest.mark.anyio
async def test_client_cannot_forge_previous_violations(async_client):
    """TEST 8: Client attempts to provide previous_violations -> server ignores and uses DB value."""
    # Send extra field in action arguments or request payload.
    # The client cannot inject previous_violations since Pydantic EvaluationRequest schema doesn't accept it,
    # and the server derives it purely from the database session record.
    payload = {
        "session_id": "test-session-allow",
        "action": {
            "tool": "search_patients",
            "arguments": {"previous_violations": 99},  # Forge attempt inside args
            "action_type": "read",
            "data_scope_size": 1
        },
        "previous_violations": 99  # Forge attempt inside request body
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    # Should use the DB session's true value (0), not 99.
    assert data["violation_count"] == 0


@pytest.mark.anyio
async def test_policy_inheritance_resolves_through_api(async_client):
    """TEST 9: Policy inheritance through API -> child policy resolves parent rules."""
    # test-session-phi uses healthcare_policy which inherits block_large_data_scope from base_policy
    payload = {
        "session_id": "test-session-phi",
        "action": {
            "tool": "export_records",
            "arguments": {},
            "action_type": "read",
            "data_scope_size": 1500  # triggers block_large_data_scope
        }
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "BLOCK"
    assert "block_large_data_scope" in data["matched_rules"]
    assert data["policy_chain"] == ["healthcare_policy", "base_policy"]


@pytest.mark.anyio
async def test_audit_event_is_persisted(async_client):
    """TEST 10: Audit event is persisted in DB."""
    # Send a request
    payload = {
        "session_id": "test-session-allow",
        "action": {
            "tool": "audit_test_tool",
            "arguments": {"key_to_redact": "secret_password_123"},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 200
    req_id = response.json()["request_id"]
    
    # Query the DB to check if audit event exists
    async with SessionLocal() as db:
        stmt = select(AuditEventModel).where(AuditEventModel.request_id == req_id)
        res = await db.execute(stmt)
        event = res.scalar_one_or_none()
        
        assert event is not None
        assert event.session_id == "test-session-allow"
        assert event.tool_name == "audit_test_tool"
        assert event.decision == "ALLOW"
        
        # Verify basic argument sanitization
        proposed_action_json = event.proposed_action
        assert proposed_action_json["arguments"]["key_to_redact"] == "[REDACTED]"


@pytest.mark.anyio
async def test_response_contains_request_id(async_client):
    """TEST 11: Response contains request_id."""
    payload = {
        "session_id": "test-session-allow",
        "action": {
            "tool": "search_patients",
            "arguments": {},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    response = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "request_id" in data
    # Ensure it's a valid UUID string format
    import uuid
    val = uuid.UUID(data["request_id"])
    assert val is not None

