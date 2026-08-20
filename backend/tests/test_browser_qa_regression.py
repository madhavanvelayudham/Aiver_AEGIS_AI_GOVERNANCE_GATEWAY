"""
Regression tests for bugs discovered during browser QA forensic debug.

Bug 1: HITL status field case mismatch (APPROVED/DENIED vs approved/denied)
Bug 2: Simulator session isolation — unique session IDs per run
Bug 3: Simulator not sending previous_violations to session creation
Bug 4: Risk score calculation verification for delete operations
Bug 5: Risk score calculation verification for write operations
Bug 6: Anomaly score = 0 when history < 3 entries (expected behavior)
Bug 7: audit_event_id returned by evaluate/chat endpoints
Bug 8: Session reuse — verify violations are correctly updated
Bug 9: Exact audit event lookup by primary key — must not return wrong event
Bug 10: HITL tool field null guard — proposed_action=None must not crash
Bug 11: Suspended session risk_calculated=False must prevent risk fallback
Bug 12: HITL revalidation semantics — suspended session blocks even with human approval
"""
import pytest
import uuid
from app.core.risk_engine import RiskEngine
from app.core.anomaly_analyzer import BehavioralAnomalyAnalyzer
from app.core.models import ProposedAction


# ====================================================================
# Bug 1 Regression: HITL status response must use UPPERCASE strings
# ====================================================================

@pytest.mark.anyio
async def test_hitl_approve_returns_uppercase_status(async_client):
    """Bug 1: Backend HITL approve must return status='APPROVED' (uppercase)."""
    # Create session and trigger HITL
    await async_client.post("/api/v1/governance/sessions", json={
        "session_id": "regression-hitl-status-test",
        "user_role": "nurse",
        "data_classification": "PHI"
    })
    chat_res = await async_client.post("/api/v1/agent/chat", json={
        "session_id": "regression-hitl-status-test",
        "message": "Update patient records P101"
    })
    hitl_id = chat_res.json()["hitl"]["request_id"]

    # Approve and verify exact status string
    approve_res = await async_client.post(f"/api/v1/hitl/{hitl_id}/approve", json={
        "reviewer": "QA Tester",
        "reason": "Regression test"
    })
    data = approve_res.json()
    assert approve_res.status_code == 200
    assert data["status"] == "APPROVED", f"Expected 'APPROVED' (uppercase), got '{data['status']}'"


@pytest.mark.anyio
async def test_hitl_deny_returns_uppercase_status(async_client):
    """Bug 1: Backend HITL deny must return status='DENIED' (uppercase)."""
    # Create session and trigger HITL
    await async_client.post("/api/v1/governance/sessions", json={
        "session_id": "regression-hitl-deny-status-test",
        "user_role": "nurse",
        "data_classification": "PHI"
    })
    chat_res = await async_client.post("/api/v1/agent/chat", json={
        "session_id": "regression-hitl-deny-status-test",
        "message": "Update patient records P101"
    })
    hitl_id = chat_res.json()["hitl"]["request_id"]

    # Deny and verify exact status string
    deny_res = await async_client.post(f"/api/v1/hitl/{hitl_id}/deny", json={
        "reviewer": "QA Tester",
        "reason": "Denial regression test"
    })
    data = deny_res.json()
    assert deny_res.status_code == 200
    assert data["status"] == "DENIED", f"Expected 'DENIED' (uppercase), got '{data['status']}'"


# ====================================================================
# Bug 3/8 Regression: Session creation must accept previous_violations
# ====================================================================

@pytest.mark.anyio
async def test_session_creation_accepts_violations(async_client):
    """Bug 3/8: POST /sessions must accept and persist previous_violations."""
    res = await async_client.post("/api/v1/governance/sessions", json={
        "session_id": "regression-violations-test",
        "user_role": "nurse",
        "data_classification": "PHI",
        "previous_violations": 2
    })
    data = res.json()
    assert res.status_code == 200
    assert data["previous_violations"] == 2
    assert data["status"] == "active"  # 2 violations should still be active


