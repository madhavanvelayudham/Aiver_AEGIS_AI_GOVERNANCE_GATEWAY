import yaml
from pathlib import Path
from app.core.models import PolicyDefinition, PolicyCondition, PolicyRule
from app.core.dsl import validate_policy

class PolicyValidationError(Exception):
    def __init__(self, policy_id: str, errors: list[str]):
        self.policy_id = policy_id
        self.errors = errors
        super().__init__(f"Policy '{policy_id}' validation failed: {'; '.join(errors)}")

def _parse_condition(data: dict | list) -> PolicyCondition:
    if isinstance(data, dict):
        if 'all' in data:
            return PolicyCondition(all_=[_parse_condition(c) for c in data['all']])
        elif 'any' in data:
            return PolicyCondition(any_=[_parse_condition(c) for c in data['any']])
        else:
            return PolicyCondition(field=data.get('field'), operator=data.get('operator'), value=data.get('value'))
    raise ValueError("Invalid condition format")

class PolicyLoader:
    def load_from_yaml(self, content: str) -> PolicyDefinition:
        data = yaml.safe_load(content)
        if not data:
            raise ValueError("Empty YAML content")
            
        rules = []
        for r_data in data.get('rules', []):
            condition = _parse_condition(r_data.get('condition', {}))
            rule = PolicyRule(
                id=r_data['id'],
                name=r_data.get('name', ''),
                description=r_data.get('description', ''),
                priority=r_data.get('priority', 0),
                decision=r_data['decision'],
                condition=condition
            )
            rules.append(rule)
            
        policy = PolicyDefinition(
            id=data['id'],
            name=data.get('name', ''),
            version=data.get('version', 1),
            extends=data.get('extends'),
            description=data.get('description', ''),
            rules=rules
        )
        
        errors = validate_policy(policy)
        if errors:
            raise PolicyValidationError(policy.id, errors)
            
        return policy
    
    def load_from_file(self, path: Path) -> PolicyDefinition:
        content = path.read_text()
        return self.load_from_yaml(content)
    
    def load_policies_from_directory(self, directory: Path) -> dict[str, PolicyDefinition]:
        policies = {}
        for file in directory.glob('*.yaml'):
            try:
                policy = self.load_from_file(file)
                policies[policy.id] = policy
            except Exception:
                pass
        return policies
