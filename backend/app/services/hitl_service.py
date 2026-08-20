import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import HITLRequestModel, SessionModel
from app.core.models import ProposedAction, RuntimeContext
from app.services.governance_service import InvalidGovernanceStateError, SessionNotFoundError

def _sanitize_arguments(args: dict) -> dict:
    if not args:
        return args
    sanitized = {}
    for k, v in args.items():
        if any(term in k.lower() for term in ["password", "secret", "token", "key", "ssn"]):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_arguments(v)
        else:
            sanitized[k] = v
    return sanitized

def _sanitize_proposed_action(action_dict: dict) -> dict:
    if not action_dict:
        return action_dict
    sanitized = dict(action_dict)
    if "arguments" in sanitized:
        sanitized["arguments"] = _sanitize_arguments(sanitized["arguments"])
    return sanitized


class HITLService:
    async def create_hitl_request(
        self,
        session_id: str,
        agent_id: str,
        proposed_action: ProposedAction,
        runtime_context: dict,
        policy_version_id: Optional[str],
        audit_event_id: str,
        db: AsyncSession
    ) -> HITLRequestModel:
        """Creates a new pending HITL request in the database with sanitized arguments."""
        sanitized_action = proposed_action.model_dump()
        sanitized_action["arguments"] = _sanitize_arguments(proposed_action.arguments)
        
        hitl_request = HITLRequestModel(
            id=str(uuid.uuid4()),
            session_id=session_id,
            agent_id=agent_id,
            audit_event_id=audit_event_id,
            proposed_action=sanitized_action,
            runtime_context=runtime_context,
            policy_version_id=policy_version_id,
            status="PENDING",
            created_at=datetime.utcnow()
        )
        db.add(hitl_request)
        await db.commit()
        return hitl_request

    async def approve_request(
        self,
        hitl_request_id: str,
        reviewer: str,
        reason: Optional[str],
        db: AsyncSession
    ) -> dict:
        """
        Performs scoped revalidation and atomic approval.

        The approval is scoped: 'human_approval_present=True' tells the governance
        engine that THIS EXACT request has been human-reviewed. It does NOT create a
        global bypass — higher-priority BLOCK or SUSPEND_SESSION rules still apply.

        Revalidation flow:
          1. Load HITL request (must be PENDING).
          2. Re-evaluate the exact proposed action against current session state.
          3. If result is REQUIRE_HITL AND human_approval_present=True → treat as ALLOW
             (human review was the reason for HITL, and approval was granted).
          4. If result is BLOCK or SUSPEND_SESSION → transition to DENIED (higher rule applies).
          5. If result is ALLOW → execute ToolGateway.
          6. Verify DB state change via SELECT (not rowcount, which is unreliable on async SQLite).
        """
        # 1. Load HITL request
        stmt_select = select(HITLRequestModel).where(HITLRequestModel.id == hitl_request_id)
        res_select = await db.execute(stmt_select)
        hitl_request = res_select.scalar_one_or_none()
        
        if not hitl_request:
            raise SessionNotFoundError(f"HITL request with ID '{hitl_request_id}' not found.")
            
        if hitl_request.status != "PENDING":
            raise InvalidGovernanceStateError("HITL request has already been resolved.")
            
        # 2. Revalidate current AEGIS state with human_approval_present=True (scoped to this request)
        from app.api.v1.governance import get_governance_service
        gov_service = get_governance_service()
        proposed_action = ProposedAction(**hitl_request.proposed_action)
        
        decision_val = None
        reval_reason = None
        try:
            # human_approval_present=True is passed to RuntimeContext so policy rules CAN check it.
            # It does NOT bypass BLOCK or SUSPEND_SESSION rules — those have higher priority.
            decision, audit_event, session = await gov_service.evaluate_session_action(
                session_id=hitl_request.session_id,
                proposed_action=proposed_action,
                db=db,
                request_id=str(uuid.uuid4()),
                human_approval_present=True
            )
            decision_val = decision.decision
            reval_reason = decision.explanation
        except Exception as e:
            decision_val = "BLOCK"
            reval_reason = f"Revalidation error: {str(e)}"
            
        # 3. Determine effective approval outcome:
        #    - ALLOW → approved, execute tool
        #    - REQUIRE_HITL + human_approval_present → the original HITL was approved by human,
        #      so this counts as ALLOW for this exact request
        #    - BLOCK or SUSPEND_SESSION → higher-priority rule applies, deny
        effective_allow = decision_val == "ALLOW" or decision_val == "REQUIRE_HITL"
            
        # 4. Atomically update status
        new_status = "APPROVED" if effective_allow else "DENIED"
        resolution_note = (
            reason or "Approved by human reviewer."
            if effective_allow
            else f"Revalidation blocked. Decision: {decision_val}. Reason: {reval_reason}"
        )
        
        stmt = (
            update(HITLRequestModel)
            .where(HITLRequestModel.id == hitl_request_id, HITLRequestModel.status == "PENDING")
            .values(
                status=new_status,
                reviewed_by=reviewer,
                reviewed_at=datetime.utcnow(),
                resolution_reason=resolution_note
            )
        )
        await db.execute(stmt)
        await db.commit()

        # 5. SELECT to verify status actually changed (rowcount unreliable on async SQLite)
        stmt_verify = select(HITLRequestModel.status).where(HITLRequestModel.id == hitl_request_id)
        res_verify = await db.execute(stmt_verify)
        verified_status = res_verify.scalar_one_or_none()
        
        if verified_status != new_status:
            raise InvalidGovernanceStateError(
                f"HITL request '{hitl_request_id}' status change did not persist. "
                f"Expected '{new_status}', found '{verified_status}'. "
                "Request may have been resolved concurrently."
            )
            
        if not effective_allow:
            return {
                "hitl_request_id": hitl_request_id,
                "status": "DENIED",
                "governance": {
                    "decision": decision_val,
                    "explanation": reval_reason
                },
                "tool_execution": {
                    "executed": False
                }
            }
            
        # 6. Execute ToolGateway (zero locks held at this point)
        from app.tools import ToolGateway, registry as default_registry
        gateway = ToolGateway(default_registry)
        tool_result = await gateway.execute(proposed_action, "ALLOW")
        
        return {
            "hitl_request_id": hitl_request_id,
            "status": "APPROVED",
            "governance": {
                "decision": "ALLOW"
            },
            "tool_execution": {
                "executed": True,
                "tool": proposed_action.tool,
                "result": tool_result
            }
        }

    async def deny_request(
        self,
        hitl_request_id: str,
        reviewer: str,
        reason: Optional[str],
        db: AsyncSession
    ) -> dict:
        """Atomically transitions status to DENIED, verified via SELECT."""
        stmt_select = select(HITLRequestModel).where(HITLRequestModel.id == hitl_request_id)
        res_select = await db.execute(stmt_select)
        hitl_request = res_select.scalar_one_or_none()
        
        if not hitl_request:
            raise SessionNotFoundError(f"HITL request with ID '{hitl_request_id}' not found.")
            
        if hitl_request.status != "PENDING":
            raise InvalidGovernanceStateError("HITL request has already been resolved.")
            
        stmt = (
            update(HITLRequestModel)
            .where(HITLRequestModel.id == hitl_request_id, HITLRequestModel.status == "PENDING")
            .values(
                status="DENIED",
                reviewed_by=reviewer,
                reviewed_at=datetime.utcnow(),
                resolution_reason=reason or "Denied by human reviewer."
            )
        )
        await db.execute(stmt)
        await db.commit()
        
        # SELECT to verify status change (rowcount is unreliable on async SQLite)
        stmt_verify = select(HITLRequestModel.status).where(HITLRequestModel.id == hitl_request_id)
        res_verify = await db.execute(stmt_verify)
        verified_status = res_verify.scalar_one_or_none()
        
        if verified_status != "DENIED":
            raise InvalidGovernanceStateError(
                f"HITL request '{hitl_request_id}' status change did not persist. "
                f"Expected 'DENIED', found '{verified_status}'. "
                "Request may have been resolved concurrently."
            )
            
        return {
            "hitl_request_id": hitl_request_id,
            "status": "DENIED",
            "tool_execution": {
                "executed": False
            }
        }

    async def get_request(self, hitl_request_id: str, db: AsyncSession) -> Optional[HITLRequestModel]:
        stmt = select(HITLRequestModel).where(HITLRequestModel.id == hitl_request_id)
        res = await db.execute(stmt)
        req = res.scalar_one_or_none()
        if req and req.proposed_action:
            req.proposed_action = _sanitize_proposed_action(req.proposed_action)
        return req

    async def list_pending(self, db: AsyncSession) -> list[HITLRequestModel]:
        stmt = select(HITLRequestModel).where(HITLRequestModel.status == "PENDING").order_by(HITLRequestModel.created_at.desc())
        res = await db.execute(stmt)
        requests = res.scalars().all()
        for r in requests:
            if r.proposed_action:
                r.proposed_action = _sanitize_proposed_action(r.proposed_action)
        return list(requests)
