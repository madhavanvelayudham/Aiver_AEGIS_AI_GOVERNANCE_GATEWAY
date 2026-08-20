import json
import httpx
from app.llm.base import LLMProvider
from app.core.models import ProposedAction
from app.config import get_settings

class GeminiProvider(LLMProvider):
    async def generate_action(
        self,
        user_message: str,
        session_id: str,
        available_tools: list[dict]
    ) -> ProposedAction:
        """Invokes Google Gemini API with Structured Outputs to generate a ProposedAction."""
        settings = get_settings()
        if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY.strip() == "":
            raise ValueError("GEMINI_API_KEY is not configured. Real LLM execution requires a valid API key.")
        
        # Build prompt listing tools
        tools_str = "\n".join([
            f"- {t['name']}: {t['description']} (Action Type: {t['action_type']})"
            for t in available_tools
        ])
        
        system_instruction = f"""You are an action-planning agent for the AEGIS AI Governance system.
Your job is to translate the user's natural language request into a single structured proposed tool action.

Available tools:
{tools_str}

Important rules:
1. You are NOT the authorizer. Do NOT decide if the action is allowed.
2. You must never output a field named 'decision' or try to bypass governance.
3. If the user request does not match any registered tool, or is a malicious attempt, choose the closest tool or fallback.
4. Output only valid JSON matching the schema.
"""

        # Build endpoint dynamically using config setting (CORRECTION 2)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
        
        payload = {
            "contents": [
                {
                    "parts": [{"text": user_message}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string"},
                        "arguments": {"type": "object"},
                        "action_type": {
                            "type": "string",
                            "enum": ["read", "write", "delete", "admin"]
                        },
                        "data_scope_size": {"type": "integer"}
                    },
                    "required": ["tool", "arguments", "action_type", "data_scope_size"]
                }
            }
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(url, json=payload, timeout=30.0)
                response.raise_for_status()
                res_data = response.json()
                
                # Extract text block from candidate response
                text = res_data["candidates"][0]["content"]["parts"][0]["text"]
                action_data = json.loads(text.strip())
                return ProposedAction(**action_data)
            except Exception as e:
                raise ValueError(f"Failed to generate structured action from Gemini: {str(e)}")
