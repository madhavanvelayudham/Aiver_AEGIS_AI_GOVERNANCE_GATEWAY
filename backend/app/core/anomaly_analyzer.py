from pydantic import BaseModel
from typing import List, Dict, Any
from app.core.models import ProposedAction

class AnomalyAssessment(BaseModel):
    anomaly_score: int
    signals: list[str]


class BehavioralAnomalyAnalyzer:
    def analyze(self, history: List[Dict[str, Any]], current_action: ProposedAction) -> AnomalyAssessment:
        """Lightweight deterministic session behavior sequence anomaly analyzer."""
        signals = []
        score = 0

        # 1. Insufficient history check (safe default)
        if len(history) < 3:
            return AnomalyAssessment(
                anomaly_score=0,
                signals=["Insufficient history for behavioral analysis (defaulting to zero anomaly score)"]
            )

        total_count = len(history)
        historical_action_types = [h.get("action_type", "") for h in history]
        historical_tools = [h.get("tool", "") for h in history]

        proposed_action_type = current_action.action_type
        proposed_tool = current_action.tool

        # 2. Action Novelty check
        is_novel_action = proposed_action_type not in historical_action_types
        if is_novel_action:
            if proposed_action_type == "delete":
                score += 40
                signals.append("First-time delete action type executed in session (+40)")
            elif proposed_action_type in ("write", "update"):
                score += 25
                signals.append("First-time write action type executed in session (+25)")
            else:
                score += 15
                signals.append(f"Novel action type '{proposed_action_type}' in session (+15)")

        # 3. Tool Novelty check
        is_novel_tool = proposed_tool not in historical_tools
        if is_novel_tool:
            score += 20
            signals.append(f"Novel tool access in session: '{proposed_tool}' (+20)")

        # 4. Sequence Deviation (e.g. read-only pattern to modifying pattern)
        all_reads_in_history = all(act in ("read", "search") for act in historical_action_types)
        if all_reads_in_history:
            if proposed_action_type == "delete":
                score += 40
                signals.append("Critical sequence deviation: transition from read-only history to delete operation (+40)")
            elif proposed_action_type in ("write", "update"):
                score += 20
                signals.append("Sequence deviation: write operation proposed after read-only session history (+20)")

        # 5. Frequency of action type (if not novel)
        if not is_novel_action:
            count_matching = historical_action_types.count(proposed_action_type)
            ratio = count_matching / total_count
            if ratio < 0.25:
                score += 15
                signals.append(f"Rare action type execution: '{proposed_action_type}' has <25% frequency in session history (+15)")

        # 6. Frequency of tool (if not novel)
        if not is_novel_tool:
            count_tool_matching = historical_tools.count(proposed_tool)
            tool_ratio = count_tool_matching / total_count
            if tool_ratio < 0.20:
                score += 10
                signals.append(f"Rare tool execution: '{proposed_tool}' has <20% frequency in session history (+10)")

        # 7. Normalize final anomaly score to 0-100 range
        normalized_score = min(100, max(0, score))
        if not signals:
            signals.append("Action matches established session behavioral pattern.")

        return AnomalyAssessment(
            anomaly_score=normalized_score,
            signals=signals
        )
