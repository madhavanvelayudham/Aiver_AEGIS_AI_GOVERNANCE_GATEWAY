from datetime import datetime
from typing import Any, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import ProposedAction, RuntimeContext, GovernanceDecision
from app.core.policy_loader import PolicyLoader
from app.core.policy_resolver import PolicyResolver
from app.core.rule_evaluator import RuleEvaluator
from app.core.decision_engine import DecisionEngine
from app.core.context_builder import ContextBuilder
from app.config import get_settings
from app.db.models import SessionModel, AuditEventModel, PolicyVersionModel

from app.core.risk_engine import RiskEngine
from app.core.anomaly_analyzer import BehavioralAnomalyAnalyzer

# Custom domain/service exceptions
class SessionNotFoundError(Exception):
    pass

class PolicyNotFoundError(Exception):
    pass

class SuspendedSessionError(Exception):
    pass

class InvalidGovernanceStateError(Exception):
    pass


def _sanitize_arguments(arguments: dict) -> dict:
    sensitive_keys = {"password", "secret", "token", "key", "ssn", "credit_card", "cc", "auth"}
    sanitized = {}
    for k, v in arguments.items():
        if any(sk in k.lower() for sk in sensitive_keys):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = _sanitize_arguments(v)
        else:
            sanitized[k] = v
    return sanitized


