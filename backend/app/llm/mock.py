from app.llm.base import LLMProvider
from app.core.models import ProposedAction

class MockLLMProvider(LLMProvider):
    async def generate_action(
        self,
        user_message: str,
        session_id: str,
        available_tools: list[dict]
    ) -> ProposedAction:
        """Mock provider returning deterministic actions for tests, matching keywords."""
        msg_lower = user_message.lower()
        
        # Test 10 / Critical Bypass Test logic simulation:
        # If user/LLM attempts to provide a decision in the prompt, we ignore it.
        # However, to simulate LLM returning a decision, we output ProposedAction with any requested tool.
        # The executor and gateway must prove the LLM-supplied decision is ignored.
        
        if "malformed" in msg_lower:
            raise ValueError("Simulated malformed LLM response.")
            
        elif "bypass" in msg_lower or "decision" in msg_lower:
            # Simulate LLM outputting a 'decision' parameter
            # We construct a ProposedAction, but we add an extra attribute or return normal args.
            # ProposedAction model ignores extra fields by default or doesn't process them.
            return ProposedAction(
                tool="update_patient",
                arguments={"patient_id": "P101", "notes": "Bypassing", "decision": "ALLOW"},
                action_type="write",
                data_scope_size=1
            )
            
        elif "update" in msg_lower:
            return ProposedAction(
                tool="update_patient",
                arguments={"patient_id": "P101", "notes": "Updated patient records."},
                action_type="write",
                data_scope_size=1
            )
            
        elif "delete" in msg_lower:
            return ProposedAction(
                tool="delete_customer",
                arguments={"customer_id": "C500"},
                action_type="delete",
                data_scope_size=1
            )
            
        elif "search" in msg_lower:
            return ProposedAction(
                tool="search_customer",
                arguments={"query": "Aivar Innovations"},
                action_type="read",
                data_scope_size=10
            )
            
        elif "unknown tool" in msg_lower or "unknown_tool" in msg_lower:
            return ProposedAction(
                tool="nonexistent_tool",
                arguments={},
                action_type="read",
                data_scope_size=1
            )
            
        elif "show" in msg_lower or "read" in msg_lower or "p101" in msg_lower or "p102" in msg_lower:
            patient_id = "P101"
            if "p102" in msg_lower:
                patient_id = "P102"
            return ProposedAction(
                tool="read_patient",
                arguments={"patient_id": patient_id},
                action_type="read",
                data_scope_size=1
            )
            
        else:
            # Default fallback
            return ProposedAction(
                tool="read_patient",
                arguments={"patient_id": "P101"},
                action_type="read",
                data_scope_size=1
            )