@pytest.mark.anyio
async def test_session_update_preserves_violations(async_client):
    """Bug 8: Repeated session creation with same ID must update violations."""
    # First creation
    await async_client.post("/api/v1/governance/sessions", json={
        "session_id": "regression-session-reuse-test",
        "user_role": "nurse",
        "data_classification": "PHI",
        "previous_violations": 0
    })

    # Update with new violations
    res = await async_client.post("/api/v1/governance/sessions", json={
        "session_id": "regression-session-reuse-test",
        "user_role": "nurse",
        "data_classification": "PHI",
        "previous_violations": 2
    })
    data = res.json()
    assert data["previous_violations"] == 2


# ====================================================================
# Bug 4 Regression: Risk score for delete on PHI must NOT be 10
# ====================================================================

def test_risk_score_delete_phi_after_hours():
    """Bug 4: delete_customer on PHI after-hours with 2 violations must be HIGH/CRITICAL, not 10/LOW."""
    engine = RiskEngine()
    action = ProposedAction(
        tool="delete_customer",
        arguments={"id": "C101"},
        action_type="delete",
        data_scope_size=1
    )
    result = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="PHI",
        previous_violations=2,
        is_business_hours=False,
        data_scope_size=1,
        anomaly_score=0
    )
    # Expected: delete(50) + PHI(20) + destructive(20) + after-hours(10) + violations(10) = 110 → clamped to 100
    assert result.risk_score == 100
    assert result.risk_level == "CRITICAL"


def test_risk_score_delete_phi_business_hours_no_violations():
    """Verify delete on PHI during business hours with no violations."""
    engine = RiskEngine()
    action = ProposedAction(
        tool="delete_customer",
        arguments={"id": "C101"},
        action_type="delete",
        data_scope_size=1
    )
    result = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="PHI",
        previous_violations=0,
        is_business_hours=True,
        data_scope_size=1,
        anomaly_score=0
    )
    # Expected: delete(50) + PHI(20) + destructive(20) = 90
    assert result.risk_score == 90
    assert result.risk_level == "CRITICAL"


# ====================================================================
# Bug 5 Regression: Risk score for write/update on PHI
# ====================================================================

def test_risk_score_update_patient_phi_after_hours():
    """Bug 5: update_patient on PHI after-hours should be 55, not 10."""
    engine = RiskEngine()
    action = ProposedAction(
        tool="update_patient",
        arguments={"patient_id": "P101"},
        action_type="write",
        data_scope_size=1
    )
    result = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="PHI",
        previous_violations=0,
        is_business_hours=False,
        data_scope_size=1,
        anomaly_score=0
    )
    # Expected: write(25) + PHI(20) + after-hours(10) = 55
    assert result.risk_score == 55
    assert result.risk_level == "MEDIUM"


# ====================================================================
# Bug 6 Regression: Anomaly score = 0 with insufficient history
# ====================================================================

def test_anomaly_score_zero_with_empty_history():
    """Bug 6: Anomaly must be 0 when history has < 3 entries."""
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(
        tool="delete_customer",
        arguments={"id": "C101"},
        action_type="delete",
        data_scope_size=1
    )
    # Empty history
    result = analyzer.analyze([], action)
    assert result.anomaly_score == 0

    # 1 entry
    result = analyzer.analyze([{"action_type": "read", "tool": "read_patient"}], action)
    assert result.anomaly_score == 0

    # 2 entries
    result = analyzer.analyze([
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ], action)
    assert result.anomaly_score == 0


def test_anomaly_score_nonzero_with_sufficient_history():
    """Bug 6 verification: anomaly must be > 0 with 3+ read-only entries followed by delete."""
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(
        tool="delete_customer",
        arguments={"id": "C101"},
        action_type="delete",
        data_scope_size=1
    )
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
    ]
    result = analyzer.analyze(history, action)
    # Novel delete(+40) + Novel tool(+20) + Sequence deviation read→delete(+40) = 100
    assert result.anomaly_score == 100
    assert len(result.signals) > 0


