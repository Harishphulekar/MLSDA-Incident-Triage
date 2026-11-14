"""Tests for Stub LLM Service Domain-Specific Reasoning."""
from src.agentops.stub_llm import StubLLMService

def test_stub_llm_faculty_reference_scenario():
    service = StubLLMService(latency_ms=0)
    system = "You are an on-call Production Incident Triage Assistant."
    user = "Host postgres-primary-01 disk usage at 87% and climbing steadily. Table and index sizes are not growing."

    res = service.generate_response_sync(system, user, "run_stub_test")
    assert res["cause_class"] == "PostgreSQL Replication Slot WAL Retention"
    assert res["severity"] == "SEV1"
    assert res["routing_decision"] == "escalate_dba"
    assert res["confidence"] >= 0.90
    assert len(res["evidence_citations"]) > 0

def test_stub_llm_connection_saturation():
    service = StubLLMService(latency_ms=0)
    system = "You are an on-call assistant."
    user = "FATAL: remaining connection slots are reserved for non-replication superuser connections (max_connections reached)."

    res = service.generate_response_sync(system, user, "run_stub_test_conn")
    assert res["cause_class"] == "PostgreSQL Connection Saturation"
    assert res["routing_decision"] == "escalate_sre"

def test_stub_llm_ambiguous_incident():
    service = StubLLMService(latency_ms=0)
    system = "You are an on-call assistant."
    user = "Ambiguous telemetry signals, cause unknown."

    res = service.generate_response_sync(system, user, "run_stub_test_ambig")
    assert res["cause_class"] == "Indeterminate System Anomaly"
    assert res["routing_decision"] == "escalate_human_expert"
    assert not res["evidence_sufficient"]
