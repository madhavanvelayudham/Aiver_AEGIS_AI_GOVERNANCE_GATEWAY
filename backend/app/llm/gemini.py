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
        
        # Build prompt listing tools with required arguments
        tools_info = []
        for t in available_tools:
            req_args = t.get("required_args", [])
            args_desc = ", ".join(req_args) if req_args else "none"
            tools_info.append(
                f"- {t['name']}: {t['description']} (Action Type: {t['action_type']}, Required Arguments: {args_desc})"
            )
        tools_str = "\n".join(tools_info)
        
        system_instruction = f"""You are an action-planning agent for the AEGIS AI Governance system.
Your job is to translate the user's natural language request into a single structured proposed tool action.

Available tools and their required arguments:
{tools_str}

Important rules:
1. You are NOT the authorizer. Do NOT decide if the action is allowed.
2. You must never output a field named 'decision' or try to bypass governance.
3. You MUST extract non-empty string values for all required arguments of the selected tool from the user message.
   - For 'read_patient': required argument 'patient_id' (e.g. 'P101').
   - For 'update_patient': required arguments 'patient_id' (e.g. 'P101') AND 'notes' (e.g. description of updates requested).
   - For 'search_customer': required argument 'query' (e.g. search keywords).
   - For 'delete_customer': required argument 'customer_id' (e.g. 'C101' or 'C500').
4. The 'arguments' JSON object MUST contain all required argument keys with valid non-empty string values.
5. If the user request does not specify explicit arguments, extract or infer non-empty arguments directly from the user message context.
"""

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
                        "arguments": {
                            "type": "object",
                            "properties": {
                                "patient_id": {"type": "string"},
                                "notes": {"type": "string"},
                                "query": {"type": "string"},
                                "customer_id": {"type": "string"}
                            }
                        },
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
        
        action_data = None
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=30.0)
                if response.status_code == 429:
                    raise ValueError("Gemini provider is temporarily rate-limited. Please retry shortly.")
                if response.status_code != 200:
                    raise ValueError(f"Gemini API returned HTTP status {response.status_code}.")
                
                res_data = response.json()
                candidates = res_data.get("candidates", [])
                if not candidates or "content" not in candidates[0]:
                    raise ValueError("Gemini returned an empty candidate response.")
                    
                text = candidates[0]["content"]["parts"][0]["text"]
                action_data = json.loads(text.strip())
        except ValueError as ve:
            raise ve
        except Exception as e:
            # Clean sanitized error message with zero API key exposure
            raise ValueError("Failed to generate structured action from Gemini provider.")
            
        action = ProposedAction(**action_data)

        # Validate ProposedAction arguments for known tools (strictly reject missing required arguments)
        tool_map = {t["name"]: t for t in available_tools}
        if action.tool in tool_map:
            t_info = tool_map[action.tool]
            req_args = t_info.get("required_args", [])
            if not isinstance(action.arguments, dict):
                raise ValueError(f"LLM proposed action arguments for '{action.tool}' must be a dictionary.")
                
            missing_args = [arg for arg in req_args if not action.arguments.get(arg)]
            if missing_args:
                raise ValueError(f"LLM proposed tool '{action.tool}' missing required arguments: {', '.join(missing_args)}.")
                    
            # Ensure action_type matches registered tool action_type
            if t_info.get("action_type") and action.action_type != t_info["action_type"]:
                action.action_type = t_info["action_type"]

        return action
