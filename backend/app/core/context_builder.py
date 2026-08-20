from datetime import datetime, time
from app.core.models import RuntimeContext, ProposedAction
from app.config import get_settings

class ContextBuilder:
    def build_from_session(
        self,
        session_id: str,
        agent_id: str,
        user_role: str,
        data_classification: str,
        previous_violations: int,
        session_status: str,
        proposed_action: ProposedAction,
        timestamp: datetime | None = None,
        human_approval_present: bool = False,
        risk_score: int = 0,
        risk_level: str = "LOW",
        anomaly_score: int = 0,
        anomaly_signals: list[str] = None,
        historical_events_count: int = 0,
        risk_factors: list[str] = None,
        is_business_hours: bool | None = None,
    ) -> RuntimeContext:
        settings = get_settings()
        now = timestamp or datetime.utcnow()
        if is_business_hours is None:
            is_bh = self._is_business_hours(now, settings.BUSINESS_HOURS_START, settings.BUSINESS_HOURS_END)
        else:
            is_bh = is_business_hours
        
        return RuntimeContext(
            timestamp=now,
            user_role=user_role,
            session_data_classification=data_classification,
            agent_id=agent_id,
            action_type=proposed_action.action_type,
            data_scope_size=proposed_action.data_scope_size,
            previous_violations_in_session=previous_violations,
            session_id=session_id,
            is_business_hours=is_bh,
            session_status=session_status,
            human_approval_present=human_approval_present,
            risk_score=risk_score,
            risk_level=risk_level,
            anomaly_score=anomaly_score,
            anomaly_signals=anomaly_signals or [],
            historical_events_count=historical_events_count,
            risk_factors=risk_factors or [],
        )
    
    def build_for_simulation(
        self,
        timestamp: datetime,
        user_role: str,
        session_data_classification: str,
        agent_id: str,
        action_type: str,
        data_scope_size: int,
        previous_violations_in_session: int,
        is_business_hours: bool | None = None,
    ) -> RuntimeContext:
        settings = get_settings()
        if is_business_hours is None:
            is_business_hours = self._is_business_hours(timestamp, settings.BUSINESS_HOURS_START, settings.BUSINESS_HOURS_END)
        
        return RuntimeContext(
            timestamp=timestamp,
            user_role=user_role,
            session_data_classification=session_data_classification,
            agent_id=agent_id,
            action_type=action_type,
            data_scope_size=data_scope_size,
            previous_violations_in_session=previous_violations_in_session,
            session_id="simulation",
            is_business_hours=is_business_hours,
            session_status="active",
        )
    
    @staticmethod
    def _is_business_hours(dt: datetime, start_str: str, end_str: str) -> bool:
        start = time.fromisoformat(start_str)
        end = time.fromisoformat(end_str)
        current_time = dt.time()
        weekday = dt.weekday()
        if weekday >= 5:
            return False
        return start <= current_time < end
