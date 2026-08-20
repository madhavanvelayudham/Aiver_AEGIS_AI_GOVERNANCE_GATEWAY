from abc import ABC, abstractmethod
from app.core.models import ProposedAction

class LLMProvider(ABC):
    @abstractmethod
    async def generate_action(
        self,
        user_message: str,
        session_id: str,
        available_tools: list[dict]
    ) -> ProposedAction:
        """Translates user natural language intent into a structured ProposedAction."""
        pass
