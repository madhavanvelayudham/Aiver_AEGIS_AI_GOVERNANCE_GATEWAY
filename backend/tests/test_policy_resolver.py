import pytest
from app.core.models import PolicyDefinition
from app.core.policy_resolver import CircularInheritanceError, MissingParentPolicyError


def test_child_inherits_parent_rules(loaded_policies, policy_resolver):
    """healthcare_policy should inherit all base_policy rules."""
    resolved = policy_resolver.resolve("healthcare_policy", loaded_policies)
    rule_ids = [r.id for r in resolved.rules]
    # Base rules present
    assert "after_hours_write_hitl" in rule_ids
    assert "block_large_data_scope" in rule_ids
    assert "violation_threshold_suspend" in rule_ids
    assert "delete_requires_admin" in rule_ids
    # Own rules present
    assert "phi_restricted_access" in rule_ids
    assert "phi_write_hitl" in rule_ids
    # Total: 6 base + 3 own = 9
    assert len(resolved.rules) == 9


def test_child_overrides_parent_rule(loaded_policies, policy_resolver):
    """hospital_policy overrides phi_write_hitl from healthcare_policy."""
    resolved = policy_resolver.resolve("hospital_policy", loaded_policies)
    phi_write_rule = next(r for r in resolved.rules if r.id == "phi_write_hitl")
    assert phi_write_rule.source_policy == "hospital_policy"


def test_circular_inheritance_rejected(policy_resolver):
    """Circular inheritance must raise CircularInheritanceError."""
    policies = {
        "a": PolicyDefinition(id="a", extends="b"),
        "b": PolicyDefinition(id="b", extends="a"),
    }
    with pytest.raises(CircularInheritanceError):
        policy_resolver.resolve("a", policies)


def test_missing_parent_raises_error(policy_resolver):
    """Missing parent policy should raise MissingParentPolicyError."""
    policies = {
        "child": PolicyDefinition(id="child", extends="nonexistent"),
    }
    with pytest.raises(MissingParentPolicyError):
        policy_resolver.resolve("child", policies)


def test_chain_order(loaded_policies, policy_resolver):
    """Chain should be ordered leaf -> root."""
    resolved = policy_resolver.resolve("hospital_policy", loaded_policies)
    assert resolved.chain == ["hospital_policy", "healthcare_policy", "base_policy"]


def test_root_policy_resolves(loaded_policies, policy_resolver):
    """Root policy with no parent should resolve to itself."""
    resolved = policy_resolver.resolve("base_policy", loaded_policies)
    assert resolved.chain == ["base_policy"]
    assert len(resolved.rules) == 6


def test_hospital_inherits_all_levels(loaded_policies, policy_resolver):
    """hospital_policy should have rules from all 3 levels of inheritance."""
    resolved = policy_resolver.resolve("hospital_policy", loaded_policies)
    rule_ids = [r.id for r in resolved.rules]
    # From base
    assert "after_hours_write_hitl" in rule_ids
    assert "block_large_data_scope" in rule_ids
    # From healthcare
    assert "phi_restricted_access" in rule_ids
    # From hospital (new)
    assert "external_read_block" in rule_ids
    # Override: phi_write_hitl should come from hospital
    phi_rule = next(r for r in resolved.rules if r.id == "phi_write_hitl")
    assert phi_rule.source_policy == "hospital_policy"
    # Total: 6 base + 3 healthcare + 3 hospital - 2 overrides = 10
    assert len(resolved.rules) == 10
