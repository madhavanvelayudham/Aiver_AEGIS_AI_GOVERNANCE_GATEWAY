import pytest
from app.core.models import ProposedAction
from app.db.database import SessionLocal
from app.db.models import SessionModel, AuditEventModel
from app.config import get_settings
from app.tools import ToolGateway, registry as reg, ToolExecutionDenied
from sqlalchemy import update, delete
import uuid
from datetime import datetime

@pytest.mark.anyio
async def test_dynamic_policy_low_risk_action_allowed(async_client):
    """TEST 1: Low risk action (read) during business hours returns ALLOW."""
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "00:00"
    settings.BUSINESS_HOURS_END = "23:59"
    
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(status="active", previous_violations=0))
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
    assert res.json()["decision"] == "ALLOW"

@pytest.mark.anyio
async def test_dynamic_policy_critical_risk_delete_blocked(async_client):
    """TEST 3 & 5: Critical risk delete operation is blocked by the block_critical_risk_delete rule in base_policy."""
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "23:59"  # After-hours (+10)
    settings.BUSINESS_HOURS_END = "23:59"
    
    # Delete base score: 50 + Destructive: 20 + PHI classification: 20 + After hours: 10 = 100 (CRITICAL)
    # previous_violations = 0 to avoid triggering any suspension rules.
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(
            status="active",
            previous_violations=0,
            data_classification="phi"
        ))
        await db.commit()
        
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "delete_customer",
            "arguments": {"id": "C101"},
            "action_type": "delete",
            "data_scope_size": 1
        }
    }
    
    res = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res.status_code == 200
    assert res.json()["decision"] == "BLOCK"
    assert res.json()["deciding_rule_id"] == "block_critical_risk_delete"

@pytest.mark.anyio
async def test_dynamic_policy_high_anomaly_write_requires_hitl(async_client):
    """TEST 4: High anomaly write requires human review (high_anomaly_write_hitl rule in base_policy)."""
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "00:00"
    settings.BUSINESS_HOURS_END = "23:59"
    
    # 1. Populate session logs with repeated read pattern (3 items) to build history
    async with SessionLocal() as db:
        await db.execute(delete(AuditEventModel).where(AuditEventModel.session_id == "test-session-after-hours"))
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(
            status="active",
            previous_violations=0,
            data_classification="internal"
        ))
        for _ in range(3):
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
        
    # 2. Propose a write operation (first time in session history -> sequence deviation & novelty -> anomaly_score = 65)
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "update_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "write",
            "data_scope_size": 1
        }
    }
    
    res = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res.status_code == 200
    # Rule high_anomaly_write_hitl matches (anomaly_score = 65 > 60) and returns REQUIRE_HITL
    assert res.json()["decision"] == "REQUIRE_HITL"
    assert res.json()["deciding_rule_id"] == "high_anomaly_write_hitl"

@pytest.mark.anyio
async def test_dynamic_policy_phi_high_risk_write_block(async_client):
    """TEST 6 & 7: Stricter PHI + High Risk rule triggers BLOCK in healthcare_policy."""
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "23:59"  # After-hours (+10)
    settings.BUSINESS_HOURS_END = "23:59"
    
    # Write action base = 25
    # PHI classification = +20
    # After hours = +10
    # Large data scope = +10
    # Total = 65 (HIGH risk level)
    # previous_violations = 0 to avoid session suspension
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(
            status="active",
            user_role="nurse",
            data_classification="PHI",
            previous_violations=0,
            active_policy_id="healthcare_policy"
        ))
        await db.commit()
        
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "update_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "write",
            "data_scope_size": 150
        }
    }
    
    res = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res.status_code == 200
    # Rule phi_high_risk_write_block matches and returns BLOCK
    assert res.json()["decision"] == "BLOCK"
    assert res.json()["deciding_rule_id"] == "phi_high_risk_write_block"

