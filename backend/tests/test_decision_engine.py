import pytest
from app.core.models import (
    EvaluationResult, ResolvedRule, ResolvedPolicy, RuleMatch, PolicyCondition,
)
from app.core.decision_engine import DecisionEngine


def test_no_match_returns_allow(decision_engine):
    """When no rules matched, decision should be ALLOW."""
    evaluation = EvaluationResult(evaluated_rules=[], matched_rules=[])
    policy = ResolvedPolicy(rules=[], chain=["base_policy"])
    decision = decision_engine.decide(evaluation, policy)
    assert decision.decision == "ALLOW"
    assert decision.explanation == "No restricting rules matched. Default: ALLOW."


def test_severity_determines_outcome(decision_engine):
    """BLOCK (severity 3) should win over REQUIRE_HITL (severity 2) even with lower priority."""
    cond = PolicyCondition(field="action.type", operator="equals", value="write")
    rule_block = ResolvedRule(id="r1", name="Block Rule", decision="BLOCK", priority=50, condition=cond, source_policy="p1")
    rule_hitl = ResolvedRule(id="r2", name="HITL Rule", decision="REQUIRE_HITL", priority=100, condition=cond, source_policy="p1")

    evaluation = EvaluationResult(
        evaluated_rules=[
            RuleMatch(rule_id="r1", matched=True, source_policy="p1", decision="BLOCK"),
            RuleMatch(rule_id="r2", matched=True, source_policy="p1", decision="REQUIRE_HITL"),
        ],
        matched_rules=[rule_block, rule_hitl],
    )
    policy = ResolvedPolicy(rules=[rule_block, rule_hitl], chain=["p1"])
    decision = decision_engine.decide(evaluation, policy)
    assert decision.decision == "BLOCK"
    assert decision.deciding_rule_id == "r1"


def test_equal_severity_priority_wins(decision_engine):
    """When severity is equal, higher priority rule wins."""
    cond = PolicyCondition(field="action.type", operator="equals", value="write")
    rule_low = ResolvedRule(id="r1", name="Low Priority", decision="BLOCK", priority=50, condition=cond, source_policy="p1")
    rule_high = ResolvedRule(id="r2", name="High Priority", decision="BLOCK", priority=100, condition=cond, source_policy="p1")

    evaluation = EvaluationResult(
        evaluated_rules=[
            RuleMatch(rule_id="r1", matched=True, source_policy="p1", decision="BLOCK"),
            RuleMatch(rule_id="r2", matched=True, source_policy="p1", decision="BLOCK"),
        ],
        matched_rules=[rule_low, rule_high],
    )
    policy = ResolvedPolicy(rules=[rule_low, rule_high], chain=["p1"])
    decision = decision_engine.decide(evaluation, policy)
    assert decision.decision == "BLOCK"
    assert decision.deciding_rule_id == "r2"  # higher priority


def test_suspend_wins_over_all(decision_engine):
    """SUSPEND_SESSION should always win regardless of priority."""
    cond = PolicyCondition(field="action.type", operator="equals", value="write")
    rule_block = ResolvedRule(id="r1", decision="BLOCK", priority=200, condition=cond, source_policy="p1")
    rule_suspend = ResolvedRule(id="r2", decision="SUSPEND_SESSION", priority=50, condition=cond, source_policy="p1")

    evaluation = EvaluationResult(
        evaluated_rules=[
            RuleMatch(rule_id="r1", matched=True, source_policy="p1", decision="BLOCK"),
            RuleMatch(rule_id="r2", matched=True, source_policy="p1", decision="SUSPEND_SESSION"),
        ],
        matched_rules=[rule_block, rule_suspend],
    )
    policy = ResolvedPolicy(rules=[rule_block, rule_suspend], chain=["p1"])
    decision = decision_engine.decide(evaluation, policy)
    assert decision.decision == "SUSPEND_SESSION"
    assert decision.deciding_rule_id == "r2"
