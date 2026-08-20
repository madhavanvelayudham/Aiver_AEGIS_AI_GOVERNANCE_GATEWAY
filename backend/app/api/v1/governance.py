import uuid
from datetime import datetime
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import ProposedAction, RuleMatch
from app.db.database import get_db
from app.db.models import PolicyVersionModel
from app.services.governance_service import GovernanceService

router = APIRouter()

# Global service instance cache
_governance_service: Optional[GovernanceService] = None

def get_governance_service() -> GovernanceService:
    global _governance_service
    if _governance_service is None:
        _governance_service = GovernanceService()
        policy_dir = Path("D:/AIver_One_day/policies")
        _governance_service.load_policies_from_directory(policy_dir)
    return _governance_service


class EvaluationRequest(BaseModel):
    session_id: str = Field(..., description="Unique session ID to evaluate the action against.")
    action: ProposedAction = Field(..., description="The proposed tool action details.")


class EvaluationResponse(BaseModel):
    request_id: str = Field(..., description="Authoritative UUID generated for this request.")
    audit_event_id: str = Field(..., description="Primary key of the AuditEventModel record for this exact request.")
    session_id: str = Field(..., description="ID of the evaluation session.")
    agent_id: str = Field(..., description="ID of the agent initiating the action.")
    decision: str = Field(..., description="Final governance decision (ALLOW, BLOCK, REQUIRE_HITL, SUSPEND_SESSION).")
    matched_rules: list[str] = Field(..., description="IDs of rules that matched.")
    evaluated_rules: list[RuleMatch] = Field(..., description="Complete log of evaluated rules and matching status.")
    policy_chain: list[str] = Field(..., description="Policy inheritance chain resolved.")
    deciding_rule_id: Optional[str] = Field(None, description="The rule ID that determined the final decision.")
    explanation: str = Field(..., description="Explanation generated for this decision.")
    policy_version: int = Field(..., description="Version of the active policy used.")
    violation_count: int = Field(..., description="Server-derived count of violations after this request.")
    session_status: str = Field(..., description="State of the session after this request (active or suspended).")
    timestamp: datetime = Field(..., description="Server timestamp when action was processed.")


@router.post(
    "/governance/evaluate",
    response_model=EvaluationResponse,
    summary="Evaluate proposed action against active policy",
    description="Evaluates a proposed action against the session context and active policy rules, logs an audit trail, and increments violations."
)
async def evaluate_action(
    request: EvaluationRequest,
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service)
):
    request_id = str(uuid.uuid4())
    
    # Delegate database actions, context building, and rule evaluation to transport-independent service layer
    decision, audit_event, session = await service.evaluate_session_action(
        session_id=request.session_id,
        proposed_action=request.action,
        db=db,
        request_id=request_id
    )
    
    # Retrieve version number for target policy
    target_policy = session.active_policy_id or "base_policy"
    stmt_ver = select(PolicyVersionModel.version).where(
        PolicyVersionModel.policy_id == target_policy,
        PolicyVersionModel.status == "active"
    ).order_by(PolicyVersionModel.version.desc())
    res_ver = await db.execute(stmt_ver)
    version = res_ver.scalar() or 1
    
    return EvaluationResponse(
        request_id=request_id,
        audit_event_id=audit_event.id,
        session_id=session.id,
        agent_id=session.agent_id,
        decision=decision.decision,
        matched_rules=decision.matched_rules,
        evaluated_rules=decision.evaluated_rules,
        policy_chain=decision.policy_chain,
        deciding_rule_id=decision.deciding_rule_id,
        explanation=decision.explanation,
        policy_version=version,
        violation_count=session.previous_violations,
        session_status=session.status,
        timestamp=audit_event.created_at
    )


