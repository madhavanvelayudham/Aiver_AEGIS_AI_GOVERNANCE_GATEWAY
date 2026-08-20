from typing import Any
from app.core.models import RuntimeContext, ProposedAction, ResolvedPolicy, ResolvedRule, EvaluationResult, RuleMatch, PolicyCondition

class RuleEvaluator:
    def evaluate(self, context: RuntimeContext, action: ProposedAction, policy: ResolvedPolicy) -> EvaluationResult:
        evaluated = []
        matched = []
        for rule in policy.rules:
            try:
                result = self._evaluate_condition(rule.condition, context, action)
            except Exception:
                result = False
            evaluated.append(RuleMatch(
                rule_id=rule.id, rule_name=rule.name,
                matched=result, source_policy=rule.source_policy,
                decision=rule.decision if result else None
            ))
            if result:
                matched.append(rule)
        return EvaluationResult(evaluated_rules=evaluated, matched_rules=matched)
    
    def _evaluate_condition(self, condition: PolicyCondition, context: RuntimeContext, action: ProposedAction) -> bool:
        if condition.all_ is not None:
            return all(self._evaluate_condition(c, context, action) for c in condition.all_)
        if condition.any_ is not None:
            return any(self._evaluate_condition(c, context, action) for c in condition.any_)
        
        field_value = self._resolve_field(condition.field, context, action)
        return self._apply_operator(condition.operator, field_value, condition.value)
    
    def _resolve_field(self, field_path: str, context: RuntimeContext, action: ProposedAction) -> Any:
        if field_path.startswith("context."):
            attr = field_path[len("context."):]
            return getattr(context, attr)
        elif field_path.startswith("action."):
            attr = field_path[len("action."):]
            if attr == "type":
                return action.action_type
            elif attr == "tool":
                return action.tool
            raise ValueError(f"Unknown action field: {field_path}")
        raise ValueError(f"Unknown field prefix: {field_path}")
    
    def _apply_operator(self, operator: str, field_value: Any, target_value: Any) -> bool:
        if operator == "equals":
            return field_value == target_value
        elif operator == "not_equals":
            return field_value != target_value
        elif operator == "greater_than":
            return field_value > target_value
        elif operator == "greater_than_or_equals":
            return field_value >= target_value
        elif operator == "less_than":
            return field_value < target_value
        elif operator == "less_than_or_equals":
            return field_value <= target_value
        elif operator == "in":
            return field_value in target_value
        elif operator == "not_in":
            return field_value not in target_value
        elif operator == "contains":
            return target_value in field_value
        raise ValueError(f"Unknown operator: {operator}")