# ====================================================================
# Bug 7 Regression: audit_event_id returned from evaluate and chat
# ====================================================================

@pytest.mark.anyio
async def test_evaluate_returns_audit_event_id(async_client):
    """Bug 7: POST /governance/evaluate must return audit_event_id for exact correlation."""
    res = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": "test-session-allow",
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    })
    assert res.status_code == 200
    data = res.json()
    assert "audit_event_id" in data, "evaluate must return audit_event_id"
    assert data["audit_event_id"] is not None
    assert len(data["audit_event_id"]) > 0


@pytest.mark.anyio
async def test_chat_returns_audit_event_id(async_client):
    """Bug 7: POST /agent/chat must return audit_event_id for exact correlation."""
    res = await async_client.post("/api/v1/agent/chat", json={
        "session_id": "test-session-allow",
        "message": "Read patient notes"
    })
    assert res.status_code == 200
    data = res.json()
    assert "audit_event_id" in data, "chat must return audit_event_id"
    assert data["audit_event_id"] is not None
    assert len(data["audit_event_id"]) > 0


# ====================================================================
# Bug 9 Regression: Exact audit event lookup by primary key
# ====================================================================

@pytest.mark.anyio
async def test_get_audit_event_by_id_returns_correct_event(async_client):
    """Bug 9: GET /governance/audit_events/{id} must return the exact event, not a different one."""
    # Create two events in different sessions — inspector must not confuse them
    res_a = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": "test-session-allow",
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    })
    assert res_a.status_code == 200
    event_id_a = res_a.json()["audit_event_id"]

    res_b = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": "test-session-phi",
        "action": {
            "tool": "delete_patient",
            "arguments": {"patient_id": "P999"},
            "action_type": "delete",
            "data_scope_size": 1
        }
    })
    assert res_b.status_code == 200
    event_id_b = res_b.json()["audit_event_id"]

    # Fetch event A by its exact PK
    fetch_a = await async_client.get(f"/api/v1/governance/audit_events/{event_id_a}")
    assert fetch_a.status_code == 200
    data_a = fetch_a.json()
    assert data_a["id"] == event_id_a
    assert data_a["tool_name"] == "read_patient", (
        f"Expected 'read_patient' for event A, got '{data_a['tool_name']}'. "
        "Event lookup is returning a different event."
    )

    # Fetch event B by its exact PK
    fetch_b = await async_client.get(f"/api/v1/governance/audit_events/{event_id_b}")
    assert fetch_b.status_code == 200
    data_b = fetch_b.json()
    assert data_b["id"] == event_id_b
    assert data_b["tool_name"] == "delete_patient", (
        f"Expected 'delete_patient' for event B, got '{data_b['tool_name']}'. "
        "Event lookup is returning a different event."
    )

    # Events must be completely distinct
    assert event_id_a != event_id_b


@pytest.mark.anyio
async def test_get_audit_event_404_for_unknown_id(async_client):
    """Bug 9: GET /governance/audit_events/{id} must return 404 for non-existent ID."""
    fake_id = str(uuid.uuid4())
    res = await async_client.get(f"/api/v1/governance/audit_events/{fake_id}")
    assert res.status_code == 404


# ====================================================================
# Bug 10 Regression: HITL pending endpoint null guard for proposed_action
# ====================================================================

