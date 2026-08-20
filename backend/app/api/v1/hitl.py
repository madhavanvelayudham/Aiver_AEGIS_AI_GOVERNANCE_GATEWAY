from typing import Any, Optional, List
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.hitl_service import HITLService

router = APIRouter()

# Global HITLService cache
_hitl_service: Optional[HITLService] = None

def get_hitl_service() -> HITLService:
    global _hitl_service
    if _hitl_service is None:
        _hitl_service = HITLService()
    return _hitl_service


# Request Schemas
class HITLResolutionRequest(BaseModel):
    reviewer: str = Field(..., description="Name or identifier of the reviewer.")
    reason: Optional[str] = Field(None, description="Optional notes/reason for approval or denial decision.")


# Response Schemas
class GovernanceDetails(BaseModel):
    decision: str
    explanation: Optional[str] = None


class ToolExecutionDetails(BaseModel):
    executed: bool
    tool: Optional[str] = None
    result: Any = None


class HITLResolutionResponse(BaseModel):
    hitl_request_id: str
    status: str
    governance: Optional[GovernanceDetails] = None
    tool_execution: ToolExecutionDetails


class HITLRequestDetailResponse(BaseModel):
    id: str
    session_id: str
    agent_id: Optional[str]
    audit_event_id: Optional[str]
    proposed_action: Optional[dict]
    runtime_context: Optional[dict]
    policy_version_id: Optional[str]
    status: str
    created_at: str
    expires_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    resolution_reason: Optional[str] = None


class HITLRequestPendingResponse(BaseModel):
    hitl_request_id: str
    session_id: str
    agent_id: Optional[str]
    audit_event_id: Optional[str] = None
    tool: Optional[str] = None       # None when proposed_action is absent; frontend shows 'Unknown tool'
    action_type: Optional[str] = None
    reason: Optional[str]
    created_at: str
    status: str


@router.post(
    "/hitl/{hitl_request_id}/approve",
    response_model=HITLResolutionResponse,
    summary="Approve a pending human-in-the-loop action request",
    description="Loads the HITL request, performs revalidation against current policy/session state, and executes the tool only if ALLOW decision."
)
async def approve_hitl(
    hitl_request_id: str,
    payload: HITLResolutionRequest,
    db: AsyncSession = Depends(get_db),
    service: HITLService = Depends(get_hitl_service)
):
    result = await service.approve_request(
        hitl_request_id=hitl_request_id,
        reviewer=payload.reviewer,
        reason=payload.reason,
        db=db
    )
    return result


@router.post(
    "/hitl/{hitl_request_id}/deny",
    response_model=HITLResolutionResponse,
    summary="Deny a pending human-in-the-loop action request",
    description="Loads the HITL request, updates status to DENIED, and blocks execution of the tool."
)
async def deny_hitl(
    hitl_request_id: str,
    payload: HITLResolutionRequest,
    db: AsyncSession = Depends(get_db),
    service: HITLService = Depends(get_hitl_service)
):
    result = await service.deny_request(
        hitl_request_id=hitl_request_id,
        reviewer=payload.reviewer,
        reason=payload.reason,
        db=db
    )
    return result


@router.get(
    "/hitl/pending",
    response_model=List[HITLRequestPendingResponse],
    summary="List all pending human-in-the-loop review requests",
    description="Retrieves a list of all active HITL requests awaiting human approval."
)
async def list_pending_hitl(
    db: AsyncSession = Depends(get_db),
    service: HITLService = Depends(get_hitl_service)
):
    requests = await service.list_pending(db)
    response_list = []
    for r in requests:
        # Defensive null guard: proposed_action may be None if stored incorrectly
        if r.proposed_action and isinstance(r.proposed_action, dict):
            tool_name = r.proposed_action.get("tool") or None   # None if empty/absent
            action_type = r.proposed_action.get("action_type") or None
        else:
            tool_name = None
            action_type = None
        
        # Load rule explanation from runtime_context or use default description
        rule_desc = "Pending approval"
        if r.runtime_context and isinstance(r.runtime_context, dict):
            rule_desc = "After-hours action requires approval"
            
        response_list.append(
            HITLRequestPendingResponse(
                hitl_request_id=r.id,
                session_id=r.session_id,
                agent_id=r.agent_id,
                audit_event_id=r.audit_event_id,
                tool=tool_name,
                action_type=action_type,
                reason=rule_desc,
                created_at=r.created_at.isoformat(),
                status=r.status
            )
        )
    return response_list


@router.get(
    "/hitl/{hitl_request_id}",
    response_model=HITLRequestDetailResponse,
    summary="Get details of a specific human-in-the-loop request",
    description="Loads all database details for a specific HITL request, with sensitive fields redacted."
)
async def get_hitl_detail(
    hitl_request_id: str,
    db: AsyncSession = Depends(get_db),
    service: HITLService = Depends(get_hitl_service)
):
    r = await service.get_request(hitl_request_id, db)
    if not r:
        from app.services.governance_service import SessionNotFoundError
        raise SessionNotFoundError(f"HITL request with ID '{hitl_request_id}' not found.")
        
    return HITLRequestDetailResponse(
        id=r.id,
        session_id=r.session_id,
        agent_id=r.agent_id,
        audit_event_id=r.audit_event_id,
        proposed_action=r.proposed_action,
        runtime_context=r.runtime_context,
        policy_version_id=r.policy_version_id,
        status=r.status,
        created_at=r.created_at.isoformat(),
        expires_at=r.expires_at.isoformat() if r.expires_at else None,
        reviewed_by=r.reviewed_by,
        reviewed_at=r.reviewed_at.isoformat() if r.reviewed_at else None,
        resolution_reason=r.resolution_reason
    )
