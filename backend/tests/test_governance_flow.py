import pytest
from datetime import datetime
from app.core.models import ProposedAction, RuntimeContext
from app.core.policy_resolver import MissingParentPolicyError


def test_missing_policy_fails(governance_service):
    """Referencing a non-existent policy should raise an error."""
    action = ProposedAction(tool="test_tool", action_type="read", data_scope_size=1)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
        user_role="nurse",
        session_data_classification="internal",
        agent_id="aegis-agent-01",
        action_type="read",
        data_scope_size=1,
        previous_violations_in_session=0,
        session_id="test-session-1",
        is_business_hours=True,
        session_status="active",
    )
    with pytest.raises(MissingParentPolicyError):
        governance_service.evaluate(action, ctx, policy_id="nonexistent_policy")


def test_full_flow_allow(governance_service):
    """Business hours, nurse, internal data, read action -> ALLOW."""
    action = ProposedAction(tool="search_records", action_type="read", data_scope_size=1)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
        user_role="nurse",
        session_data_classification="internal",
        agent_id="aegis-agent-01",
        action_type="read",
        data_scope_size=1,
        previous_violations_in_session=0,
        session_id="test-session-1",
        is_business_hours=True,
        session_status="active",
    )
    decision = governance_service.evaluate(action, ctx)
    assert decision.decision == "ALLOW"


def test_full_flow_after_hours_hitl(governance_service):
    """After hours + write -> REQUIRE_HITL."""
    action = ProposedAction(tool="update_record", action_type="write", data_scope_size=1)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 23, 0, 0),
        user_role="nurse",
        session_data_classification="internal",
        agent_id="aegis-agent-01",
        action_type="write",
        data_scope_size=1,
        previous_violations_in_session=0,
        session_id="test-session-1",
        is_business_hours=False,
        session_status="active",
    )
    decision = governance_service.evaluate(action, ctx)
    assert decision.decision == "REQUIRE_HITL"


def test_full_flow_phi_block(governance_service):
    """PHI + external user -> BLOCK (via healthcare_policy)."""
    action = ProposedAction(tool="view_patient", action_type="read", data_scope_size=1)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
        user_role="external",
        session_data_classification="PHI",
        agent_id="aegis-agent-01",
        action_type="read",
        data_scope_size=1,
        previous_violations_in_session=0,
        session_id="test-session-2",
        is_business_hours=True,
        session_status="active",
    )
    decision = governance_service.evaluate(action, ctx, policy_id="healthcare_policy")
    assert decision.decision == "BLOCK"


def test_full_flow_violation_escalation(governance_service):
    """3rd BLOCK violation -> SUSPEND_SESSION."""
    # Non-admin delete triggers BLOCK, with 2 prior violations -> SUSPEND
    action = ProposedAction(tool="delete_record", action_type="delete", data_scope_size=1)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
        user_role="nurse",
        session_data_classification="internal",
        agent_id="aegis-agent-01",
        action_type="delete",
        data_scope_size=1,
        previous_violations_in_session=2,
        session_id="test-session-1",
        is_business_hours=True,
        session_status="active",
    )
    decision = governance_service.evaluate(action, ctx)
    assert decision.decision == "SUSPEND_SESSION"


def test_full_flow_hospital_doctor_phi_write_allowed(governance_service):
    """Doctor writing PHI using hospital_policy during business hours -> ALLOW.

    hospital_policy overrides phi_write_hitl to exclude doctors.
    Since doctor DOES equal 'doctor', the condition 'user_role not_equals doctor' is False,
    so phi_write_hitl doesn't match. And business hours means after_hours_write_hitl doesn't match.
    No other restricting rules match -> ALLOW.
    """
    action = ProposedAction(tool="update_patient_chart", action_type="write", data_scope_size=1)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
        user_role="doctor",
        session_data_classification="PHI",
        agent_id="aegis-agent-01",
        action_type="write",
        data_scope_size=1,
        previous_violations_in_session=0,
        session_id="test-session-3",
        is_business_hours=True,
        session_status="active",
    )
    decision = governance_service.evaluate(action, ctx, policy_id="hospital_policy")
    assert decision.decision == "ALLOW"


def test_full_flow_decision_contains_audit_metadata(governance_service):
    """Governance decision should contain policy chain and evaluated rules for audit."""
    action = ProposedAction(tool="update_record", action_type="write", data_scope_size=1)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 23, 0, 0),
        user_role="nurse",
        session_data_classification="internal",
        agent_id="aegis-agent-01",
        action_type="write",
        data_scope_size=1,
        previous_violations_in_session=0,
        session_id="test-session-1",
        is_business_hours=False,
        session_status="active",
    )
    decision = governance_service.evaluate(action, ctx)
    assert len(decision.policy_chain) > 0
    assert len(decision.evaluated_rules) > 0
    assert decision.decision_id  # non-empty UUID