@pytest.mark.anyio
async def test_hitl_pending_endpoint_handles_null_proposed_action(async_client):
    """Bug 10: GET /hitl/pending must not crash if a HITL record has proposed_action=None."""
    from app.db.database import SessionLocal
    from app.db.models import HITLRequestModel
    from datetime import datetime
    
    # Manually insert a HITL record with null proposed_action (edge case / corrupted data)
    async with SessionLocal() as db:
        broken_hitl = HITLRequestModel(
            id=str(uuid.uuid4()),
            session_id="test-session-allow",
            agent_id="aegis-agent-01",
            proposed_action=None,    # The null guard must handle this
            runtime_context=None,
            status="PENDING",
            created_at=datetime.utcnow()
        )
        db.add(broken_hitl)
        await db.commit()
        broken_id = broken_hitl.id

    # The pending endpoint must not 500 — must return the item with tool=None
    res = await async_client.get("/api/v1/hitl/pending")
    assert res.status_code == 200, f"Pending endpoint crashed: {res.text}"
    items = res.json()
    
    # Find the broken item
    broken_items = [i for i in items if i["hitl_request_id"] == broken_id]
    assert len(broken_items) == 1
    # tool should be None (not a crash)
    assert broken_items[0]["tool"] is None, (
        f"Expected tool=null for null proposed_action, got '{broken_items[0]['tool']}'"
    )
    
    # Cleanup
    from sqlalchemy import delete as sa_delete
    async with SessionLocal() as db:
        await db.execute(sa_delete(HITLRequestModel).where(HITLRequestModel.id == broken_id))
        await db.commit()


# ====================================================================
# Bug 11 Regression: Suspended session risk display — risk_calculated=False
# ====================================================================

@pytest.mark.anyio
async def test_suspended_session_audit_event_has_risk_calculated_false(async_client):
    """Bug 11: Suspended session fast-path must store risk_calculated=False, not null runtime_context."""
    res = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": "test-session-suspended",
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    })
    assert res.status_code == 200
    data = res.json()
    assert data["decision"] == "SUSPEND_SESSION"
    
    audit_event_id = data["audit_event_id"]
    
    # Fetch the exact audit event
    fetch = await async_client.get(f"/api/v1/governance/audit_events/{audit_event_id}")
    assert fetch.status_code == 200
    event = fetch.json()
    
    assert event["runtime_context"] is not None, (
        "Suspended session audit event must not have null runtime_context. "
        "Frontend needs risk_calculated=False to display N/A instead of fabricating 10."
    )
    rc = event["runtime_context"]
    assert rc.get("risk_calculated") is False, (
        f"Expected risk_calculated=False for suspended session, got: {rc.get('risk_calculated')}"
    )
    assert rc.get("risk_score") is None, (
        f"Expected risk_score=None for suspended session, got: {rc.get('risk_score')}"
    )


# ====================================================================
# Bug 12 Regression: HITL revalidation — suspended session blocks approval
# ====================================================================

@pytest.mark.anyio
async def test_hitl_approve_blocked_when_session_suspended(async_client):
    """Bug 12: HITL approval must not execute if session became suspended during review period."""
    # 1. Create an active session
    sess_id = f"test-suspension-hitl-{uuid.uuid4()}"
    await async_client.post("/api/v1/governance/sessions", json={
        "session_id": sess_id,
        "user_role": "nurse",
        "data_classification": "PHI",
        "previous_violations": 0
    })

    # 2. Trigger HITL (must use after-hours for the policy rule to trigger REQUIRE_HITL)
    from app.config import get_settings
    settings = get_settings()
    orig_start = settings.BUSINESS_HOURS_START
    orig_end = settings.BUSINESS_HOURS_END
    settings.BUSINESS_HOURS_START = "23:59"
    settings.BUSINESS_HOURS_END = "23:59"

    chat_res = await async_client.post("/api/v1/agent/chat", json={
        "session_id": sess_id,
        "message": "Update patient records P101"
    })
    settings.BUSINESS_HOURS_START = orig_start
    settings.BUSINESS_HOURS_END = orig_end

    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert chat_data["governance"]["decision"] == "REQUIRE_HITL"
    hitl_id = chat_data["hitl"]["request_id"]

    # 3. Manually suspend the session (simulating concurrent violation accumulation)
    from app.db.database import SessionLocal
    from app.db.models import SessionModel
    from sqlalchemy import update as sa_update
    async with SessionLocal() as db:
        await db.execute(
            sa_update(SessionModel)
            .where(SessionModel.id == sess_id)
            .values(status="suspended", previous_violations=3)
        )
        await db.commit()

    # 4. Approve the HITL — revalidation must discover session is suspended and DENY
    approve_res = await async_client.post(f"/api/v1/hitl/{hitl_id}/approve", json={
        "reviewer": "Security Reviewer",
        "reason": "Approved the update"
    })
    assert approve_res.status_code == 200
    approve_data = approve_res.json()
    
    # The session is now suspended — revalidation should block this
    # SUSPEND_SESSION has higher priority than REQUIRE_HITL + human_approval_present
    assert approve_data["status"] == "DENIED", (
        f"HITL approval must be DENIED when session becomes suspended, got: {approve_data['status']}"
    )
    assert approve_data["tool_execution"]["executed"] is False, (
        "Tool must NOT be executed when session is suspended, even with human approval."
    )


