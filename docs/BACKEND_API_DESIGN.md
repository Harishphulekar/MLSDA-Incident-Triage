# Backend and API Architecture Design Document

**Project:** Production Incident Triage and Runbook Assistant  
**Course:** ML System Design and AgentOps (UE24AM342AA5)  
**Mini Project:** 08  
**Author:** Member 1 — Backend & API Engineer  
**Component:** `src/backend/`  

---

## 1. Executive Summary & Architecture Overview

The **Backend & API Gateway** (`src/backend/`) is the primary operational interface for the Production Incident Triage and Runbook Assistant. It accepts raw and structured infrastructure alerts from monitoring agents, on-call consoles, and automated systems, performs strict multi-tier validation and security checks, isolates malicious or malformed payloads into a quarantine store, generates unique lifecycle run IDs, and dispatches valid jobs into an asynchronous message queue. Background workers consume these jobs, invoke the multi-agent reasoning and verification pipeline, and persist the grounded advisory recommendations for human SRE and DBA engineers.

### High-Level Architecture Flow

```
                      +---------------------------------------+
                      |       Alert Ingestion Client          |
                      |   (SRE Console, Prometheus, Locust)   |
                      +---------------------------------------+
                                          |
                                          | POST /api/v1/incidents
                                          v
                      +---------------------------------------+
                      |         FastAPI Gateway (API)         |
                      |  - Correlation ID Injection           |
                      |  - Per-Client Rate Limiter (Token)    |
                      |  - Idempotency Deduplication Key      |
                      +---------------------------------------+
                                          |
                         +----------------+----------------+
                         |                                 |
                         v                                 v
          [ Validation / Security Layer ]         [ Destructive / Injection ]
          - Required Fields & Types               - Prompt Injection Guardrail
          - Database Allowed Set                  - Dangerous Shell / SQL Commands
          - Metric Ranges & Consistency           - Malformed Payload Structure
                         |                                 |
              [ PASS ]   |                     [ FAIL ]    |
                         v                                 v
            +-------------------------+       +-------------------------+
            |  Generate Unique Run ID |       |    Quarantine Store     |
            |     (run_<hex_12>)      |       |  (Redacted & Isolated)  |
            +-------------------------+       +-------------------------+
                         |                                 |
                         v                                 v
            +-------------------------+       +-------------------------+
            |    Redis Task Queue     |       |  HTTP 422 Rejection     |
            |   (In-Memory Fallback)  |       |  (quarantine_id returned)
            +-------------------------+       +-------------------------+
                         |
                         v
            +-------------------------+
            |   Async Agent Worker    |
            |  - Trace Context Extract|
            |  - Bounded Retries (x3) |
            |  - Status: processing   |
            +-------------------------+
                         |
                         v
            +-------------------------+
            | Agent Service Adapter   |
            | -> Triage Agent         |
            | -> Retrieval Agent      |
            | -> Verification Agent   |
            +-------------------------+
                         |
                         v
            +-------------------------+
            | State & Result Storage  |
            | (Redis / Persistent Map)|
            | Status: completed/escal.|
            +-------------------------+
                         |
                         v
    +-----------------------------------------------+
    | GET /api/v1/incidents/{run_id}         (Status)
    | GET /api/v1/incidents/{run_id}/result  (Result)
    +-----------------------------------------------+
```

---

## 2. API Endpoints Reference

The FastAPI gateway provides standard RESTful endpoints documented via automatic OpenAPI (Swagger UI) at `/docs` and ReDoc at `/redoc`.

