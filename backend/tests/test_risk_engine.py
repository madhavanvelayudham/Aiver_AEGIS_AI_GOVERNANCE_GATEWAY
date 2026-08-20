import pytest
from app.core.models import ProposedAction
from app.core.risk_engine import RiskEngine, RiskAssessment

def test_risk_low_risk_read():
    engine = RiskEngine()
    action = ProposedAction(tool="search_customer", arguments={}, action_type="read", data_scope_size=1)
    
    res = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="public",
        previous_violations=0,
        is_business_hours=True,
        data_scope_size=1
    )
    
    assert res.risk_score == 10
    assert res.risk_level == "LOW"
    assert "Low-risk search or read operation" in res.risk_factors[0]

def test_risk_medium_risk_write():
    engine = RiskEngine()
    action = ProposedAction(tool="update_patient", arguments={"patient_id": "P101"}, action_type="write", data_scope_size=1)
    
    res = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="internal",
        previous_violations=0,
        is_business_hours=True,
        data_scope_size=1
    )
    
    # Base write: 25 + Internal data: 10 = 35
    assert res.risk_score == 35
    assert res.risk_level == "MEDIUM"
    assert len(res.risk_factors) == 2

def test_risk_high_risk_sensitive_write():
    engine = RiskEngine()
    action = ProposedAction(tool="update_patient", arguments={"patient_id": "P101"}, action_type="write", data_scope_size=1)
    
    res = engine.assess(
        action=action,
        user_role="doctor",
        session_data_classification="phi",
        previous_violations=0,
        is_business_hours=True,
        data_scope_size=1
    )
    
    # Base write: 25 + PHI data: 20 = 45 -> medium risk
    # Let's add after-hours to push it high:
    res_after_hours = engine.assess(
        action=action,
        user_role="doctor",
        session_data_classification="phi",
        previous_violations=0,
        is_business_hours=False,
        data_scope_size=1
    )
    # Base write: 25 + PHI: 20 + After-hours: 10 = 55 -> medium risk
    # Let's add a large scope to push it high (55 + 10 = 65)
    res_high = engine.assess(
        action=action,
        user_role="doctor",
        session_data_classification="phi",
        previous_violations=0,
        is_business_hours=False,
        data_scope_size=150
    )
    assert res_high.risk_score == 65
    assert res_high.risk_level == "HIGH"

def test_risk_destructive_operation():
    engine = RiskEngine()
    action = ProposedAction(tool="delete_customer", arguments={"id": "C101"}, action_type="delete", data_scope_size=1)
    
    res = engine.assess(
        action=action,
        user_role="admin",
        session_data_classification="public",
        previous_violations=0,
        is_business_hours=True,
        data_scope_size=1
    )
    
    # Base delete: 50 + Destructive penalty: 20 = 70
    assert res.risk_score == 70
    assert res.risk_level == "HIGH"
    assert any("Destructive" in f for f in res.risk_factors)

def test_risk_phi_classification():
    engine = RiskEngine()
    action = ProposedAction(tool="read_patient", arguments={}, action_type="read", data_scope_size=1)
    
    res = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="phi",
        previous_violations=0,
        is_business_hours=True,
        data_scope_size=1
    )
    
    # Base read: 10 + PHI: 20 = 30 -> MEDIUM
    assert res.risk_score == 30
    assert res.risk_level == "MEDIUM"

def test_risk_after_hours():
    engine = RiskEngine()
    action = ProposedAction(tool="read_patient", arguments={}, action_type="read", data_scope_size=1)
    
    res = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="public",
        previous_violations=0,
        is_business_hours=False,
        data_scope_size=1
    )
    
    # Base read: 10 + After-hours: 10 = 20
    assert res.risk_score == 20
    assert any("outside standard business hours" in f for f in res.risk_factors)

