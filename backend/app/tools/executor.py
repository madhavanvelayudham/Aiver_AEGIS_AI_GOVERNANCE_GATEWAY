import asyncio
from typing import Any
from app.core.models import ProposedAction
from app.tools.registry import ToolRegistry

class ToolExecutionDenied(Exception):
    """Exception raised when a tool is executed without an explicit ALLOW decision."""
    pass


class ToolGateway:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    async def execute(self, action: ProposedAction, decision: str) -> Any:
        """Executes the registered tool (CORRECTION 1: enforce secure authorization check)."""
        # Ensure authorization boundary check is a runtime exception rather than a Python assert
        if decision != "ALLOW":
            raise ToolExecutionDenied(
                f"Tool execution blocked. Required governance decision is 'ALLOW', but received '{decision}'."
            )
        
        tool = self.registry.get_tool(action.tool)
        if not tool:
            raise ValueError(f"Tool '{action.tool}' is not registered in the gateway.")
        
        # Invoke mock function
        func = tool["func"]
        if asyncio.iscoroutinefunction(func):
            return await func(**action.arguments)
        
        # Sync execution fallback
        return func(**action.arguments)
