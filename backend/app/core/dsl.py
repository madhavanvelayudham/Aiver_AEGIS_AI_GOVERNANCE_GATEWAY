from datetime import datetime
from app.core.models import PolicyCondition, PolicyDefinition

SUPPORTED_FIELDS: dict[str, type] = {
    "action.type": str,
    "action.tool": str,
    "context.timestamp": datetime,
    "context.user_role": str,
    "context.session_data_classification": str,
    "context.agent_id": str,
    "context.action_type": str,
    "context.data_scope_size": int,
    "context.previous_violations_in_session": int,
    "context.is_business_hours": bool,
    "context.human_approval_present": bool,
    "context.risk_score": int,
    "context.risk_level": str,
    "context.anomaly_score": int,
}

SUPPORTED_OPERATORS: dict[str, set[type]] = {
    "equals": {str, int, float, bool},
    "not_equals": {str, int, float, bool},
    "greater_than": {int, float},
    "greater_than_or_equals": {int, float},
    "less_than": {int, float},
    "less_than_or_equals": {int, float},
    "in": {str, int},
    "not_in": {str, int},
    "contains": {str},
}

VALID_DECISIONS = {"ALLOW", "BLOCK", "REQUIRE_HITL", "SUSPEND_SESSION"}

MAX_CONDITION_DEPTH = 5

def validate_field(field: str) -> bool:
    return field in SUPPORTED_FIELDS

def validate_operator(operator: str, field: str) -> bool:
    if field not in SUPPORTED_FIELDS:
        return False
    if operator not in SUPPORTED_OPERATORS:
        return False
    field_type = SUPPORTED_FIELDS[field]
    return field_type in SUPPORTED_OPERATORS[operator]

def validate_condition(condition: PolicyCondition, depth: int = 0) -> list[str]:
    errors = []
    if depth > MAX_CONDITION_DEPTH:
        return [f"Condition nesting depth exceeds maximum of {MAX_CONDITION_DEPTH}"]
    
    if condition.all_ is not None:
        for c in condition.all_:
            errors.extend(validate_condition(c, depth + 1))
    elif condition.any_ is not None:
        for c in condition.any_:
            errors.extend(validate_condition(c, depth + 1))
    else:
        if not condition.field:
            errors.append("Leaf condition must have a 'field'")
        elif not validate_field(condition.field):
            errors.append(f"Unsupported field: {condition.field}")
        
        if not condition.operator:
            errors.append("Leaf condition must have an 'operator'")
        elif condition.field and validate_field(condition.field) and not validate_operator(condition.operator, condition.field):
            errors.append(f"Operator {condition.operator} not supported for field {condition.field}")
            
    return errors

def validate_policy(policy: PolicyDefinition) -> list[str]:
    errors = []
    seen_rules = set()
    for rule in policy.rules:
        if rule.id in seen_rules:
            errors.append(f"Duplicate rule ID: {rule.id}")
        seen_rules.add(rule.id)
        
        if rule.decision not in VALID_DECISIONS:
            errors.append(f"Invalid decision '{rule.decision}' in rule {rule.id}")
            
        errors.extend([f"Rule {rule.id}: {err}" for err in validate_condition(rule.condition)])
    return errors
