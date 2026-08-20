import pytest
from app.core.models import ProposedAction
from app.core.anomaly_analyzer import BehavioralAnomalyAnalyzer, AnomalyAssessment

def test_anomaly_insufficient_history():
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(tool="read_patient", arguments={}, action_type="read", data_scope_size=1)
    
    # 0 items
    res0 = analyzer.analyze([], action)
    assert res0.anomaly_score == 0
    assert "Insufficient history" in res0.signals[0]
    
    # 2 items
    res2 = analyzer.analyze([
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ], action)
    assert res2.anomaly_score == 0
    assert "Insufficient history" in res2.signals[0]

def test_anomaly_normal_repeated_read():
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(tool="read_patient", arguments={}, action_type="read", data_scope_size=1)
    
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ]
    res = analyzer.analyze(history, action)
    assert res.anomaly_score == 0
    assert "matches established session behavioral pattern" in res.signals[0]

def test_anomaly_new_read_action():
    analyzer = BehavioralAnomalyAnalyzer()
    
    # Tool read_patient is in history, but we do search_customer (read action type)
    action = ProposedAction(tool="search_customer", arguments={}, action_type="read", data_scope_size=1)
    
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ]
    res = analyzer.analyze(history, action)
    
    # Novel tool: search_customer (+20)
    # Action type 'read' exists in history, ratio = 100% (no novelty penalty, no frequency penalty)
    assert res.anomaly_score == 20
    assert any("Novel tool access" in s for s in res.signals)

def test_anomaly_new_write_action():
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(tool="update_patient", arguments={}, action_type="write", data_scope_size=1)
    
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ]
    res = analyzer.analyze(history, action)
    
    # Novel action type write (+25)
    # Novel tool update_patient (+20)
    # Sequence deviation (read-only history -> write): +20
    # Total = 65
    assert res.anomaly_score == 65
    assert any("First-time write action" in s for s in res.signals)
    assert any("Sequence deviation" in s for s in res.signals)

def test_anomaly_new_destructive_action():
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(tool="delete_customer", arguments={}, action_type="delete", data_scope_size=1)
    
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ]
    res = analyzer.analyze(history, action)
    
    # Novel action type delete (+40)
    # Novel tool delete_customer (+20)
    # Critical sequence deviation (read-only -> delete): +40
    # Total = 100
    assert res.anomaly_score == 100
    assert any("First-time delete action" in s for s in res.signals)
    assert any("Critical sequence deviation" in s for s in res.signals)

def test_anomaly_tool_novelty():
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(tool="search_customer", arguments={}, action_type="read", data_scope_size=1)
    
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ]
    res = analyzer.analyze(history, action)
    assert res.anomaly_score == 20
    assert any("Novel tool access" in s for s in res.signals)

def test_anomaly_sequence_deviation():
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(tool="update_patient", arguments={}, action_type="write", data_scope_size=1)
    
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "search", "tool": "search_customer"},
        {"action_type": "read", "tool": "read_patient"}
    ]
    res = analyzer.analyze(history, action)
    
    # Action type write is novel: +25
    # Tool update_patient is novel: +20
    # Sequence deviation (read-only history -> write): +20
    # Total = 65
    assert res.anomaly_score == 65
    assert any("Sequence deviation" in s for s in res.signals)

def test_anomaly_destructive_escalation():
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(tool="delete_customer", arguments={}, action_type="delete", data_scope_size=1)
    
    # History contains reads and writes, but no deletes
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "write", "tool": "update_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ]
    res = analyzer.analyze(history, action)
    
    # Novel action type delete: +40
    # Novel tool delete_customer: +20
    # History is NOT all reads, so no sequence deviation (+0)
    # Total = 60
    assert res.anomaly_score == 60
    assert any("First-time delete action" in s for s in res.signals)
    assert not any("Critical sequence deviation" in s for s in res.signals)

def test_anomaly_combined_signals():
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(tool="delete_customer", arguments={}, action_type="delete", data_scope_size=1)
    
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ]
    res = analyzer.analyze(history, action)
    assert res.anomaly_score == 100

def test_anomaly_bounds_check():
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(tool="delete_customer", arguments={}, action_type="delete", data_scope_size=1)
    
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ]
    res = analyzer.analyze(history, action)
    assert 0 <= res.anomaly_score <= 100

def test_anomaly_deterministic_repeatability():
    analyzer = BehavioralAnomalyAnalyzer()
    action = ProposedAction(tool="update_patient", arguments={}, action_type="write", data_scope_size=1)
    
    history = [
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"},
        {"action_type": "read", "tool": "read_patient"}
    ]
    
    res1 = analyzer.analyze(history, action)
    res2 = analyzer.analyze(history, action)
    
    assert res1.anomaly_score == res2.anomaly_score
    assert res1.signals == res2.signals
