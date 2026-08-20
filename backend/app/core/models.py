from pydantic import BaseModel, Field, field_validator
from typing import Any, Literal, Optional
from datetime import datetime
import uuid

class ProposedAction(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}
    action_type: Literal["read", "write", "delete", "admin"]
    data_scope_size: int = 1

    @field_validator("tool")
    @classmethod
    def tool_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("tool must be non-empty")
        return v.strip()

    @field_validator("data_scope_size")
    @classmethod
    def data_scope_size_must_be_positive(cls, v: int) -> int:
        if v < 0:
            raise ValueError("data_scope_size must be >= 0")
        return v

class RuntimeContext(BaseModel):
    timestamp: datetime
    user_role: str
    session_data_classification: str
    agent_id: str
    action_type: str
    data_scope_size: int
    previous_violations_in_session: int
    session_id: str
    is_business_hours: bool
    session_status: str = "active"
    human_approval_present: bool = False
    risk_score: int = 0
    risk_level: str = "LOW"
    anomaly_score: int = 0
    anomaly_signals: list[str] = []
    historical_events_count: int = 0
    risk_factors: list[str] = []

class PolicyCondition(BaseModel):
    field: Optional[str] = None
    operator: Optional[str] = None
    value: Any = None
    all_: Optional[list["PolicyCondition"]] = Field(None, alias="all")
    any_: Optional[list["PolicyCondition"]] = Field(None, alias="any")
    model_config = {"populate_by_name": True}

class PolicyRule(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    priority: int = 0
    decision: Literal["ALLOW", "BLOCK", "REQUIRE_HITL", "SUSPEND_SESSION"]
    condition: PolicyCondition

class PolicyDefinition(BaseModel):
    id: str
    name: str = ""
    version: int = 1
    extends: Optional[str] = None
    description: str = ""
    rules: list[PolicyRule] = []

class ResolvedRule(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    priority: int = 0
    decision: str
    condition: PolicyCondition
    source_policy: str

class ResolvedPolicy(BaseModel):
    rules: list[ResolvedRule]
    chain: list[str]
    chain_versions: list[int] = []

class RuleMatch(BaseModel):
    rule_id: str
    rule_name: str = ""
    matched: bool
    source_policy: str
    decision: Optional[str] = None

class EvaluationResult(BaseModel):
    evaluated_rules: list[RuleMatch]
    matched_rules: list[ResolvedRule]

class GovernanceDecision(BaseModel):
    decision: str
    deciding_rule_id: Optional[str] = None
    matched_rules: list[str] = []
    evaluated_rules: list[RuleMatch] = []
    policy_chain: list[str] = []
    explanation: str = ""
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
