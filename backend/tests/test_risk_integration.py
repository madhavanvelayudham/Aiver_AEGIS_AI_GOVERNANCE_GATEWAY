import pytest
from datetime import datetime
from app.core.models import ProposedAction, RuntimeContext
from app.db.database import SessionLocal
from app.db.models import SessionModel, AuditEventModel, HITLRequestModel
from app.services.governance_service import GovernanceService
from app.config import get_settings
from app.tools import ToolGateway, registry as reg, ToolExecutionDenied
from sqlalchemy import select, update, delete
import uuid

@pytest.mark.anyio
async def test_risk_integration_runtime_context_fields(async_client):
    """TEST 1-4: RuntimeContext contains risk_score, risk_level, anomaly_score, risk_factors."""
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "00:00"
    settings.BUSINESS_HOURS_END = "23:59"
    
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    
    res = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res.status_code == 200
    
    # Check the database audit log to verify fields are stored in runtime_context
    async with SessionLocal() as db:
        stmt = select(AuditEventModel).order_by(AuditEventModel.created_at.desc()).limit(1)
        db_res = await db.execute(stmt)
        event = db_res.scalar_one_or_none()
        
        assert event is not None
        rc = event.runtime_context
        assert "risk_score" in rc
        assert "risk_level" in rc
        assert "anomaly_score" in rc
        assert "risk_factors" in rc
        assert rc["risk_level"] == "LOW"

@pytest.mark.anyio
async def test_risk_integration_client_injection_ignored(async_client):
    """TEST 5-7: Values calculated server-side; client injection of risk/anomaly is ignored."""
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "00:00"
    settings.BUSINESS_HOURS_END = "23:59"
    
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        },
        "risk_score": 100,
        "anomaly_score": 95,
        "risk_level": "CRITICAL"
    }
    
    res = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res.status_code == 200
    
    async with SessionLocal() as db:
        stmt = select(AuditEventModel).order_by(AuditEventModel.created_at.desc()).limit(1)
        db_res = await db.execute(stmt)
        event = db_res.scalar_one_or_none()
        
        assert event is not None
        rc = event.runtime_context
        # Inject values must NOT influence calculated server-side values (which are LOW/0)
        assert rc["risk_score"] == 20  # base read (10) + internal classification (10)
        assert rc["anomaly_score"] == 0
        assert rc["risk_level"] == "LOW"

@pytest.mark.anyio
async def test_risk_integration_history_and_anomaly(async_client):
    """TEST 8-11: History events affect anomaly score correctly."""
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "00:00"
    settings.BUSINESS_HOURS_END = "23:59"
    
    # 1. Clean history for the session
    async with SessionLocal() as db:
        await db.execute(delete(AuditEventModel).where(AuditEventModel.session_id == "test-session-after-hours"))
        await db.commit()
        
    # 2. Insufficient history check: 0 events -> anomaly_score should default to 0
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    res = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res.status_code == 200
    
    async with SessionLocal() as db:
        stmt = select(AuditEventModel).order_by(AuditEventModel.created_at.desc()).limit(1)
        db_res = await db.execute(stmt)
        event = db_res.scalar_one_or_none()
        assert event.runtime_context["anomaly_score"] == 0
        
    # 3. Insert 3 read audit events manually to simulate repeated read pattern
    async with SessionLocal() as db:
        for i in range(3):
            db.add(AuditEventModel(
                request_id=str(uuid.uuid4()),
                session_id="test-session-after-hours",
                agent_id="aegis-agent-01",
                action_type="read",
                tool_name="read_patient",
                proposed_action={"tool": "read_patient", "action_type": "read"},
                runtime_context={},
                decision="ALLOW",
                explanation="Normal",
                created_at=datetime.utcnow()
            ))
        await db.commit()
        
    # 4. Propose repeated action -> anomaly should be 0
    res_repeat = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res_repeat.status_code == 200
    async with SessionLocal() as db:
        stmt = select(AuditEventModel).order_by(AuditEventModel.created_at.desc()).limit(1)
        db_res = await db.execute(stmt)
        event = db_res.scalar_one_or_none()
        assert event.runtime_context["anomaly_score"] == 0

    # 5. Propose sudden destructive delete action type -> anomaly should spike to 100
    payload_delete = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "delete_customer",
            "arguments": {"id": "C101"},
            "action_type": "delete",
            "data_scope_size": 1
        }
    }
    res_spike = await async_client.post("/api/v1/governance/evaluate", json=payload_delete)
    assert res_spike.status_code == 200
    async with SessionLocal() as db:
        stmt = select(AuditEventModel).order_by(AuditEventModel.created_at.desc()).limit(1)
        db_res = await db.execute(stmt)
        event = db_res.scalar_one_or_none()
        assert event.runtime_context["anomaly_score"] == 100

