import uuid
from typing import Any, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.agent.agent_service import AgentService

router = APIRouter()

from app.api.v1.governance import get_governance_service

def get_agent_service(gov_service=Depends(get_governance_service)) -> AgentService:
    return AgentService(governance_service=gov_service)


class AgentChatRequest(BaseModel):
    session_id: str = Field(..., description="The session ID associated with this chat.")
    message: str = Field(..., description="The message sent to the agent.")
    llm_provider: Optional[str] = Field(None, description="Optional LLM provider override ('mock' or 'gemini').")


class ProposedActionInfo(BaseModel):
    tool: str
    arguments: dict
    action_type: str
    data_scope_size: int


class GovernanceInfo(BaseModel):
    decision: str
    matched_rules: list[str]
    explanation: str


class ToolExecutionInfo(BaseModel):
    executed: bool
    tool: Optional[str] = None
    result: Any = None


class HitlInfo(BaseModel):
    request_id: str
    status: str


class AgentChatResponse(BaseModel):
    request_id: str
    audit_event_id: str = Field(..., description="Primary key of the AuditEventModel record for exact correlation.")
    message: str
    proposed_action: ProposedActionInfo
    governance: GovernanceInfo
    hitl: Optional[HitlInfo] = None
    tool_execution: ToolExecutionInfo


@router.post(
    "/agent/chat",
    response_model=AgentChatResponse,
    summary="Send a chat message to the agent under AEGIS governance",
    description="Translates the user query to a proposed action, routes it through AEGIS governance evaluation, and executes the tool if allowed."
)
async def agent_chat(
    request: AgentChatRequest,
    db: AsyncSession = Depends(get_db),
    service: AgentService = Depends(get_agent_service)
):
    request_id = str(uuid.uuid4())
    result = await service.chat(
        session_id=request.session_id,
        message=request.message,
        db=db,
        request_id=request_id,
        llm_provider=request.llm_provider
    )
    return result
