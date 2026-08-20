from collections import OrderedDict
from app.core.models import PolicyDefinition, ResolvedPolicy, ResolvedRule

MAX_INHERITANCE_DEPTH = 10

class CircularInheritanceError(Exception): ...
class MissingParentPolicyError(Exception): ...
class InheritanceDepthError(Exception): ...

class PolicyResolver:
    def resolve(self, policy_id: str, policies: dict[str, PolicyDefinition]) -> ResolvedPolicy:
        chain = []
        chain_versions = []
        current_id = policy_id
        visited = set()
        
        while current_id:
            if current_id in visited:
                raise CircularInheritanceError(f"Circular inheritance detected at {current_id}")
            if current_id not in policies:
                raise MissingParentPolicyError(f"Policy {current_id} not found in policies")
                
            visited.add(current_id)
            chain.append(current_id)
            chain_versions.append(policies[current_id].version)
            
            if len(chain) > MAX_INHERITANCE_DEPTH:
                raise InheritanceDepthError(f"Inheritance depth exceeds {MAX_INHERITANCE_DEPTH}")
                
            current_id = policies[current_id].extends
            
        # Reverse chain to start from root
        chain.reverse()
        chain_versions.reverse()
        
        merged_rules = OrderedDict()
        for p_id in chain:
            policy = policies[p_id]
            for rule in policy.rules:
                resolved_rule = ResolvedRule(
                    id=rule.id,
                    name=rule.name,
                    description=rule.description,
                    priority=rule.priority,
                    decision=rule.decision,
                    condition=rule.condition,
                    source_policy=p_id
                )
                merged_rules[rule.id] = resolved_rule
                
        # the requested chain format likely needs to be child -> root as requested in model definition (chain list e.g. ["hospital_policy", "healthcare_policy", "base_policy"])
        # Wait, the instruction says "e.g. ["hospital_policy", "healthcare_policy", "base_policy"]", so that's leaf to root.
        # So reverse again for output.
        chain.reverse()
        chain_versions.reverse()
        
        return ResolvedPolicy(
            rules=list(merged_rules.values()),
            chain=chain,
            chain_versions=chain_versions
        )