# ====================================================================
# Focus Area 1 Regression: Scenario A Business Hours Context Override
# ====================================================================

@pytest.mark.anyio
async def test_scenario_a_business_hours_override_produces_risk_20_and_allow(async_client):
    """Verifies that setting explicit is_business_hours=True on session produces Business Hours YES, Risk Score 20, and ALLOW."""
    sess_id = f"test-scenario-a-{uuid.uuid4()}"
    # Provision session with explicit business hours override = True
    sess_res = await async_client.post("/api/v1/governance/sessions", json={
        "session_id": sess_id,
        "user_role": "doctor",
        "data_classification": "internal",
        "previous_violations": 0,
        "is_business_hours": True
    })
    assert sess_res.status_code == 200

    eval_res = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": sess_id,
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    })
    assert eval_res.status_code == 200
    data = eval_res.json()
    
    assert data["decision"] == "ALLOW", f"Expected ALLOW for Scenario A, got '{data['decision']}'"
    
    # Fetch exact audit event
    audit_id = data["audit_event_id"]
    audit_res = await async_client.get(f"/api/v1/governance/audit_events/{audit_id}")
    assert audit_res.status_code == 200
    event = audit_res.json()
    
    rc = event["runtime_context"]
    assert rc["is_business_hours"] is True, f"Expected is_business_hours=True, got {rc['is_business_hours']}"
    assert rc["risk_score"] == 20, f"Expected risk_score=20 (read 10 + internal 10 + bh 0), got {rc['risk_score']}"
    assert not any("outside standard business hours" in f for f in rc.get("risk_factors", [])), (
        "Outside business hours penalty must not be present when is_business_hours=True"
    )


# ====================================================================
# Focus Area 3 Regression: Scenario C Violation Boundary & Suspension
# ====================================================================

@pytest.mark.anyio
async def test_scenario_c_violation_boundary_and_suspension(async_client):
    """Verifies that previous=2 + current violation=1 → resulting=3 → SUSPEND_SESSION and DB previous_violations=3."""
    sess_id = f"test-scenario-c-{uuid.uuid4()}"
    # Provision session with previous_violations = 2
    sess_res = await async_client.post("/api/v1/governance/sessions", json={
        "session_id": sess_id,
        "user_role": "nurse",
        "data_classification": "PHI",
        "previous_violations": 2,
        "is_business_hours": False
    })
    assert sess_res.status_code == 200

    # Evaluate violating action (delete_customer)
    eval_res = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": sess_id,
        "action": {
            "tool": "delete_customer",
            "arguments": {"customer_id": "C101"},
            "action_type": "delete",
            "data_scope_size": 1
        }
    })
    assert eval_res.status_code == 200
    data = eval_res.json()
    
    assert data["decision"] == "SUSPEND_SESSION", f"Expected SUSPEND_SESSION, got '{data['decision']}'"
    
    # Check audit event runtime_context recorded previous violations = 2 before request
    audit_id = data["audit_event_id"]
    audit_res = await async_client.get(f"/api/v1/governance/audit_events/{audit_id}")
    assert audit_res.status_code == 200
    event = audit_res.json()
    assert event["runtime_context"]["previous_violations_in_session"] == 2
    
    # Check database session record now reflects resulting total violations = 3 and status = suspended
    sessions_res = await async_client.get("/api/v1/governance/sessions")
    assert sessions_res.status_code == 200
    sessions = sessions_res.json()
    sess_db = next(s for s in sessions if s["id"] == sess_id)
    assert sess_db["previous_violations"] == 3, f"Expected DB total violations=3, got {sess_db['previous_violations']}"
    assert sess_db["status"] == "suspended"