# Administrative Response Schemas for Dashboard
class AuditEventResponse(BaseModel):
    id: str
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    agent_id: Optional[str] = None
    action_type: Optional[str] = None
    tool_name: Optional[str] = None
    proposed_action: Optional[dict] = None
    runtime_context: Optional[dict] = None
    policy_version_id: Optional[str] = None
    policy_chain: Optional[list[str]] = None
    evaluated_rules: Optional[list[dict]] = None
    matched_rules: Optional[list[str]] = None
    decision: Optional[str] = None
    deciding_rule_id: Optional[str] = None
    explanation: Optional[str] = None
    created_at: datetime


class SessionResponse(BaseModel):
    id: str
    agent_id: str
    user_role: str
    data_classification: str
    active_policy_id: Optional[str] = None
    previous_violations: int
    is_business_hours: Optional[bool] = None
    status: str
    created_at: datetime


class PolicyVersionResponse(BaseModel):
    policy_id: str
    version: int
    yaml_content: str
    parsed_rules: Optional[list] = None


class MetricsResponse(BaseModel):
    total_requests: int
    decision_counts: dict[str, int]
    session_counts: dict[str, int]


@router.get(
    "/governance/audit_events",
    response_model=list[AuditEventResponse],
    summary="Get recent governance audit logs",
    description="Retrieves the log of decisions and matches processed by the AEGIS engine."
)
async def get_audit_events(
    limit: int = Query(50, description="Max number of events to load."),
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service)
):
    events = await service.get_audit_events(db, limit)
    return events


@router.get(
    "/governance/audit_events/{event_id}",
    response_model=AuditEventResponse,
    summary="Get a single governance audit event by primary key",
    description="Fetches the exact AuditEvent record by its UUID primary key. Use this for precise event-to-inspector correlation without session_id ambiguity."
)
async def get_audit_event_by_id(
    event_id: str,
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service)
):
    from app.db.models import AuditEventModel
    from sqlalchemy import select as sa_select
    stmt = sa_select(AuditEventModel).where(AuditEventModel.id == event_id)
    res = await db.execute(stmt)
    event = res.scalar_one_or_none()
    if not event:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Audit event '{event_id}' not found.")
    # Apply same sanitization as list endpoint
    if event.proposed_action:
        from app.services.governance_service import _sanitize_arguments
        sanitized = dict(event.proposed_action)
        if "arguments" in sanitized:
            sanitized["arguments"] = _sanitize_arguments(sanitized["arguments"])
        event.proposed_action = sanitized
    return event


@router.get(
    "/governance/sessions",
    response_model=list[SessionResponse],
    summary="Get list of all sessions",
    description="Retrieves details and status indicators for all sessions."
)
async def get_sessions(
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service)
):
    sessions = await service.get_sessions(db)
    return sessions


@router.get(
    "/governance/policies",
    response_model=list[PolicyVersionResponse],
    summary="Get loaded policies active configurations",
    description="Lists all loaded policy files and active versions."
)
async def get_policies(
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service)
):
    policies = await service.get_policies(db)
    return policies


@router.get(
    "/governance/metrics",
    response_model=MetricsResponse,
    summary="Get general system performance metrics",
    description="Aggregates transaction and violation statistics."
)
async def get_metrics(
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service)
):
    metrics = await service.get_metrics(db)
    return metrics


class CreateSessionRequest(BaseModel):
    session_id: str
    user_role: str
    data_classification: str
    previous_violations: Optional[int] = None
    is_business_hours: Optional[bool] = None
    status: Optional[str] = None


@router.post(
    "/governance/sessions",
    response_model=SessionResponse,
    summary="Create or seed a custom session",
    description="Creates a new session record in the database for policy testing."
)
async def create_session(
    request: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    service: GovernanceService = Depends(get_governance_service)
):
    sess = await service.create_session(
        session_id=request.session_id,
        user_role=request.user_role,
        data_classification=request.data_classification,
        db=db,
        previous_violations=request.previous_violations,
        is_business_hours=request.is_business_hours,
        status=request.status
    )
    return sess

