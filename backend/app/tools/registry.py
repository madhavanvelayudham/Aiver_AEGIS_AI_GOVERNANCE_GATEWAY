from typing import Callable, Optional

# Mock tool implementations
def mock_read_patient(patient_id: str) -> dict:
    return {
        "status": "success",
        "tool": "read_patient",
        "data": {
            "patient_id": patient_id,
            "name": "Jane Doe",
            "age": 34,
            "diagnosis": "Healthy Recovery",
            "classification": "PHI"
        }
    }

def mock_update_patient(patient_id: str, notes: str) -> dict:
    return {
        "status": "success",
        "tool": "update_patient",
        "data": {
            "patient_id": patient_id,
            "updated_at": "2026-08-19T23:17:00",
            "notes": notes,
            "status": "record_updated"
        }
    }

def mock_search_customer(query: str) -> dict:
    return {
        "status": "success",
        "tool": "search_customer",
        "data": {
            "query": query,
            "results": [
                {"customer_id": "C101", "name": "Aivar Innovations", "tier": "Enterprise"},
                {"customer_id": "C102", "name": "Aegis Ltd", "tier": "Premium"}
            ]
        }
    }

def mock_delete_customer(customer_id: str) -> dict:
    return {
        "status": "success",
        "tool": "delete_customer",
        "data": {
            "customer_id": customer_id,
            "status": "deleted"
        }
    }


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name: str, description: str, action_type: str, func: Callable):
        self._tools[name] = {
            "name": name,
            "description": description,
            "action_type": action_type,
            "func": func
        }

    def get_tool(self, name: str) -> Optional[dict]:
        return self._tools.get(name)

    def get_available_tools(self) -> list[dict]:
        return list(self._tools.values())


# Singleton instance
registry = ToolRegistry()

# Register default mock tools
registry.register(
    name="read_patient",
    description="Retrieve medical chart details for a specific patient ID (restricted to PHI medical staff).",
    action_type="read",
    func=mock_read_patient
)

registry.register(
    name="update_patient",
    description="Update notes on a patient medical chart chart (requires write clearance).",
    action_type="write",
    func=mock_update_patient
)

registry.register(
    name="search_customer",
    description="Search database records for customer name or query query.",
    action_type="read",
    func=mock_search_customer
)

registry.register(
    name="delete_customer",
    description="Delete customer billing account record by customer ID (admin only).",
    action_type="delete",
    func=mock_delete_customer
)
