import pytest
from app.core.dsl import validate_condition, validate_field, validate_operator, validate_policy
from app.core.models import PolicyCondition, PolicyRule, PolicyDefinition


def test_invalid_field_rejected():
    """Unknown field in condition should produce validation error."""
    condition = PolicyCondition(field="context.nonexistent", operator="equals", value="test")
    errors = validate_condition(condition)
    assert len(errors) > 0
    assert "Unsupported field" in errors[0]


def test_invalid_operator_rejected():
    """Unknown operator should produce validation error."""
    condition = PolicyCondition(field="context.user_role", operator="invalid_op", value="test")
    errors = validate_condition(condition)
    assert len(errors) > 0


def test_valid_field_accepted():
    """All supported fields should validate without errors."""
    condition = PolicyCondition(field="action.type", operator="equals", value="read")
    errors = validate_condition(condition)
    assert len(errors) == 0


def test_valid_operator_for_field():
    """equals on string field should work."""
    condition = PolicyCondition(field="context.user_role", operator="equals", value="admin")
    errors = validate_condition(condition)
    assert len(errors) == 0


def test_incompatible_operator_for_field():
    """greater_than on boolean field should fail."""
    condition = PolicyCondition(field="context.is_business_hours", operator="greater_than", value=True)
    errors = validate_condition(condition)
    assert len(errors) > 0


def test_duplicate_rule_ids_rejected():
    """Policy with two rules having same ID should produce error."""
    cond = PolicyCondition(field="action.type", operator="equals", value="read")
    policy = PolicyDefinition(
        id="test_policy",
        rules=[
            PolicyRule(id="rule1", decision="BLOCK", condition=cond),
            PolicyRule(id="rule1", decision="ALLOW", condition=cond),
        ],
    )
    errors = validate_policy(policy)
    assert any("Duplicate rule ID" in e for e in errors)


def test_condition_depth_limit():
    """Deeply nested conditions beyond MAX_CONDITION_DEPTH should fail."""
    # Build 7 levels of nesting (MAX_CONDITION_DEPTH is 5)
    leaf = PolicyCondition(field="action.type", operator="equals", value="read")
    current = leaf
    for _ in range(7):
        current = PolicyCondition(all_=[current])
    errors = validate_condition(current)
    assert len(errors) > 0
    assert "depth" in errors[0].lower()


def test_validate_field_returns_true_for_known():
    assert validate_field("action.type") is True
    assert validate_field("context.user_role") is True
    assert validate_field("context.is_business_hours") is True


def test_validate_field_returns_false_for_unknown():
    assert validate_field("context.unknown") is False
    assert validate_field("foo.bar") is False


def test_validate_operator_int_field():
    """greater_than should work on int fields."""
    assert validate_operator("greater_than", "context.data_scope_size") is True
    assert validate_operator("equals", "context.data_scope_size") is True


def test_all_combinator_validates_children():
    """Errors in children of 'all' combinator should be reported."""
    condition = PolicyCondition(all_=[
        PolicyCondition(field="context.bad_field", operator="equals", value="x"),
        PolicyCondition(field="action.type", operator="equals", value="read"),
    ])
    errors = validate_condition(condition)
    assert len(errors) == 1
    assert "Unsupported field" in errors[0]


def test_any_combinator_validates_children():
    """Errors in children of 'any' combinator should be reported."""
    condition = PolicyCondition(any_=[
        PolicyCondition(field="action.type", operator="bad_op", value="read"),
    ])
    errors = validate_condition(condition)
    assert len(errors) > 0