| Method | Endpoint | Status Code | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/incidents` | `202 Accepted` / `200 OK` | Submit production incident alert for automated triage. |
| `GET` | `/api/v1/incidents/{run_id}` | `200 OK` / `404 Not Found` | Retrieve run status, timestamps, latency and retries. |
| `GET` | `/api/v1/incidents/{run_id}/result` | `200 OK` / `202 Accepted` / `404` | Retrieve structured agent diagnostic recommendations. |
| `GET` | `/api/v1/incidents/quarantine` | `200 OK` | List quarantined alerts for SRE security review. |
| `GET` | `/api/v1/incidents/quarantine/{quarantine_id}` | `200 OK` / `404` | Inspect a specific quarantined record with sanitized payload. |
| `GET` | `/api/v1/health` & `/health` | `200 OK` | Liveness probe for container orchestrators. |
| `GET` | `/api/v1/ready` & `/health/ready` | `200 OK` | Readiness probe verifying Redis and queue depth. |
| `GET` | `/api/v1/metrics` & `/metrics` | `200 OK` | Prometheus scrape target for latency and error metrics. |
| `POST` | `/api/v1/feedback` | `200 OK` | Record human SRE feedback on triage quality. |
| `GET` | `/api/v1/feedback/stats` | `200 OK` | Get aggregate feedback and satisfaction metrics. |
| `GET` | `/api/v1/prompts` | `200 OK` | List available and active system prompt versions. |

---

## 3. Request and Response Schemas

### 3.1 Standard Incident Alert Request (`IncidentAlertRequest`)

```json
{
  "alert_id": "ALT-PG-DISK-001",
  "database": "postgresql",
  "database_version": "16",
  "metric": "disk_usage",
  "observed_value": 88.5,
  "threshold": 80.0,
  "severity": "warning",
  "on_call_note": "Host postgres-primary-01 disk usage at 88% and climbing steadily. Table and index sizes are not growing.",
  "timestamp": "2026-11-14T12:00:00Z",
  "metadata": {
    "cluster": "prod-us-east-1",
    "node": "postgres-primary-01"
  },
  "client_id": "sre-monitoring",
  "sync_mode": false
}
```

#### Field Specifications:
- `alert_id` (string, required): Unique alert identifier (2–128 characters).
- `database` (string, required): Allowed values: `postgresql`, `postgres`.
- `database_version` (string, optional): Engine version (e.g., `"14"`, `"15"`, `"16"`).
- `metric` (string, required): Metric name (e.g., `disk_usage`, `active_connections`, `replication_lag_bytes`).
- `observed_value` (float, required): Observed measurement. Must be between 0.0 and 100.0 for percentage metrics. Non-negative for byte/counter metrics.
- `threshold` (float, required): Alert trigger threshold. Must be non-negative.
- `severity` (string, required): Allowed values: `critical`, `warning`, `info`, `sev1`, `sev2`, `sev3`, `sev4`, `blocker`.
- `on_call_note` (string, optional): Context or symptoms observed by the human engineer (max 4096 chars).
- `timestamp` (string/float, optional): ISO 8601 string or Unix epoch timestamp.
- `metadata` (dict, optional): Arbitrary environment and cluster tags.
- `sync_mode` (boolean, optional): If `true`, waits for the agent pipeline to complete synchronously. Defaults to `false` (asynchronous queue submission).

### 3.2 Backward-Compatible Ingestion (`IncidentSubmissionRequest`)

To ensure backward compatibility with Member 4's evaluation harnesses and Locust load tests, the gateway also natively accepts the legacy schema:

```json
{
  "alert_payload": "Host postgres-primary-01 disk usage at 88% and climbing steadily. Table and index sizes are not growing.",
  "on_call_notes": "disk filling, cause unknown. Investigating replication lag.",
  "client_id": "locust_load_test"
}
```

The validation layer dynamically normalizes this input into a validated `IncidentAlertRequest`.

### 3.3 Incident Submission Response (`IncidentSubmissionResponse`)

```json
{
  "run_id": "run_a4f910e527bc",
  "alert_id": "ALT-PG-DISK-001",
  "correlation_id": "corr_3e89bc1012ab",
  "status": "queued",
  "message": "Incident triage request validated and queued for asynchronous agent processing.",
  "created_at": "2026-11-14T12:05:00.123456+00:00",
  "result": null
}
```

### 3.4 Status Response (`IncidentStatusResponse`)

```json
{
  "run_id": "run_a4f910e527bc",
  "alert_id": "ALT-PG-DISK-001",
  "status": "processing",
  "created_at": "2026-11-14T12:05:00.123456+00:00",
  "updated_at": "2026-11-14T12:05:00.345678+00:00",
  "completed_at": null,
  "queue_duration_seconds": 0.0512,
  "execution_duration_seconds": null,
  "retry_count": 0,
  "error": null
}
```

### 3.5 Unified Final Result Response (`IncidentResultResponse`)

```json
{
  "run_id": "run_a4f910e527bc",
  "alert_id": "ALT-PG-DISK-001",
  "status": "completed",
  "symptom_class": "PostgreSQL Replication Slot WAL Retention",
  "probable_root_cause": "WAL segments accumulate in pg_wal because an inactive or stalled replication slot retains them, causing primary disk consumption despite constant table/index sizes.",
  "severity": "SEV1",
  "evidence": [
    "A replication slot ensures that the primary will retain WAL logs needed by the standby even when disconnected."
  ],
  "documentation_citations": [
    {
      "source": "postgresql_wal_replication.md",
      "section": "Chapter 26.2.5: Replication Slots and WAL Retention",
      "quoted_passage": "A replication slot ensures that the primary will retain WAL logs needed by the standby even when disconnected."
    }
  ],
  "recommended_actions": [
    "Check inactive replication slots via pg_replication_slots.",
    "Drop orphaned or disconnected replication slots: SELECT pg_drop_replication_slot('slot_name');",
    "Monitor pg_wal disk space utilization on primary node."
  ],
  "escalation_required": false,
  "escalation_reason": null,
  "confidence": 0.95,
  "routing_decision": "escalate_dba",
  "created_at": "2026-11-14T12:05:00.123456+00:00",
  "completed_at": "2026-11-14T12:05:01.456789+00:00",
  "cost": {
    "total_tokens": 320,
    "total_cost_dollars": 0.000078
  }
}
```

---

## 4. Multi-Tier Validation & Quarantine Layer

Alert validation is governed by `src/backend/validator.py` and `src/backend/quarantine.py`.

### Validation Pipeline:
1. **Size Boundary Enforcement:** Payloads exceeding 1MB are rejected immediately.
2. **Security & Destructive Command Defense:** 
   - Shell commands (`rm -rf`, `format c:`, `reboot`, `killall -9`, pipe to bash) are blocked outright.
   - SQL drop/truncate patterns (`DROP DATABASE`, `TRUNCATE TABLE`, `-- drop table`) are intercepted.
3. **Prompt Injection Guardrail:**
   - Evaluates input using Member 4's `injection_detector` (`src/agentops/guardrails/injection_detector.py`).
   - Instruction overrides (e.g., `ignore previous instructions`, `you are now root`) are quarantined with category `prompt_injection`.
4. **Pydantic Type & Invariant Validation:**
   - Database name validation against allowed engines.
   - Severity level validation against allowed enums.
   - Numeric range checks: Percentage metrics must strictly reside within `[0.0, 100.0]`. Thresholds must be non-negative.
   - Timestamp format validation (ISO 8601 parsing).

### Quarantine Mechanism:
- Any rejected payload is recorded in the `QuarantineStore`.
- **Secret Redaction:** Passwords, API keys, tokens, and credentials in the raw alert are recursively redacted (`[REDACTED]`) before persistence.
- Quarantined records receive a unique `quarantine_id` (`quar_<hex_12>`), a structured rejection reason, timestamp, client ID, and list of validation errors.
- **Queue Isolation:** Quarantined requests never enter the agent queue.
- **Reviewability:** On-call engineers can audit quarantined payloads via `GET /api/v1/incidents/quarantine` and `GET /api/v1/incidents/quarantine/{quarantine_id}`.

---

## 5. Asynchronous Processing & Redis Queue

### 5.1 Architecture & Graceful Fallback
- **Primary Queue:** Managed in `src/backend/queue.py` utilizing `redis.asyncio` and Redis lists (`RPUSH` / `BLPOP`).
- **Resilient Fallback:** If Redis is offline (e.g. during local offline testing or container boot sequence), the system immediately detects port unavailability within 0.05s and falls back to an in-memory `asyncio.Queue` without blocking or failing.
- **Heartbeat:** Workers write timestamp heartbeats to `/tmp/worker_heartbeat` (or Windows tempdir) for container liveness probes.

### 5.2 Bounded Retries with Exponential Backoff
The worker (`src/backend/worker.py`) wraps agent execution in a bounded retry loop:
- **Max Retries:** 3 attempts.
- **Backoff:** Exponential (`backoff = 0.5 * (2 ** (attempt - 1))`).
- **Retry Telemetry:** Increments `AGENT_RETRIES_TOTAL` metric with reason and logs structured retry events (`log_retry_event`).
- **Exhaustion:** If all retries fail, status transitions to `failed` and records the exact error details.

### 5.3 Idempotency Support
- Clients can provide an `Idempotency-Key` or `X-Idempotency-Key` header.
- The gateway checks whether a run already exists for this key. If found, it returns the existing `run_id` and cached status/result immediately, avoiding duplicate agent processing and redundant token costs.

---

## 6. Agent Integration & Service Adapter Interface

The backend connects to Member 3's multi-agent orchestrator through a clean adapter layer defined in `src/backend/agent_service.py`.

### 6.1 Integration Flow
1. Worker extracts incident parameters (`alert_id`, `database`, `metric`, `observed_value`, `threshold`, `severity`, `on_call_note`).
2. Adapter composes an alert narrative string for multi-agent consumption.
3. Invokes Member 3's `incident_orchestrator.process_incident(...)`.
4. Orchestrator executes:
   - Triage Agent (alert classification and severity).
   - Retrieval Agent (RAG runbook search over `./src/rag/corpus/`).
   - Verification Agent (evidence citation matching and grounding checks).
   - Security Output Filter (enforces human-advisory tone and strips remediation execution claims).
5. Adapter maps the orchestrator output into the unified `IncidentResultResponse` contract.
6. Worker saves the completed result to `RunStorage`.

### 6.2 Human-in-the-Loop Advisory Guarantee
The assistant strictly provides advisory diagnostic guidance. Under no circumstances does the backend execute shell commands, run migration scripts, or alter database DDL.

### 6.3 Mock Adapter for Offline Testing
A `MockAgentAdapter` is provided for isolated unit testing and offline development:
- Clearly flags output with `[MOCK]` prefixes.
- Simulates multi-agent responses without network dependencies.
- Can be swapped via `agent_service.set_adapter(MockAgentAdapter())`.

---

## 7. Observability & AgentOps Integration

The backend fully integrates with Member 4's AgentOps infrastructure:

### 7.1 Structured Logging
- Uses `src.agentops.logging.JSONFormatter` for single-line JSON output.
- Propagates `correlation_id_ctx` (from HTTP headers) and `run_id_ctx` across API and worker boundaries.
- Automatically redacts sensitive fields (`password`, `api_key`, `token`, `secret`).

### 7.2 OpenTelemetry Distributed Tracing
- Uses OpenTelemetry W3C tracecontext propagation.
- `TaskQueue.enqueue()` injects the active trace context into `_trace_carrier`.
- `AgentWorker` extracts the trace context on `dequeue()`, creating linked child spans across the asynchronous queue boundary.
- Traces export to Jaeger (`http://localhost:16686` / `http://jaeger:4317`).

