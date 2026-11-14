"""Automated Tests for Agent Service Adapter and Orchestrator Integration."""
import pytest
from src.backend.agent_service import (
    AgentService,
    RealAgentOrchestratorAdapter,
    MockAgentAdapter
)
from src.backend.schemas import IncidentResultResponse

@pytest.mark.asyncio
async def test_real_orchestrator_adapter_faculty_ref_scenario():
    """
    Test real multi-agent orchestrator integration against Faculty Reference Scenario:
    Primary PostgreSQL disk usage climbing steadily while tables and indexes are stable.
    """
    adapter = RealAgentOrchestratorAdapter()
    task_payload = {
        "run_id": "run_faculty_ref_01",
        "alert_id": "SCEN-001-FACULTY-REF",
        "database": "postgresql",
        "database_version": "16",
        "metric": "disk_usage",
        "observed_value": 88.0,
        "threshold": 80.0,
        "severity": "warning",
        "on_call_note": "Host postgres-primary-01 disk usage at 88% and climbing steadily. Table and index sizes are not growing. Investigating replication slots and WAL retention.",
        "correlation_id": "corr_fac_01",
        "client_id": "test_suite"
    }

    result: IncidentResultResponse = await adapter.triage_incident(task_payload)
    assert result.run_id == "run_faculty_ref_01"
    assert result.alert_id == "SCEN-001-FACULTY-REF"
    assert result.confidence >= 0.70
    assert len(result.documentation_citations) > 0
    assert len(result.recommended_actions) > 0
    # Human advisory guarantee: actions must be advisory recommendations
    for action in result.recommended_actions:
        assert isinstance(action, str)

@pytest.mark.asyncio
async def test_real_orchestrator_connection_exhaustion_scenario():
    """Test real multi-agent orchestrator triage on connection exhaustion incident."""
    adapter = RealAgentOrchestratorAdapter()
    task_payload = {
        "run_id": "run_conn_01",
        "alert_id": "SCEN-004-CONN",
        "database": "postgresql",
        "metric": "active_connections",
        "observed_value": 500,
        "threshold": 450,
        "severity": "critical",
        "on_call_note": "PostgreSQL error: FATAL: remaining connection slots are reserved for non-replication superuser connections (max_connections reached).",
        "correlation_id": "corr_conn_01"
    }

    result: IncidentResultResponse = await adapter.triage_incident(task_payload)
    assert result.run_id == "run_conn_01"
    assert "connection" in result.probable_root_cause.lower() or "connection" in result.symptom_class.lower()

@pytest.mark.asyncio
async def test_mock_adapter_behavior():
    """Verify mock agent adapter behavior when active."""
    mock_adapter = MockAgentAdapter()
    task_payload = {
        "run_id": "run_mock_01",
        "alert_id": "ALT-MOCK-01",
        "metric": "disk_usage",
        "observed_value": 75,
        "severity": "warning"
    }

    res: IncidentResultResponse = await mock_adapter.triage_incident(task_payload)
    assert "[MOCK]" in res.symptom_class
    assert res.run_id == "run_mock_01"
    assert res.confidence == 0.88
