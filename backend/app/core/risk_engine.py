from pydantic import BaseModel
from typing import List, Optional
from app.core.models import ProposedAction, RuntimeContext

class RiskAssessment(BaseModel):
    risk_score: int
    risk_level: str
    risk_factors: list[str]


class RiskEngine:
    def assess(
        self,
        action: ProposedAction,
        user_role: str,
        session_data_classification: str,
        previous_violations: int,
        is_business_hours: bool,
        data_scope_size: int,
        anomaly_score: int = 0
    ) -> RiskAssessment:
        """Deterministically evaluates the risk score, level, and explainable risk factors."""
        score = 0
        factors = []

        # 1. Action type base risk
        action_type = action.action_type
        if action_type in ("read", "search"):
            score += 10
            factors.append("Low-risk search or read operation (+10)")
        elif action_type in ("write", "update"):
            score += 25
            factors.append("Medium-risk write or update operation (+25)")
        elif action_type in ("delete", "admin"):
            score += 50
            factors.append("High-risk delete or admin operation (+50)")
        else:
            score += 10
            factors.append("Default action base risk (+10)")

        # 2. Data classification sensitivity
        data_class = session_data_classification.lower() if session_data_classification else "public"
        if data_class == "phi":
            score += 20
            factors.append("Sensitive PHI data classification access (+20)")
        elif data_class == "internal":
            score += 10
            factors.append("Internal data classification access (+10)")

        # 3. Destructive operation penalty
        tool_name = action.tool.lower() if action.tool else ""
        if action_type == "delete" or "delete" in tool_name or "drop" in tool_name:
            score += 20
            factors.append("Destructive write or delete tool proposed (+20)")

        # 4. After-hours penalty
        if not is_business_hours:
            score += 10
            factors.append("Action requested outside standard business hours (+10)")

        # 5. Previous session violations (bounded at 15 points)
        violation_penalty = min(15, previous_violations * 5)
        if violation_penalty > 0:
            factors.append(f"Elevated risk due to previous session violations (+{violation_penalty})")
        score += violation_penalty

        # 6. Large data scope size penalty
        if data_scope_size > 100:
            score += 10
            factors.append(f"Large data scope size: {data_scope_size} records (+10)")

        # 7. Behavioral anomaly signal penalty (bounded at 15 points)
        anomaly_penalty = min(15, int(anomaly_score * 0.15))
        if anomaly_penalty > 0:
            factors.append(f"Elevated risk from behavioral sequence anomalies (+{anomaly_penalty})")
        score += anomaly_penalty

        # 8. Bounds check normalization
        normalized_score = min(100, max(0, score))

        # 9. Risk Level mapping
        if normalized_score < 30:
            level = "LOW"
        elif normalized_score < 60:
            level = "MEDIUM"
        elif normalized_score < 85:
            level = "HIGH"
        else:
            level = "CRITICAL"

        return RiskAssessment(
            risk_score=normalized_score,
            risk_level=level,
            risk_factors=factors
        )
