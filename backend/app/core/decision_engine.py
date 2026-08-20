from app.core.models import EvaluationResult, GovernanceDecision, ResolvedPolicy

DECISION_SEVERITY = {
    "SUSPEND_SESSION": 4,
    "BLOCK": 3,
    "REQUIRE_HITL": 2,
    "ALLOW": 1,
}

class DecisionEngine:
    def decide(self, evaluation: EvaluationResult, policy: ResolvedPolicy) -> GovernanceDecision:
        if not evaluation.matched_rules:
            return GovernanceDecision(
                decision="ALLOW",
                matched_rules=[],
                evaluated_rules=evaluation.evaluated_rules,
                policy_chain=policy.chain,
                explanation="No restricting rules matched. Default: ALLOW."
            )
        
        winning_rule = max(
            evaluation.matched_rules,
            key=lambda r: (DECISION_SEVERITY.get(r.decision, 0), r.priority)
        )
        
        explanation = f"Rule '{winning_rule.id}' matched: {winning_rule.description or winning_rule.name}"
        
        return GovernanceDecision(
            decision=winning_rule.decision,
            deciding_rule_id=winning_rule.id,
            matched_rules=[r.id for r in evaluation.matched_rules],
            evaluated_rules=evaluation.evaluated_rules,
            policy_chain=policy.chain,
            explanation=explanation
        )
