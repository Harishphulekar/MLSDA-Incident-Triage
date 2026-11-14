"""Tests for Prometheus Metrics Registration, Incrementing, and Exporting."""
from src.agentops.metrics import (
    HTTP_REQUESTS_TOTAL,
    INCIDENT_E2E_DURATION_SECONDS,
    AGENT_STEP_DURATION_SECONDS,
    AGENT_EXECUTION_TOTAL,
    AGENT_TOOL_CALLS_TOTAL,
    QUEUE_DEPTH_CURRENT,
    LLM_TOKEN_USAGE_TOTAL,
    LLM_COST_DOLLARS_TOTAL,
    get_metrics_output
)

def test_prometheus_metrics_increment_and_observe():
    HTTP_REQUESTS_TOTAL.labels(method="POST", endpoint="/api/v1/incidents", status="200").inc()
    INCIDENT_E2E_DURATION_SECONDS.labels(status="success", routing_decision="escalate_dba").observe(0.125)
    AGENT_STEP_DURATION_SECONDS.labels(agent="TriageAgent", step="triage_classification").observe(0.045)
    AGENT_EXECUTION_TOTAL.labels(agent="TriageAgent", status="success").inc()
    AGENT_TOOL_CALLS_TOTAL.labels(agent="RetrievalAgent", tool_name="vector_search", status="success").inc()
    QUEUE_DEPTH_CURRENT.set(5)
    LLM_TOKEN_USAGE_TOTAL.labels(model="stub", prompt_version="v1.1.0", token_type="prompt").inc(120)
    LLM_COST_DOLLARS_TOTAL.labels(model="stub", prompt_version="v1.1.0").inc(0.00015)

    output = get_metrics_output().decode("utf-8")
    assert "http_requests_total" in output
    assert "incident_e2e_duration_seconds" in output
    assert "agent_step_duration_seconds" in output
    assert "queue_depth_current" in output
    assert "llm_token_usage_total" in output
    assert "llm_cost_dollars_total" in output
    assert "process_cpu_percent" in output
    assert "process_resident_memory_bytes" in output