@pytest.mark.anyio
async def test_scenario_c_non_violating_action_does_not_increment_violations(async_client):
    """Verifies that previous=2 + ALLOWed action → resulting=2, status remains active."""
    sess_id = f"test-scenario-c-allow-{uuid.uuid4()}"
    sess_res = await async_client.post("/api/v1/governance/sessions", json={
        "session_id": sess_id,
        "user_role": "doctor",
        "data_classification": "internal",
        "previous_violations": 2,
        "is_business_hours": True
    })
    assert sess_res.status_code == 200

    eval_res = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": sess_id,
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    })
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["decision"] == "ALLOW"
    
    # Session violations in DB must remain 2 (not incremented)
    sessions_res = await async_client.get("/api/v1/governance/sessions")
    sessions = sessions_res.json()
    sess_db = next(s for s in sessions if s["id"] == sess_id)
    assert sess_db["previous_violations"] == 2
    assert sess_db["status"] == "active"


# ====================================================================
# Focus Area 2 Regression: Scenario B Fresh Session Anomaly Evaluation
# ====================================================================

@pytest.mark.anyio
async def test_scenario_b_fresh_session_has_zero_anomaly(async_client):
    """Verifies that Scenario B in a fresh session has anomaly_score=0 (due to insufficient history) and decision=REQUIRE_HITL."""
    sess_id = f"test-scenario-b-{uuid.uuid4()}"
    sess_res = await async_client.post("/api/v1/governance/sessions", json={
        "session_id": sess_id,
        "user_role": "nurse",
        "data_classification": "PHI",
        "previous_violations": 0,
        "is_business_hours": False
    })
    assert sess_res.status_code == 200

    chat_res = await async_client.post("/api/v1/agent/chat", json={
        "session_id": sess_id,
        "message": "Update patient diagnosis record P101"
    })
    assert chat_res.status_code == 200
    data = chat_res.json()
    assert data["governance"]["decision"] == "REQUIRE_HITL"
    
    # Check audit event
    audit_id = data["audit_event_id"]
    audit_res = await async_client.get(f"/api/v1/governance/audit_events/{audit_id}")
    event = audit_res.json()
    assert event["runtime_context"]["anomaly_score"] == 0


# ====================================================================
# Behavioral Anomaly Pipeline Forensic Regression Tests
# ====================================================================

@pytest.mark.anyio
async def test_anomaly_fresh_session_insufficient_history_signal(async_client):
    """TEST 1: Fresh session with <3 history records returns anomaly_score=0 and Insufficient history signal."""
    sess_id = f"test-insufficient-hist-{uuid.uuid4()}"
    await async_client.post("/api/v1/governance/sessions", json={
        "session_id": sess_id,
        "user_role": "doctor",
        "data_classification": "internal",
        "previous_violations": 0
    })

    eval_res = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": sess_id,
        "action": {
            "tool": "read_patient",
            "arguments": {"patient_id": "P101"},
            "action_type": "read",
            "data_scope_size": 1
        }
    })
    data = eval_res.json()
    audit_res = await async_client.get(f"/api/v1/governance/audit_events/{data['audit_event_id']}")
    rc = audit_res.json()["runtime_context"]

    assert rc["anomaly_score"] == 0
    assert rc["historical_events_count"] == 0
    assert any("Insufficient history" in s for s in rc.get("anomaly_signals", []))


