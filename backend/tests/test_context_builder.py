import pytest
from datetime import datetime
from app.core.models import ProposedAction, RuntimeContext
from app.core.context_builder import ContextBuilder


def test_business_hours_weekday(context_builder):
    """Tuesday 10:00 UTC should be business hours."""
    ctx = context_builder.build_for_simulation(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),  # Tuesday
        user_role="nurse",
        session_data_classification="internal",
        agent_id="agent-01",
        action_type="read",
        data_scope_size=1,
        previous_violations_in_session=0,
    )
    assert ctx.is_business_hours is True


def test_after_hours_weekday(context_builder):
    """Tuesday 23:00 UTC should NOT be business hours."""
    ctx = context_builder.build_for_simulation(
        timestamp=datetime(2026, 8, 18, 23, 0, 0),  # Tuesday
        user_role="nurse",
        session_data_classification="internal",
        agent_id="agent-01",
        action_type="read",
        data_scope_size=1,
        previous_violations_in_session=0,
    )
    assert ctx.is_business_hours is False


def test_weekend_not_business_hours(context_builder):
    """Saturday 10:00 UTC should NOT be business hours."""
    ctx = context_builder.build_for_simulation(
        timestamp=datetime(2026, 8, 22, 10, 0, 0),  # Saturday
        user_role="nurse",
        session_data_classification="internal",
        agent_id="agent-01",
        action_type="read",
        data_scope_size=1,
        previous_violations_in_session=0,
    )
    assert ctx.is_business_hours is False


def test_server_timestamp_is_used(context_builder):
    """When building from session, a specified timestamp should be used."""
    action = ProposedAction(tool="test_tool", action_type="read", data_scope_size=1)
    fixed_time = datetime(2026, 8, 18, 14, 30, 0)
    ctx = context_builder.build_from_session(
        session_id="sess-1",
        agent_id="agent-01",
        user_role="nurse",
        data_classification="internal",
        previous_violations=3,
        session_status="active",
        proposed_action=action,
        timestamp=fixed_time,
    )
    assert ctx.timestamp == fixed_time
    assert ctx.previous_violations_in_session == 3


def test_simulation_allows_custom_business_hours(context_builder):
    """Simulator can override is_business_hours."""
    # Even though it's 10:00 on Tuesday (normally business hours),
    # we can force is_business_hours=False
    ctx = context_builder.build_for_simulation(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
        user_role="nurse",
        session_data_classification="internal",
        agent_id="agent-01",
        action_type="read",
        data_scope_size=1,
        previous_violations_in_session=0,
        is_business_hours=False,
    )
    assert ctx.is_business_hours is False


def test_build_from_session_derives_action_fields(context_builder):
    """Context should derive action_type and data_scope_size from ProposedAction."""
    action = ProposedAction(tool="bulk_export", action_type="write", data_scope_size=500)
    ctx = context_builder.build_from_session(
        session_id="sess-1",
        agent_id="agent-01",
        user_role="admin",
        data_classification="PHI",
        previous_violations=0,
        session_status="active",
        proposed_action=action,
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
    )
    assert ctx.action_type == "write"
    assert ctx.data_scope_size == 500
    assert ctx.session_data_classification == "PHI"
