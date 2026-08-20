from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import ProposedAction, GovernanceDecision
from app.llm import LLMProvider, MockLLMProvider, GeminiProvider
from app.tools import ToolRegistry, ToolGateway, registry as default_registry
from app.services.governance_service import GovernanceService, InvalidGovernanceStateError
from app.config import get_settings


class AgentService:
    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        tool_registry: Optional[ToolRegistry] = None,
        governance_service: Optional[GovernanceService] = None
    ):
        self.tool_registry = tool_registry or default_registry
        self.tool_gateway = ToolGateway(self.tool_registry)
        self.governance_service = governance_service or GovernanceService()
        
        # Initialize LLM provider based on settings config
        if llm_provider:
            self.llm_provider = llm_provider
        else:
            settings = get_settings()
            if settings.LLM_PROVIDER == "gemini":
                self.llm_provider = GeminiProvider()
            else:
                self.llm_provider = MockLLMProvider()

    async def chat(
        self,
        session_id: str,
        message: str,
        db: AsyncSession,
        request_id: str,
        llm_provider: Optional[str] = None
    ) -> dict:
        """Runs the agent loop: LLM propose -> validation -> AEGIS govern -> execute tool."""
        # 1. Fetch available tools list to provide as system prompts to LLM
        available_tools = self.tool_registry.get_available_tools()
        
        # Determine effective LLM provider for this request
        active_llm_provider = self.llm_provider
        if llm_provider:
            prov_name = llm_provider.strip().lower()
            if prov_name == "gemini":
                active_llm_provider = GeminiProvider()
            elif prov_name == "mock":
                active_llm_provider = MockLLMProvider()

        # 2. LLM proposes the structured action
        try:
            proposed_action = await active_llm_provider.generate_action(
                user_message=message,
                session_id=session_id,
                available_tools=available_tools
            )
        except ValueError as e:
            raise InvalidGovernanceStateError(f"LLM proposed action parsing/validation failed: {str(e)}")
        
        # 3. Validate ProposedAction (Security boundary: treat LLM output as untrusted user input)
        if not proposed_action.tool or proposed_action.tool.strip() == "":
            raise InvalidGovernanceStateError("LLM proposed action contains an empty tool name.")
        
        tool = self.tool_registry.get_tool(proposed_action.tool)
        if not tool:
            raise InvalidGovernanceStateError(f"Tool '{proposed_action.tool}' proposed by LLM is not registered.")
            
        # Ensure action type matches registry definition
        if proposed_action.action_type != tool["action_type"]:
            raise InvalidGovernanceStateError(
                f"Tool action type mismatch. Expected '{tool['action_type']}', but LLM proposed '{proposed_action.action_type}'."
            )
            
        # 4. AEGIS Governance interception (calls the existing DB-aware evaluate flow)
        decision, audit_event, session = await self.governance_service.evaluate_session_action(
            session_id=session_id,
            proposed_action=proposed_action,
            db=db,
            request_id=request_id
        )
        
        # 5. Controlled tool execution gateway
        executed = False
        tool_result = None
        hitl_info = None
        
        if decision.decision == "ALLOW":
            tool_result = await self.tool_gateway.execute(proposed_action, "ALLOW")
            executed = True
        elif decision.decision == "REQUIRE_HITL":
            from app.services.hitl_service import HITLService
            hitl_svc = HITLService()
            hitl_req = await hitl_svc.create_hitl_request(
                session_id=session.id,
                agent_id=session.agent_id,
                proposed_action=proposed_action,
                runtime_context=audit_event.runtime_context,
                policy_version_id=audit_event.policy_version_id,
                audit_event_id=audit_event.id,
                db=db
            )
            hitl_info = {
                "request_id": hitl_req.id,
                "status": "PENDING"
            }
            
        # 6. Construct and return response
        res = {
            "request_id": request_id,
            "audit_event_id": audit_event.id,
            "message": message,
            "proposed_action": proposed_action.model_dump(),
            "governance": {
                "decision": decision.decision,
                "matched_rules": decision.matched_rules,
                "explanation": decision.explanation
            },
            "tool_execution": {
                "executed": executed,
                "tool": proposed_action.tool,
                "result": tool_result
            }
        }
        if hitl_info:
            res["hitl"] = hitl_info
        return res