### 7.3 Prometheus Metrics
The gateway exports metrics at `/metrics` and `/api/v1/metrics`:
- `http_requests_total`: API request counts partitioned by method, endpoint, and status code.
- `http_request_duration_seconds`: Histogram of endpoint response latency.
- `queue_depth_current`: Gauge tracking pending jobs in the queue.
- `worker_active_count`: Gauge tracking active worker processes.
- `incident_e2e_duration_seconds`: End-to-end incident triage pipeline latency.
- `agent_step_duration_seconds`: Latency of individual agent reasoning steps.
- `agent_retries_total`: Count of worker and agent retry events.
- `llm_token_usage_total` & `llm_cost_dollars_total`: Token usage and cumulative dollar cost tracking.

---

## 8. Verification and Test Suite Results

The backend includes a comprehensive automated test suite in `tests/`:

1. `tests/test_backend_api.py` (11 tests):
   - Health probes (`/health`, `/api/v1/health`, `/health/ready`, `/api/v1/ready`).
   - Prometheus metrics endpoint (`/metrics`, `/api/v1/metrics`).
   - Swagger OpenAPI specification accessibility (`/docs`, `/openapi.json`).
   - Asynchronous incident submission (`202 Accepted` with `run_id`).
   - Synchronous triage submission (`sync_mode=True`).
   - Backward-compatible raw alert format submission.
   - Validation failure quarantine and review API (`422 Unprocessable Content`).
   - Lifecycle status transitions (`queued` -> `processing` -> `completed`).
   - Non-existent run ID handling (`404 Not Found`).
   - Idempotency key deduplication.
   - Prompt injection attack blocking and quarantine.