@pytest.mark.anyio
async def test_dynamic_policy_inheritance_and_child_override(async_client):
    """TEST 9 & 10: Hospital policy overrides the healthcare block for trusted doctor roles."""
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "23:59"
    settings.BUSINESS_HOURS_END = "23:59"
    
    # 1. Nurse writing PHI with HIGH risk -> BLOCKED
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(
            status="active",
            user_role="nurse",
            data_classification="PHI",
            previous_violations=0,
            active_policy_id="hospital_policy"
        ))
        await db.commit()
        
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "update_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "write",
            "data_scope_size": 150
        }
    }
    
    res_nurse = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res_nurse.json()["decision"] == "BLOCK"
    assert res_nurse.json()["deciding_rule_id"] == "phi_high_risk_write_block"
    
    # 2. Doctor writing PHI with HIGH risk -> NOT blocked (because of doctor exemption override),
    # but instead matches the standard after-hours write protection -> REQUIRE_HITL!
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(
            status="active",
            user_role="doctor",
            data_classification="PHI",
            previous_violations=0,
            active_policy_id="hospital_policy"
        ))
        await db.commit()
        
    res_doctor = await async_client.post("/api/v1/governance/evaluate", json=payload)
    # The block rule does not match, so it falls back to after_hours_write_hitl -> REQUIRE_HITL!
    assert res_doctor.json()["decision"] == "REQUIRE_HITL"
    assert res_doctor.json()["deciding_rule_id"] == "after_hours_write_hitl"

@pytest.mark.anyio
async def test_dynamic_policy_same_action_different_contexts(async_client):
    """TEST 12: The same action produces ALLOW, REQUIRE_HITL, or BLOCK under different contexts."""
    payload = {
        "session_id": "test-session-after-hours",
        "action": {
            "tool": "update_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "write",
            "data_scope_size": 150
        }
    }
    
    # SCENARIO A: ALLOW (Business Hours, active session, base policy)
    settings = get_settings()
    settings.BUSINESS_HOURS_START = "00:00"
    settings.BUSINESS_HOURS_END = "23:59"
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(
            status="active",
            user_role="nurse",
            data_classification="internal",
            previous_violations=0,
            active_policy_id="base_policy"
        ))
        await db.commit()
    res_allow = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res_allow.json()["decision"] == "ALLOW"
    
    # SCENARIO B: REQUIRE_HITL (After Hours, medium/high risk)
    settings.BUSINESS_HOURS_START = "23:59"
    settings.BUSINESS_HOURS_END = "23:59"
    res_hitl = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res_hitl.json()["decision"] == "REQUIRE_HITL"
    
    # SCENARIO C: BLOCK (Stricter PHI block for high/critical risk in Healthcare Policy)
    async with SessionLocal() as db:
        await db.execute(update(SessionModel).where(SessionModel.id == "test-session-after-hours").values(
            status="active",
            user_role="nurse",
            data_classification="PHI",
            previous_violations=0,
            active_policy_id="healthcare_policy"
        ))
        await db.commit()
    res_block = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res_block.json()["decision"] == "BLOCK"

@pytest.mark.anyio
async def test_dynamic_policy_forge_prevention(async_client):
    """TEST 13-15: Neither client nor LLM can inject risk, anomaly, or decisions."""
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
        "risk_level": "CRITICAL",
        "anomaly_score": 90,
        "decision": "BLOCK",
        "session_status": "suspended"
    }
    
    res = await async_client.post("/api/v1/governance/evaluate", json=payload)
    assert res.status_code == 200
    assert res.json()["decision"] == "ALLOW"

@pytest.mark.anyio
async def test_dynamic_policy_tool_gateway_allow_only():
    """TEST 16: ToolGateway executes only when decision is ALLOW."""
    gateway = ToolGateway(reg)
    action = ProposedAction(tool="read_patient", arguments={}, action_type="read", data_scope_size=1)
    
    with pytest.raises(ToolExecutionDenied):
        await gateway.execute(action, "BLOCK")
        
    with pytest.raises(ToolExecutionDenied):
        await gateway.execute(action, "REQUIRE_HITL")