def test_risk_previous_violations():
    engine = RiskEngine()
    action = ProposedAction(tool="read_patient", arguments={}, action_type="read", data_scope_size=1)
    
    res = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="public",
        previous_violations=2,
        is_business_hours=True,
        data_scope_size=1
    )
    
    # Base read: 10 + Violations: 2 * 5 = 10 -> 20
    assert res.risk_score == 20
    assert any("previous session violations" in f for f in res.risk_factors)
    
    # Verify bounding at 15 points
    res_max = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="public",
        previous_violations=5,
        is_business_hours=True,
        data_scope_size=1
    )
    assert res_max.risk_score == 25  # 10 + 15 max violations penalty

def test_risk_large_data_scope():
    engine = RiskEngine()
    action = ProposedAction(tool="read_patient", arguments={}, action_type="read", data_scope_size=150)
    
    res = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="public",
        previous_violations=0,
        is_business_hours=True,
        data_scope_size=150
    )
    
    # Base read: 10 + Large scope: 10 = 20
    assert res.risk_score == 20
    assert any("Large data scope size" in f for f in res.risk_factors)

def test_risk_multiple_signals_combined():
    engine = RiskEngine()
    action = ProposedAction(tool="delete_customer", arguments={"id": "C101"}, action_type="delete", data_scope_size=120)
    
    res = engine.assess(
        action=action,
        user_role="admin",
        session_data_classification="phi",
        previous_violations=3,
        is_business_hours=False,
        data_scope_size=120,
        anomaly_score=80
    )
    
    # Base delete: 50
    # Sensitivity (phi): 20
    # Destructive: 20
    # After-hours: 10
    # Violations: min(15, 3*5) = 15
    # Large scope: 10
    # Anomaly: min(15, 80 * 0.15) = min(15, 12) = 12
    # Total = 50 + 20 + 20 + 10 + 15 + 10 + 12 = 137 -> Bounded at 100
    assert res.risk_score == 100
    assert res.risk_level == "CRITICAL"

def test_risk_bounds_normalization():
    engine = RiskEngine()
    action = ProposedAction(tool="read_patient", arguments={}, action_type="read", data_scope_size=1)
    
    res = engine.assess(
        action=action,
        user_role="nurse",
        session_data_classification="public",
        previous_violations=0,
        is_business_hours=True,
        data_scope_size=1
    )
    assert 0 <= res.risk_score <= 100

def test_risk_level_mapping():
    engine = RiskEngine()
    action = ProposedAction(tool="read_patient", arguments={}, action_type="read", data_scope_size=1)
    
    # LOW (< 30)
    res_low = engine.assess(action, "nurse", "public", 0, True, 1)
    assert res_low.risk_level == "LOW"
    
    # MEDIUM (30-59)
    res_med = engine.assess(action, "nurse", "phi", 0, True, 1)
    assert res_med.risk_level == "MEDIUM"
    
    # HIGH (60-84)
    action_del = ProposedAction(tool="delete_customer", arguments={}, action_type="delete", data_scope_size=1)
    res_high = engine.assess(action_del, "nurse", "public", 0, True, 1)
    assert res_high.risk_level == "HIGH"
    
    # CRITICAL (85-100)
    res_crit = engine.assess(action_del, "nurse", "phi", 3, False, 1)
    assert res_crit.risk_level == "CRITICAL"

def test_risk_factors_are_explainable():
    engine = RiskEngine()
    action = ProposedAction(tool="update_patient", arguments={}, action_type="write", data_scope_size=1)
    res = engine.assess(action, "nurse", "phi", 0, True, 1)
    
    for factor in res.risk_factors:
        assert isinstance(factor, str)
        assert len(factor) > 0

def test_risk_deterministic_repeatability():
    engine = RiskEngine()
    action = ProposedAction(tool="update_patient", arguments={}, action_type="write", data_scope_size=1)
    
    res1 = engine.assess(action, "nurse", "phi", 2, False, 1)
    res2 = engine.assess(action, "nurse", "phi", 2, False, 1)
    
    assert res1.risk_score == res2.risk_score
    assert res1.risk_level == res2.risk_level
    assert res1.risk_factors == res2.risk_factors