@pytest.mark.anyio
async def test_anomaly_multistep_sequence_produces_genuine_nonzero_score(async_client):
    """TEST 2 & 11: Multi-step session (6 READs followed by 1 DELETE) supplies history to analyzer and produces genuine 100 score."""
    sess_id = f"test-multistep-seq-{uuid.uuid4()}"
    await async_client.post("/api/v1/governance/sessions", json={
        "session_id": sess_id,
        "user_role": "nurse",
        "data_classification": "PHI",
        "previous_violations": 0
    })

    # Execute 6 READ actions
    for i in range(6):
        await async_client.post("/api/v1/governance/evaluate", json={
            "session_id": sess_id,
            "action": {
                "tool": "read_patient",
                "arguments": {"patient_id": f"P10{i}"},
                "action_type": "read",
                "data_scope_size": 1
            }
        })

    # Execute DELETE action (7th event in session)
    del_res = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": sess_id,
        "action": {
            "tool": "delete_customer",
            "arguments": {"customer_id": "C101"},
            "action_type": "delete",
            "data_scope_size": 1
        }
    })
    del_data = del_res.json()
    audit_res = await async_client.get(f"/api/v1/governance/audit_events/{del_data['audit_event_id']}")
    rc = audit_res.json()["runtime_context"]

    assert rc["historical_events_count"] == 6, f"Expected 6 historical events analyzed, got {rc['historical_events_count']}"
    assert rc["anomaly_score"] == 100, f"Expected anomaly_score=100 for read->delete sequence deviation, got {rc['anomaly_score']}"
    assert any("delete" in s.lower() or "deviation" in s.lower() for s in rc.get("anomaly_signals", [])), (
        "Anomaly signals must explain the sequence deviation"
    )


@pytest.mark.anyio
async def test_anomaly_exact_session_isolation(async_client):
    """TEST 3: History from Session A does NOT contaminate Session B anomaly analysis."""
    sess_a = f"test-isolation-a-{uuid.uuid4()}"
    sess_b = f"test-isolation-b-{uuid.uuid4()}"

    await async_client.post("/api/v1/governance/sessions", json={"session_id": sess_a, "user_role": "doctor", "data_classification": "internal"})
    await async_client.post("/api/v1/governance/sessions", json={"session_id": sess_b, "user_role": "doctor", "data_classification": "internal"})

    # Populate 5 READ events in Session A only
    for i in range(5):
        await async_client.post("/api/v1/governance/evaluate", json={
            "session_id": sess_a,
            "action": {"tool": "read_patient", "arguments": {"patient_id": f"P10{i}"}, "action_type": "read", "data_scope_size": 1}
        })

    # Session B evaluates first action (fresh session)
    b_res = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": sess_b,
        "action": {"tool": "delete_customer", "arguments": {"customer_id": "C101"}, "action_type": "delete", "data_scope_size": 1}
    })
    b_data = b_res.json()
    b_audit = await async_client.get(f"/api/v1/governance/audit_events/{b_data['audit_event_id']}")
    b_rc = b_audit.json()["runtime_context"]

    # Session B must NOT inherit Session A's history
    assert b_rc["historical_events_count"] == 0, f"Session B inherited history! Got count={b_rc['historical_events_count']}"
    assert b_rc["anomaly_score"] == 0


@pytest.mark.anyio
async def test_anomaly_current_event_excluded_from_historical_baseline(async_client):
    """TEST 4: Current event is excluded from its own historical baseline during evaluation."""
    sess_id = f"test-self-exclusion-{uuid.uuid4()}"
    await async_client.post("/api/v1/governance/sessions", json={"session_id": sess_id, "user_role": "doctor", "data_classification": "internal"})

    # First event in session
    res = await async_client.post("/api/v1/governance/evaluate", json={
        "session_id": sess_id,
        "action": {"tool": "read_patient", "arguments": {"patient_id": "P101"}, "action_type": "read", "data_scope_size": 1}
    })
    audit = await async_client.get(f"/api/v1/governance/audit_events/{res.json()['audit_event_id']}")
    rc = audit.json()["runtime_context"]

    # Before event 1 ran, history was 0 (current event was not included in baseline)
    assert rc["historical_events_count"] == 0