class GovernanceService:
    def __init__(self):
        self.policy_loader = PolicyLoader()
        self.policy_resolver = PolicyResolver()
        self.rule_evaluator = RuleEvaluator()
        self.decision_engine = DecisionEngine()
        self.context_builder = ContextBuilder()
        self.risk_engine = RiskEngine()
        self.anomaly_analyzer = BehavioralAnomalyAnalyzer()
        self._policies = {}  # loaded policies cache
    
    def load_policies_from_directory(self, directory):
        from pathlib import Path
        self._policies = self.policy_loader.load_policies_from_directory(Path(directory))
    
    def evaluate(
        self,
        proposed_action: ProposedAction,
        context: RuntimeContext,
        policy_id: str | None = None,
    ) -> GovernanceDecision:
        if context.session_status == "suspended":
            return GovernanceDecision(
                decision="SUSPEND_SESSION",
                policy_chain=[],
                explanation="Session is suspended. No further actions permitted."
            )
        
        target_policy = policy_id or get_settings().DEFAULT_POLICY_ID
        resolved = self.policy_resolver.resolve(target_policy, self._policies)
        evaluation = self.rule_evaluator.evaluate(context, proposed_action, resolved)
        decision = self.decision_engine.decide(evaluation, resolved)
        
        settings = get_settings()
        if decision.decision == "BLOCK":
            resulting_violations = context.previous_violations_in_session + 1
            if resulting_violations >= settings.VIOLATION_THRESHOLD:
                decision = GovernanceDecision(
                    decision="SUSPEND_SESSION",
                    deciding_rule_id=decision.deciding_rule_id,
                    matched_rules=decision.matched_rules,
                    evaluated_rules=decision.evaluated_rules,
                    policy_chain=decision.policy_chain,
                    explanation=(
                        f"{decision.explanation}. "
                        f"Violation count ({resulting_violations}) reached threshold "
                        f"({settings.VIOLATION_THRESHOLD}). Session suspended."
                    ),
                    decision_id=decision.decision_id
                )
        
        return decision

    async def evaluate_session_action(
        self,
        session_id: str,
        proposed_action: ProposedAction,
        db: AsyncSession,
        request_id: str,
        human_approval_present: bool = False
    ) -> tuple[GovernanceDecision, AuditEventModel, SessionModel]:
        """Loads session, evaluates proposed action, updates DB status/violations, and persists audit trail."""
        # 1. Load session from database
        stmt = select(SessionModel).where(SessionModel.id == session_id)
        # Use with_for_update for row-level locking to prevent race conditions on violation counts
        res = await db.execute(stmt.with_for_update())
        session = res.scalar_one_or_none()
        
        if not session:
            raise SessionNotFoundError(f"Session with ID '{session_id}' not found.")
        
        # 2. CORRECTION 2: If session is already suspended, return SUSPEND_SESSION directly
        if session.status == "suspended":
            decision = GovernanceDecision(
                decision="SUSPEND_SESSION",
                policy_chain=[],
                explanation="Session is suspended. No further actions permitted."
            )
            
            # Log audit trail for suspended session evaluation attempt
            # Store explicit risk_calculated=False so frontend never falls back to a default risk value
            suspended_context = {
                "risk_calculated": False,
                "risk_score": None,
                "risk_level": None,
                "anomaly_score": None,
                "risk_factors": [],
                "session_status": "suspended",
                "user_role": session.user_role,
                "session_data_classification": session.data_classification,
            }
            audit_event = AuditEventModel(
                request_id=request_id,
                session_id=session.id,
                agent_id=session.agent_id,
                action_type=proposed_action.action_type,
                tool_name=proposed_action.tool,
                proposed_action={
                    "tool": proposed_action.tool,
                    "arguments": _sanitize_arguments(proposed_action.arguments),
                    "action_type": proposed_action.action_type,
                    "data_scope_size": proposed_action.data_scope_size
                },
                runtime_context=suspended_context,
                decision="SUSPEND_SESSION",
                explanation=decision.explanation,
                event_type="EVALUATION",
                created_at=datetime.utcnow()
            )
            db.add(audit_event)
            await db.commit()
            return decision, audit_event, session
            
        # 3. Verify target policy exists in loaded policies
        target_policy = session.active_policy_id or get_settings().DEFAULT_POLICY_ID
        if target_policy not in self._policies:
            raise PolicyNotFoundError(f"Policy '{target_policy}' not found.")
            
        # Get matching policy version details from DB for exact audit logging
        stmt_ver = select(PolicyVersionModel).where(
            PolicyVersionModel.policy_id == target_policy,
            PolicyVersionModel.status == "active"
        ).order_by(PolicyVersionModel.version.desc())
        res_ver = await db.execute(stmt_ver)
        policy_ver = res_ver.scalars().first()
        policy_version_id = policy_ver.id if policy_ver else None
        
        # Retrieve recent session history (last 10 events) for anomaly analyzer
        stmt_audit = (
            select(AuditEventModel)
            .where(AuditEventModel.session_id == session.id)
            .order_by(AuditEventModel.created_at.desc())
            .limit(10)
        )
        res_audit = await db.execute(stmt_audit)
        events = res_audit.scalars().all()

        history = []
        import json
        for e in events:
            prop = {}
            if isinstance(e.proposed_action, dict):
                prop = e.proposed_action
            elif isinstance(e.proposed_action, str):
                try:
                    prop = json.loads(e.proposed_action)
                except Exception:
                    prop = {}
            
            act_type = e.action_type or prop.get("action_type") or "read"
            tool_val = e.tool_name or prop.get("tool") or ""
            
            history.append({
                "action_type": act_type,
                "tool": tool_val
            })
            
        # Reverse to chronological order (oldest -> newest) for sequence analysis
        history.reverse()

        # Calculate business hours for risk engine (use explicit session override if set, else calculate from clock)
        settings = get_settings()
        now = datetime.utcnow()
        if session.is_business_hours is not None:
            is_bh = session.is_business_hours
        else:
            is_bh = self.context_builder._is_business_hours(
                now, settings.BUSINESS_HOURS_START, settings.BUSINESS_HOURS_END
            )

        # Run behavioral anomaly analyzer and risk engine
        anomaly_res = self.anomaly_analyzer.analyze(history, proposed_action)
        risk_res = self.risk_engine.assess(
            action=proposed_action,
            user_role=session.user_role,
            session_data_classification=session.data_classification,
            previous_violations=session.previous_violations,
            is_business_hours=is_bh,
            data_scope_size=proposed_action.data_scope_size,
            anomaly_score=anomaly_res.anomaly_score
        )

        # 4. Build runtime context server-side
        context = self.context_builder.build_from_session(
            session_id=session.id,
            agent_id=session.agent_id,
            user_role=session.user_role,
            data_classification=session.data_classification,
            previous_violations=session.previous_violations,
            session_status=session.status,
            proposed_action=proposed_action,
            timestamp=now,
            human_approval_present=human_approval_present,
            risk_score=risk_res.risk_score,
            risk_level=risk_res.risk_level,
            anomaly_score=anomaly_res.anomaly_score,
            anomaly_signals=anomaly_res.signals,
            historical_events_count=len(history),
            risk_factors=risk_res.risk_factors,
            is_business_hours=is_bh
        )
        
        # 5. Evaluate policy rules
        decision = self.evaluate(proposed_action, context, target_policy)
        
        # 6. Apply violation threshold and update session ORM object
        if decision.decision == "BLOCK":
            session.previous_violations += 1
            settings = get_settings()
            if session.previous_violations >= settings.VIOLATION_THRESHOLD:
                session.status = "suspended"
        elif decision.decision == "SUSPEND_SESSION":
            # Direct rule-based suspension
            session.previous_violations += 1
            session.status = "suspended"
            
        # 7. Persist audit trail event
        sanitized_action = {
            "tool": proposed_action.tool,
            "arguments": _sanitize_arguments(proposed_action.arguments),
            "action_type": proposed_action.action_type,
            "data_scope_size": proposed_action.data_scope_size
        }
        
        # Serialize RuleMatch list to JSON compatible dict/list structure
        evaluated_rules_json = [r.model_dump() for r in decision.evaluated_rules]
        
        audit_event = AuditEventModel(
            request_id=request_id,
            session_id=session.id,
            agent_id=session.agent_id,
            action_type=proposed_action.action_type,
            tool_name=proposed_action.tool,
            proposed_action=sanitized_action,
            runtime_context=context.model_dump(mode='json'),
            policy_version_id=policy_version_id,
            policy_chain=decision.policy_chain,
            evaluated_rules=evaluated_rules_json,
            matched_rules=decision.matched_rules,
            decision=decision.decision,
            deciding_rule_id=decision.deciding_rule_id,
            explanation=decision.explanation,
            event_type="EVALUATION",
            created_at=now
        )
        db.add(audit_event)
        await db.commit()
        
        return decision, audit_event, session

    async def get_audit_events(self, db: AsyncSession, limit: int = 100) -> list[AuditEventModel]:
        """Retrieves audit events sorted by creation date with sensitive argument redaction."""
        stmt = select(AuditEventModel).order_by(AuditEventModel.created_at.desc()).limit(limit)
        res = await db.execute(stmt)
        events = res.scalars().all()
        for e in events:
            if e.proposed_action:
                # Safe copy and redaction before serialization/return
                sanitized_action = dict(e.proposed_action)
                if "arguments" in sanitized_action:
                    sanitized_action["arguments"] = _sanitize_arguments(sanitized_action["arguments"])
                e.proposed_action = sanitized_action
        return list(events)

    async def get_sessions(self, db: AsyncSession) -> list[SessionModel]:
        """Retrieves all sessions from the database."""
        stmt = select(SessionModel).order_by(SessionModel.created_at.desc())
        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def get_policies(self, db: AsyncSession) -> list[dict]:
        """Retrieves all loaded policies active versions and rules definitions."""
        stmt = select(PolicyVersionModel).where(PolicyVersionModel.status == "active").order_by(PolicyVersionModel.version.desc())
        res = await db.execute(stmt)
        versions = res.scalars().all()
        policy_list = []
        seen = set()
        for v in versions:
            if v.policy_id not in seen:
                seen.add(v.policy_id)
                policy_list.append({
                    "policy_id": v.policy_id,
                    "version": v.version,
                    "yaml_content": v.yaml_content,
                    "parsed_rules": v.parsed_rules
                })
        return policy_list

    async def get_metrics(self, db: AsyncSession) -> dict:
        """Retrieves core system operational metrics."""
        stmt = select(AuditEventModel.decision)
        res = await db.execute(stmt)
        decisions = res.scalars().all()
        
        counts = {"ALLOW": 0, "BLOCK": 0, "REQUIRE_HITL": 0, "SUSPEND_SESSION": 0}
        for d in decisions:
            if d in counts:
                counts[d] += 1
            else:
                counts[d] = counts.get(d, 0) + 1
                
        stmt_sess = select(SessionModel.status)
        res_sess = await db.execute(stmt_sess)
        statuses = res_sess.scalars().all()
        
        sess_metrics = {"active": 0, "suspended": 0}
        for s in statuses:
            if s in sess_metrics:
                sess_metrics[s] += 1
            else:
                sess_metrics[s] = sess_metrics.get(s, 0) + 1
                
        return {
            "total_requests": len(decisions),
            "decision_counts": counts,
            "session_counts": sess_metrics
        }

    async def create_session(
        self,
        session_id: str,
        user_role: str,
        data_classification: str,
        db: AsyncSession,
        previous_violations: Optional[int] = None,
        is_business_hours: Optional[bool] = None,
        status: Optional[str] = None
    ) -> SessionModel:
        """Creates or updates a session."""
        stmt = select(SessionModel).where(SessionModel.id == session_id)
        res = await db.execute(stmt)
        sess = res.scalar_one_or_none()
        
        violations_val = previous_violations if previous_violations is not None else 0
        if status is None:
            resolved_status = "suspended" if violations_val >= 3 else "active"
        else:
            resolved_status = status

        if not sess:
            sess = SessionModel(
                id=session_id,
                agent_id="aegis-agent-01",
                user_role=user_role,
                data_classification=data_classification,
                active_policy_id="base_policy",
                previous_violations=violations_val,
                is_business_hours=is_business_hours,
                status=resolved_status
            )
            db.add(sess)
        else:
            sess.user_role = user_role
            sess.data_classification = data_classification
            if is_business_hours is not None:
                sess.is_business_hours = is_business_hours
            if previous_violations is not None:
                sess.previous_violations = previous_violations
                sess.status = resolved_status
            elif status is not None:
                sess.status = status
        await db.commit()
        return sess

