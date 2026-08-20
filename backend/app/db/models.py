from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.db.database import Base

class AgentModel(Base):
    __tablename__ = "agents"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    sessions = relationship("SessionModel", back_populates="agent")

class SessionModel(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String, ForeignKey("agents.id"), nullable=False)
    user_role = Column(String, nullable=False)
    data_classification = Column(String, nullable=False, default="public")
    active_policy_id = Column(String, ForeignKey("policies.id"), nullable=True)
    previous_violations = Column(Integer, default=0)
    is_business_hours = Column(Boolean, nullable=True)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    agent = relationship("AgentModel", back_populates="sessions")
    audit_events = relationship("AuditEventModel", back_populates="session")
    hitl_requests = relationship("HITLRequestModel", back_populates="session")

class PolicyModel(Base):
    __tablename__ = "policies"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, default="")
    extends_id = Column(String, ForeignKey("policies.id"), nullable=True)
    active_version = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    versions = relationship("PolicyVersionModel", back_populates="policy")

class PolicyVersionModel(Base):
    __tablename__ = "policy_versions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    policy_id = Column(String, ForeignKey("policies.id"), nullable=False)
    version = Column(Integer, nullable=False)
    yaml_content = Column(Text, nullable=False)
    parsed_rules = Column(JSON, nullable=True)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    policy = relationship("PolicyModel", back_populates="versions")

class AuditEventModel(Base):
    __tablename__ = "audit_events"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    request_id = Column(String, nullable=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True)
    agent_id = Column(String, nullable=True)
    action_type = Column(String, nullable=True)
    tool_name = Column(String, nullable=True)
    proposed_action = Column(JSON, nullable=True)
    runtime_context = Column(JSON, nullable=True)
    policy_version_id = Column(String, ForeignKey("policy_versions.id"), nullable=True)
    policy_chain = Column(JSON, nullable=True)
    evaluated_rules = Column(JSON, nullable=True)
    matched_rules = Column(JSON, nullable=True)
    decision = Column(String, nullable=True)
    deciding_rule_id = Column(String, nullable=True)
    explanation = Column(Text, nullable=True)
    tool_result = Column(JSON, nullable=True)
    event_type = Column(String, default="EVALUATION")
    created_at = Column(DateTime, default=datetime.utcnow)
    session = relationship("SessionModel", back_populates="audit_events")

class HITLRequestModel(Base):
    __tablename__ = "hitl_requests"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    agent_id = Column(String, nullable=True)
    audit_event_id = Column(String, ForeignKey("audit_events.id"), nullable=True)
    proposed_action = Column(JSON, nullable=True)
    runtime_context = Column(JSON, nullable=True)
    policy_version_id = Column(String, ForeignKey("policy_versions.id"), nullable=True)
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    resolution_reason = Column(String, nullable=True)
    session = relationship("SessionModel", back_populates="hitl_requests")

Index('idx_audit_session_time', AuditEventModel.session_id, AuditEventModel.created_at)
Index('idx_audit_decision', AuditEventModel.decision)
Index('idx_hitl_status', HITLRequestModel.status, HITLRequestModel.expires_at)
