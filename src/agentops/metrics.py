"""Prometheus Metrics Exporter for System, Agent, and Cost Observability."""
import time
import os
import psutil
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    Summary,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY
)

# Unregister default process/platform collectors if present to avoid DuplicateTimeseries
# when registering custom process gauges below
for _coll in list(REGISTRY._collector_to_names.keys()):
    if _coll.__class__.__name__ in ("ProcessCollector", "PlatformCollector", "GCCollector"):
        try:
            REGISTRY.unregister(_coll)
        except Exception:
            pass

# -----------------------------------------------------------------------------
# 1. HTTP and API Metrics
# -----------------------------------------------------------------------------
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests handled by the API",
    ["method", "endpoint", "status"]
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# -----------------------------------------------------------------------------
# 2. End-to-End and Agent-Level Metrics
# -----------------------------------------------------------------------------
INCIDENT_E2E_DURATION_SECONDS = Histogram(
    "incident_e2e_duration_seconds",
    "Total end-to-end incident triage pipeline duration in seconds",
    ["status", "routing_decision"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 3.5, 5.0, 10.0, 20.0]
)

AGENT_STEP_DURATION_SECONDS = Histogram(
    "agent_step_duration_seconds",
    "Latency of individual agent execution steps in seconds",
    ["agent", "step"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0]
)

AGENT_EXECUTION_TOTAL = Counter(
    "agent_execution_total",
    "Count of agent execution runs by agent name and outcome",
    ["agent", "status"]
)

AGENT_STEPS_PER_RUN = Histogram(
    "agent_steps_per_run",
    "Number of reasoning and execution steps taken per incident run",
    buckets=[1, 2, 3, 4, 5, 8, 10, 15]
)

AGENT_TOOL_CALLS_TOTAL = Counter(
    "agent_tool_calls_total",
    "Number of tool calls executed by agents",
    ["agent", "tool_name", "status"]
)

AGENT_RETRIES_TOTAL = Counter(
    "agent_retries_total",
    "Number of retries triggered across agent steps",
    ["agent", "reason"]
)

# -----------------------------------------------------------------------------
# 3. Queue and Worker Infrastructure Metrics
# -----------------------------------------------------------------------------
QUEUE_DEPTH_CURRENT = Gauge(
    "queue_depth_current",
    "Current number of pending triage jobs in the queue"
)

WORKER_ACTIVE_COUNT = Gauge(
    "worker_active_count",
    "Number of active worker processes consuming jobs"
)

PROCESS_CPU_PERCENT = Gauge(
    "process_cpu_percent",
    "Current CPU utilization percent of the process"
)

PROCESS_RESIDENT_MEMORY_BYTES = Gauge(
    "process_resident_memory_bytes",
    "Resident memory usage in bytes"
)

PROCESS_UPTIME_SECONDS = Gauge(
    "process_uptime_seconds",
    "Uptime of the service process in seconds"
)

# -----------------------------------------------------------------------------
# 4. LLM Token and Cost Metrics
# -----------------------------------------------------------------------------
LLM_TOKEN_USAGE_TOTAL = Counter(
    "llm_token_usage_total",
    "Total LLM tokens consumed",
    ["model", "prompt_version", "token_type"]  # token_type: prompt, completion
)

LLM_COST_DOLLARS_TOTAL = Counter(
    "llm_cost_dollars_total",
    "Cumulative estimated LLM cost in USD",
    ["model", "prompt_version"]
)

_process_start_time = time.time()
_psutil_process = psutil.Process(os.getpid())

def update_system_resource_metrics():
    """Sample and update process-level resource metrics."""
    try:
        cpu = _psutil_process.cpu_percent(interval=None)
        mem = _psutil_process.memory_info().rss
        PROCESS_CPU_PERCENT.set(cpu)
        PROCESS_RESIDENT_MEMORY_BYTES.set(mem)
        PROCESS_UPTIME_SECONDS.set(time.time() - _process_start_time)
    except Exception:
        pass

def get_metrics_output() -> bytes:
    """Generate and return current Prometheus metrics output with refreshed system metrics."""
    update_system_resource_metrics()
    return generate_latest(REGISTRY)
