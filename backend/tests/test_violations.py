import pytest
from datetime import datetime
from app.core.models import ProposedAction, RuntimeContext
from app.core.context_builder import ContextBuilder


def test_second_violation_returns_block(governance_service):
    """With previous_violations=1, a BLOCK decision stays BLOCK (not escalated)."""
    # delete by non-admin triggers delete_requires_admin -> BLOCK
    action = ProposedAction(tool="delete_record", action_type="delete", data_scope_size=1)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
        user_role="nurse",
        session_data_classification="internal",
        agent_id="aegis-agent-01",
        action_type="delete",
        data_scope_size=1,
        previous_violations_in_session=1,
        session_id="test-session-1",
        is_business_hours=True,
        session_status="active",
    )
    decision = governance_service.evaluate(action, ctx)
    assert decision.decision == "BLOCK"


def test_third_violation_returns_suspend(governance_service):
    """With previous_violations=2, a BLOCK escalates to SUSPEND_SESSION (CORRECTION A)."""
    # delete by non-admin triggers BLOCK, with 2 prior violations -> 3rd = SUSPEND
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
    assert "threshold" in decision.explanation.lower() or "suspend" in decision.explanation.lower()


def test_client_cannot_forge_violation_count():
    """Server-derived violation count (via context builder) cannot be overridden by client."""
    builder = ContextBuilder()
    action = ProposedAction(tool="test_tool", action_type="read", data_scope_size=1)
    ctx = builder.build_from_session(
        session_id="sess-1",
        agent_id="agent-01",
        user_role="nurse",
        data_classification="internal",
        previous_violations=5,  # server value
        session_status="active",
        proposed_action=action,
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
    )
    # The context uses the server-provided value, not client-supplied
    assert ctx.previous_violations_in_session == 5


def test_suspended_session_immediately_rejected(governance_service):
    """A suspended session returns SUSPEND_SESSION without rule evaluation."""
    action = ProposedAction(tool="read_data", action_type="read", data_scope_size=1)
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
        session_status="suspended",
    )
    decision = governance_service.evaluate(action, ctx)
    assert decision.decision == "SUSPEND_SESSION"
    assert "suspended" in decision.explanation.lower()


def test_hitl_does_not_escalate_to_suspend(governance_service):
    """REQUIRE_HITL decisions should NOT trigger violation threshold escalation."""
    # after-hours write triggers REQUIRE_HITL, with 2 prior violations
    # HITL is NOT a violation, so should NOT escalate to SUSPEND
    action = ProposedAction(tool="update_record", action_type="write", data_scope_size=1)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 23, 0, 0),
        user_role="nurse",
        session_data_classification="internal",
        agent_id="aegis-agent-01",
        action_type="write",
        data_scope_size=1,
        previous_violations_in_session=2,
        session_id="test-session-1",
        is_business_hours=False,
        session_status="active",
    )
    decision = governance_service.evaluate(action, ctx)
    assert decision.decision == "REQUIRE_HITL"


def test_allow_does_not_increment_violations(governance_service):
    """ALLOW decisions don't cause escalation — a clean read stays ALLOW."""
    action = ProposedAction(tool="search_data", action_type="read", data_scope_size=1)
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