2. `tests/test_backend_validation.py` (10 tests):
   - Valid structured alert normalization.
   - Missing required fields validation.
   - Unsupported database rejection (`oracle_db`, `mongodb`).
   - Invalid severity classification rejection.
   - Percentage metric range bounds enforcement (`[0.0, 100.0]`).
   - Negative threshold rejection.
   - Invalid timestamp format rejection.
   - Destructive command defense (`sudo rm -rf`).
   - Adversarial prompt injection defense.
   - Sensitive credential redaction in quarantine store.

3. `tests/test_backend_queue_worker.py` (4 tests):
   - Queue enqueue/dequeue with W3C OpenTelemetry trace context injection.
   - RunStorage status state machine transitions (`queued` -> `processing` -> `completed`).
   - Worker end-to-end processing.
   - Worker bounded retries (3 attempts) and failure state tracking.

4. `tests/test_backend_agent_service.py` (3 tests):
   - Real orchestrator adapter on Faculty Reference Scenario (PostgreSQL disk climbing while tables/indexes are stable -> WAL replication slot retention diagnosis).
   - Connection exhaustion incident triage.
   - Mock adapter isolated operation.

5. Existing Member 4 Test Suite (24 tests):
   - 100% preserved and passing without regressions.

**Overall Test Suite Result: 52 passed out of 52 tests (100% pass rate).**

