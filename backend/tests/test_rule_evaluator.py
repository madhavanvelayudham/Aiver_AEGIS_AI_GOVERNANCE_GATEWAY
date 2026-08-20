import pytest
from datetime import datetime
from app.core.models import ProposedAction, RuntimeContext, ResolvedRule, ResolvedPolicy, PolicyCondition, EvaluationResult, RuleMatch
from app.core.rule_evaluator import RuleEvaluator


def test_after_hours_write_matches_hitl_rule(rule_evaluator, loaded_policies, policy_resolver, sample_write_action, after_hours_context):
    """Write action outside business hours should match the after_hours_write_hitl rule."""
    resolved = policy_resolver.resolve("base_policy", loaded_policies)
    ctx = after_hours_context()
    result = rule_evaluator.evaluate(ctx, sample_write_action, resolved)
    matched_ids = [r.id for r in result.matched_rules]
    assert "after_hours_write_hitl" in matched_ids


def test_business_hours_write_no_after_hours_match(rule_evaluator, loaded_policies, policy_resolver, sample_write_action, business_hours_context):
    """Write action during business hours should NOT match the after_hours rule."""
    resolved = policy_resolver.resolve("base_policy", loaded_policies)
    ctx = business_hours_context()
    result = rule_evaluator.evaluate(ctx, sample_write_action, resolved)
    matched_ids = [r.id for r in result.matched_rules]
    assert "after_hours_write_hitl" not in matched_ids


def test_phi_external_user_blocked(rule_evaluator, loaded_policies, policy_resolver, sample_read_action, phi_external_context):
    """External user accessing PHI data should trigger phi_restricted_access BLOCK."""
    resolved = policy_resolver.resolve("healthcare_policy", loaded_policies)
    ctx = phi_external_context()
    result = rule_evaluator.evaluate(ctx, sample_read_action, resolved)
    matched_ids = [r.id for r in result.matched_rules]
    assert "phi_restricted_access" in matched_ids


def test_no_rules_match_returns_empty(rule_evaluator, loaded_policies, policy_resolver, sample_read_action, business_hours_context):
    """When no rules match, matched_rules should be empty."""
    resolved = policy_resolver.resolve("base_policy", loaded_policies)
    ctx = business_hours_context()
    # read + business hours + nurse + internal + 0 violations + data_scope=1
    ctx_read = RuntimeContext(
        timestamp=ctx.timestamp,
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
    result = rule_evaluator.evaluate(ctx_read, sample_read_action, resolved)
    assert len(result.matched_rules) == 0


def test_large_data_scope_blocked(rule_evaluator, loaded_policies, policy_resolver, sample_read_action):
    """Action with data_scope_size > 1000 should match block_large_data_scope."""
    resolved = policy_resolver.resolve("base_policy", loaded_policies)
    large_action = ProposedAction(tool="bulk_export", action_type="read", data_scope_size=1500)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
        user_role="nurse",
        session_data_classification="internal",
        agent_id="aegis-agent-01",
        action_type="read",
        data_scope_size=1500,
        previous_violations_in_session=0,
        session_id="test-session-1",
        is_business_hours=True,
        session_status="active",
    )
    result = rule_evaluator.evaluate(ctx, large_action, resolved)
    matched_ids = [r.id for r in result.matched_rules]
    assert "block_large_data_scope" in matched_ids


def test_delete_by_non_admin_blocked(rule_evaluator, loaded_policies, policy_resolver, sample_delete_action):
    """Non-admin user performing delete should match delete_requires_admin."""
    resolved = policy_resolver.resolve("base_policy", loaded_policies)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
        user_role="nurse",
        session_data_classification="internal",
        agent_id="aegis-agent-01",
        action_type="delete",
        data_scope_size=1,
        previous_violations_in_session=0,
        session_id="test-session-1",
        is_business_hours=True,
        session_status="active",
    )
    result = rule_evaluator.evaluate(ctx, sample_delete_action, resolved)
    matched_ids = [r.id for r in result.matched_rules]
    assert "delete_requires_admin" in matched_ids


def test_delete_by_admin_allowed(rule_evaluator, loaded_policies, policy_resolver):
    """Admin user performing delete should NOT match delete_requires_admin."""
    resolved = policy_resolver.resolve("base_policy", loaded_policies)
    action = ProposedAction(tool="delete_patient", action_type="delete", data_scope_size=1)
    ctx = RuntimeContext(
        timestamp=datetime(2026, 8, 18, 10, 0, 0),
        user_role="admin",
        session_data_classification="internal",
        agent_id="aegis-agent-01",
        action_type="delete",
        data_scope_size=1,
        previous_violations_in_session=0,
        session_id="test-session-1",
        is_business_hours=True,
        session_status="active",
    )
    result = rule_evaluator.evaluate(ctx, action, resolved)
    matched_ids = [r.id for r in result.matched_rules]
    assert "delete_requires_admin" not in matched_ids