@pytest.mark.anyio
async def test_risk_integration_recalcs_on_every_request(async_client):
    """TEST 12: Risk/anomaly is recalculated dynamically on every request."""
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "00:00"
    settings.BUSINESS_HOURS_END = "23:59"
    
    # Initial read
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    
    res1 = await async_client.post("/api/v1/governance/evaluate", json=payload)
    async with SessionLocal() as db:
        stmt = select(AuditEventModel).order_by(AuditEventModel.created_at.desc()).limit(1)
        db_res = await db.execute(stmt)
        event1 = db_res.scalar_one_or_none()
        score1 = event1.runtime_context["risk_score"]
        
    # Change time to after-hours -> risk score should increase by 10 points
    settings.BUSINESS_HOURS_START = "23:59"
    settings.BUSINESS_HOURS_END = "23:59"
    
    res2 = await async_client.post("/api/v1/governance/evaluate", json=payload)
    async with SessionLocal() as db:
        stmt = select(AuditEventModel).order_by(AuditEventModel.created_at.desc()).limit(1)
        db_res = await db.execute(stmt)
        event2 = db_res.scalar_one_or_none()
        score2 = event2.runtime_context["risk_score"]
        
    assert score2 == score1 + 10

@pytest.mark.anyio
async def test_risk_integration_hitl_approval_recalc(async_client):
    """TEST 13: HITL approval revalidation recalculates risk/anomaly."""
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "23:59"
    settings.BUSINESS_HOURS_END = "23:59"
    
    # 1. Create HITL request (during after hours)
    payload = {
        "session_id": "test-session-after-hours",
        "message": "Update patient P101"
    }
    chat_res = await async_client.post("/api/v1/agent/chat", json=payload)
    hitl_id = chat_res.json()["hitl"]["request_id"]
    
    # 2. Before approval, modify session violations count (simulates violation occurred during pending time)
    # This should increase previous_violations, resulting in a different risk calculation on revalidation
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(previous_violations=1))
        await db.commit()
        
    # 3. Approve request (revalidation runs, recalculating risk with previous_violations=1)
    # The evaluation decision will still be ALLOW since violation is 1 (threshold is 3), but the risk score will reflect the violations increase.
    approve_res = await async_client.post(f"/api/v1/hitl/{hitl_id}/approve", json={"reviewer": "Alice", "reason": "Demonstration"})
    assert approve_res.status_code == 200
    
    async with SessionLocal() as db:
        # Retrieve the approval audit event
        stmt = select(AuditEventModel).order_by(AuditEventModel.created_at.desc()).limit(1)
        db_res = await db.execute(stmt)
        event = db_res.scalar_one_or_none()
        
        # Verify previous_violations factor is present (+5 risk points)
        assert event.runtime_context["previous_violations_in_session"] == 1
        assert any("violations" in f.lower() for f in event.runtime_context["risk_factors"])

@pytest.mark.anyio
async def test_risk_integration_suspended_sessions_remain_blocked(async_client):
    """TEST 14: Suspended sessions remain blocked."""
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(status="suspended"))
        await db.commit()
        
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    res = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res.status_code == 200
    assert res.json()["decision"] == "SUSPEND_SESSION"

@pytest.mark.anyio
async def test_risk_integration_tool_gateway_allow_only():
    """TEST 15: ToolGateway remains ALLOW-only."""
    from app.tools import ToolGateway, registry as reg, ToolExecutionDenied
    gateway = ToolGateway(reg)
    
    # Non-ALLOW raises exception
    with pytest.raises(ToolExecutionDenied):
        await gateway.execute(
            ProposedAction(tool="read_patient", arguments={"patient_id": "P101"}, action_type="read", data_scope_size=1),
            "BLOCK"
        )
    with pytest.raises(ToolExecutionDenied):
        await gateway.execute(
            ProposedAction(tool="read_patient", arguments={"patient_id": "P101"}, action_type="read", data_scope_size=1),
            "REQUIRE_HITL"
        )

@pytest.mark.anyio
async def test_risk_integration_existing_behaviors_intact(async_client):
    """TEST 16-19: Existing ALLOW, REQUIRE_HITL, BLOCK, and SUSPEND_SESSION behaviors are intact."""
    settings = get_settings()
    
    # 1. ALLOW during business hours
    settings.BUSINESS_HOURS_START = "00:00"
    settings.BUSINESS_HOURS_END = "23:59"
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(status="active", previous_violations=0))
        await db.commit()
        
    payload_read = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    }
    res_allow = await async_client.post("/api/v1/governance/evaluate", json=payload_read)
    assert res_allow.json()["decision"] == "ALLOW"
    
    # 2. REQUIRE_HITL during after-hours
    settings.BUSINESS_HOURS_START = "23:59"
    settings.BUSINESS_HOURS_END = "23:59"
    payload_write = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "update_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "write",
            "data_scope_size": 1
        }
    }
    res_hitl = await async_client.post("/api/v1/governance/evaluate", json=payload_write)
    assert res_hitl.json()["decision"] == "REQUIRE_HITL"
    
    # 3. BLOCK for delete by non-admin
    payload_delete = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "delete_customer",
            "arguments": {"id": "C101"},
            "action_type": "delete",
            "data_scope_size": 1
        }
    }
    res_block = await async_client.post("/api/v1/governance/evaluate", json=payload_delete)
    assert res_block.json()["decision"] == "BLOCK"
    
    # 4. SUSPEND_SESSION escalation on 3 violations
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(previous_violations=2))
        await db.commit()
        
    # Trigger 3rd violation
    res_suspend = await async_client.post("/api/v1/governance/evaluate", json=payload_delete)
    assert res_suspend.json()["decision"] == "SUSPEND_SESSION"