---

## 9. How to Run and Test the Backend

### 9.1 Local Development Mode

Start the API Gateway:
```bash
uvicorn src.backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Start the Background Worker:
```bash
python -m src.backend.worker
```

### 9.2 Running Automated Tests

Run the complete test suite:
```bash
pytest -v tests
```

Run only Backend & API tests:
```bash
pytest -v tests/test_backend_api.py tests/test_backend_validation.py tests/test_backend_queue_worker.py tests/test_backend_agent_service.py
```

### 9.3 Docker Compose Deployment

Start all 7 services (API, Worker, Redis, ChromaDB, Prometheus, Grafana, Jaeger):
```bash
docker compose up --build -d
```

Scale worker processes:
```bash
docker compose up --build --scale agent-worker=3 -d
```

### 9.4 Manual API Verification (cURL Examples)

#### Submit a Valid Alert:
```bash
curl -X POST http://localhost:8000/api/v1/incidents \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-key-001" \
  -d '{
    "alert_id": "ALT-DEMO-01",
    "database": "postgresql",
    "database_version": "16",
    "metric": "disk_usage",
    "observed_value": 88.5,
    "threshold": 80.0,
    "severity": "warning",
    "on_call_note": "Host postgres-primary-01 disk usage climbing steadily. Table and index sizes are stable."
  }'
```

#### Query Run Status:
```bash
curl http://localhost:8000/api/v1/incidents/<run_id>
```

#### Query Triage Result:
```bash
curl http://localhost:8000/api/v1/incidents/<run_id>/result
```

#### Inspect Quarantined Alerts:
```bash
curl http://localhost:8000/api/v1/incidents/quarantine
```
