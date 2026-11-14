# MLSDA-Incident-Triage

**MLSDA Mini Project 08 – Production Incident Triage and Runbook Assistant**

**Course:** ML System Design and AgentOps (UE24AM342AA5)  
**Team:** Team 04

---

## 1. Project Overview

The **Production Incident Triage and Runbook Assistant** is an intelligent on-call assistant designed to help triage production infrastructure alerts, including PostgreSQL database disk saturation, replication lag, connection spikes and deadlock waves.

It ingests raw alerts, retrieves relevant runbooks and PostgreSQL documentation, performs multi-agent evidence verification, and generates cited advisory recommendations for human SRE and DBA engineers.

The system particularly addresses incidents where the underlying cause is not immediately obvious, such as PostgreSQL replication-slot WAL retention causing disk usage to increase while table and index sizes remain stable.

## 2. Team Architecture and Service Boundaries

The project is organized into four collaborative modules.

### Module 1: Backend and API (`src/backend/`)

- FastAPI gateway for incident ingestion, schema validation and response serialization.
- Redis-backed asynchronous task queue.
- Background worker for incident processing.

### Module 2: Corpus and RAG (`src/rag/`)

- PostgreSQL technical documentation, including replication slots and WAL retention.
- Incident runbooks covering disk saturation, replication lag, connection exhaustion and other operational issues.
- Retrieval interface with domain-weighted keyword scoring.

### Module 3: Multi-Agent and ML (`src/agents/`)

- **Triage Agent:** Classifies alerts, assigns severity (SEV1–SEV4), and forms preliminary hypotheses.
- **Retrieval Agent:** Searches the knowledge corpus for relevant technical evidence and runbooks.
- **Verification Agent:** Checks whether diagnostic claims are supported by retrieved evidence and flags insufficient evidence.
- **Orchestrator:** Coordinates the incident-processing pipeline and agent execution.

### Module 4: AgentOps, DevOps, Observability and Evaluation (`src/agentops/`)

- Docker Compose deployment configuration.
- Prometheus metrics, Grafana dashboards and Jaeger distributed tracing.
- Structured logging and correlation IDs.
- Prompt version management and security guardrails.
- Evaluation scenarios, metric calculations and prompt comparisons.
- Load-testing scripts, caching, rate limiting, feedback and cost tracking.

## 3. Project Structure

```text
MLSDA-Incident-Triage/
├── docs/
│   ├── AGENTOPS_SYSTEM_DESIGN.md
│   └── AGENTOPS_AUDIT_REPORT.md
├── grafana/
│   ├── dashboards/
│   └── provisioning/
├── locust/
├── prompts/
├── prometheus/
├── src/
│   ├── agentops/
│   │   ├── evaluation/
│   │   └── guardrails/
│   ├── agents/
│   ├── backend/
│   └── rag/
│       └── corpus/
├── tests/
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.worker
├── requirements.txt
├── .env.example
└── README.md
```

## 4. Docker Setup and Deployment

The Docker Compose configuration defines seven services:

| Service | Purpose | Port |
|---|---|---|
| `api` | FastAPI application | 8000 |
| `agent-worker` | Background incident processing | — |
| `redis` | Message queue and state store | 6379 |
| `vector-db` | ChromaDB vector database | 8001 |
| `prometheus` | Metrics collection | 9090 |
| `grafana` | Monitoring dashboards | 3000 |
| `jaeger` | Distributed tracing | 16686, 4317, 4318 |

### Start the services

```bash
docker compose up --build -d
```

### Check service status

```bash
docker compose ps
```

**Note:** These are configured deployment services. Actual container startup and health must be verified in an environment with Docker running.

## 5. Environment Configuration

Configuration is supplied through environment variables. Refer to `.env.example`.

Create a local environment file:

```bash
cp .env.example .env
```

Important configuration parameters include:

- `ACTIVE_PROMPT_VERSION`: Active prompt version (`v1.0.0` or `v1.1.0`).
- `LLM_PROVIDER`: Model provider, including the stub provider for offline testing.
- `STUB_MODEL_LATENCY_MS`: Simulated inference delay.
- `RATE_LIMIT_ENABLED`: Enables request rate limiting.
- `RATE_LIMIT_REQUESTS_PER_MINUTE`: Request quota per minute.
- `ENABLE_TRACING`: Enables distributed tracing.

Do not commit `.env` or real API credentials to GitHub.

## 6. Prometheus and Grafana Monitoring

Configured monitoring endpoints:

- **Prometheus:** http://localhost:9090
- **Application metrics:** http://localhost:8000/metrics
- **Grafana:** http://localhost:3000

The Grafana dashboard includes panels for:

- Overall system health.
- p50 and p95 latency.
- Throughput and API error rate.
- Agent success rate and execution latency.
- Tool calls and retry rate.
- Queue depth.
- Process CPU and memory.
- LLM cost tracking.

The dashboard and provisioning configuration are located under `grafana/`.

## 7. Jaeger Distributed Tracing

**Jaeger Web UI:** http://localhost:16686

OpenTelemetry instrumentation is configured to export traces to Jaeger.

Important spans include:

- `IncidentPipeline.e2e`
- `TriageAgent.execute`
- `RetrievalAgent.execute`
- `RetrievalAgent.search_runbooks`
- `VerificationAgent.execute`

Correlation IDs and incident run IDs help trace individual incident-processing executions.

## 8. Evaluation Dataset

The evaluation dataset is located at:

```text
src/agentops/evaluation/scenarios.json
```

It contains 20 synthetic incident scenarios covering:

- PostgreSQL disk growth and WAL retention.
- WAL archiver failures.
- Standby replication lag.
- Connection exhaustion.
- Slow queries and sequential scans.
- Deadlocks and lock contention.
- Linux OOM events.
- Transaction ID wraparound.
- Checkpoint I/O spikes.
- Redis dependency failures.
- Network partition scenarios.
- Ambiguous incidents requiring human escalation.
- Unsupported hardware failures.
- Prompt injection attempts.
- Insufficient retrieval evidence.
- Toxic on-call notes.

The faculty reference scenario is:

`SCEN-001-FACULTY-REF`

It represents a primary database whose disk usage is increasing while table and index sizes remain stable, requiring investigation of alternative causes such as WAL retention.

## 9. Running the Evaluation

Run the evaluation across all 20 scenarios:

```bash
python -m src.agentops.evaluation.eval_runner --prompt-version v1.1.0 --output eval_results_v1.1.0.json
```

The evaluation runner generates metric summaries and saves detailed results in JSON and CSV formats.

**Evaluation note:** The current implementation uses deterministic, heuristic-based metric calculations with TruLens-compatible metric naming. These results should be interpreted as preliminary evaluation results, not as independently validated semantic LLM-as-a-judge scores.

## 10. Comparing Prompt Versions

The project includes two prompt versions:

- `v1.0.0`: Baseline prompt.
- `v1.1.0`: Improved prompt.

Evaluate the baseline:

```bash
python -m src.agentops.evaluation.eval_runner --prompt-version v1.0.0 --output eval_results_v1.0.0.json
```

Evaluate the improved prompt:

```bash
python -m src.agentops.evaluation.eval_runner --prompt-version v1.1.0 --output eval_results_v1.1.0_improved.json
```

Compare the results:

```bash
python -m src.agentops.evaluation.eval_runner --compare eval_results_v1.0.0.json eval_results_v1.1.0_improved.json
```

The comparison helps assess changes in groundedness, context relevance, faithfulness and hallucination-related metrics.

## 11. Load Testing and Performance Evaluation

The project contains a custom benchmark harness:

```bash
python -m locust.run_load_test
```

It is designed to measure:

- Requests per second.
- p50 and p95 latency.
- Error rates.
- Concurrent request handling.

An interactive Locust test can also be started with:

```bash
locust -f locust/locustfile.py --host http://localhost:8000
```

Open:

http://localhost:8089

**Important:** The custom benchmark harness and the interactive Locust test are separate. Performance results generated by the custom harness should not be described as actual Locust measurements unless Locust has been installed and the test has been run successfully.

## 12. Scaling Background Workers

The Compose configuration supports scaling the worker service:

```bash
docker compose up --build --scale agent-worker=3 -d
```

Verify worker instances:

```bash
docker compose ps agent-worker
```

Actual horizontal scaling must be verified with Docker running.

## 13. Running Automated Tests

Run the test suite:

```bash
pytest -v tests
```

The tests cover:

- Docker and provisioning configuration syntax.
- Structured JSON logging and secret sanitization.
- Correlation ID propagation.
- Prometheus metric definitions.
- Prompt version management.
- Prompt injection defense and output filtering.
- Toxicity checks.
- Token and cost tracking.
- Retrieval caching.
- Rate limiting.
- Stub LLM behavior.
- Evaluation metric calculations.
- Feedback persistence.

## 14. Security Considerations and Limitations

- **Prompt injection defense:** The current heuristic-based detection protects against known instruction override patterns but may not detect sophisticated or obfuscated attacks.
- **Human-in-the-loop:** The assistant provides advisory recommendations. It must not autonomously execute shell commands or database DDL.
- **Citation validation:** Current citation validation uses substring matching against retrieved context and may not recognize every valid paraphrase.
- **Evaluation:** Heuristic metrics are useful for preliminary comparisons but do not replace independent semantic evaluation.
- **Deployment:** Docker-based deployment and live load testing require verification in a suitable runtime environment.

## 15. Audit and Implementation Documentation

Additional technical documentation:

- `docs/BACKEND_API_DESIGN.md` — Backend & API Gateway architecture, schema contracts, validation, quarantine, queue, worker, and agent adapter design.
- `docs/AGENTOPS_SYSTEM_DESIGN.md` — AgentOps architecture and design.
- `docs/AGENTOPS_AUDIT_REPORT.md` — Implementation audit, verification status and identified limitations.

## 16. Backend and API Gateway (`src/backend/`)

Implemented by **Member 1 (Backend & API Engineer)**.

### 16.1 Architecture Overview

The FastAPI gateway coordinates alert ingestion, validation, quarantine, asynchronous task dispatching, and run status tracking:

```text
Alert Ingestion -> Validation & Security Scan -> Run ID Generation -> Redis Queue -> Background Worker -> Agent Service Adapter -> Run Storage -> Status & Results API
                        | (if invalid/suspicious)
                        v
                 Quarantine Store (HTTP 422 Rejection)
```

### 16.2 API Endpoints

- `POST /api/v1/incidents`: Ingests and validates infrastructure alerts. Queues valid jobs asynchronously and returns `202 Accepted` with a unique `run_id` (or executes synchronously if `sync_mode: true`).
- `GET /api/v1/incidents/{run_id}`: Retrieves run lifecycle status (`queued`, `processing`, `completed`, `failed`, `escalated`).
- `GET /api/v1/incidents/{run_id}/result`: Retrieves the structured multi-agent triage result (returns `202 Accepted` while in-flight, `200 OK` when completed).
- `GET /api/v1/incidents/quarantine`: Lists quarantined malformed or suspicious alerts for SRE security review.
- `GET /api/v1/incidents/quarantine/{quarantine_id}`: Inspects a specific quarantined record with safely redacted secrets.
- `GET /api/v1/health` & `/health`: Container liveness probes.
- `GET /api/v1/ready` & `/health/ready`: Readiness probe verifying Redis connectivity, queue depth, and active prompt versions.
- `GET /api/v1/metrics` & `/metrics`: Prometheus metrics scrape endpoint.
- `POST /api/v1/feedback`: Submits human engineer evaluation feedback.
- `GET /api/v1/feedback/stats`: Returns aggregate feedback statistics.
- `GET /api/v1/prompts`: Lists prompt template versions.

### 16.3 Request and Response Payload Formats

#### Standard Incident Alert Request:
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
  "metadata": {"cluster": "prod-us-east-1"},
  "client_id": "sre-monitoring",
  "sync_mode": false
}
```

#### Incident Submission Response:
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

#### Final Structured Agent Result:
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
  "cost": {"total_tokens": 320, "total_cost_dollars": 0.000078}
}
```

### 16.4 Validation, Quarantine, and Security

- **Strict Validation:** Required fields, allowed database engines (`postgresql`, `postgres`), categorical severities (`critical`, `warning`, `info`, `sev1`–`sev4`), metric ranges (`0.0`–`100.0` for percentages, positive thresholds), and ISO 8601 timestamps.
- **Security Defense:** Destructive shell/SQL commands (`sudo rm -rf`, `DROP DATABASE`) and prompt injection attacks (`ignore previous instructions`, `grant all privileges`) are intercepted before reaching the queue.
- **Quarantine Store:** Malformed or suspicious alerts are logged, sanitized of passwords/API keys, assigned a `quarantine_id`, and stored for SRE review. The API returns `422 Unprocessable Entity` with quarantine details.
- **Human-in-the-Loop:** All recommended actions are strictly advisory recommendations for human engineers. The backend never autonomously executes shell scripts or database DDL.

### 16.5 Asynchronous Processing, Queue, and Worker

- **Queue Architecture:** Redis-backed task queue (`src/backend/queue.py`) with automatic fallback to an in-memory asynchronous queue when Redis is offline.
- **Worker Process:** Scalable background worker (`src/backend/worker.py`) that dequeues tasks, updates run lifecycle statuses, and invokes multi-agent triage.
- **Bounded Retries:** Implements 3 bounded retries with exponential backoff (`0.5s`, `1.0s`, `2.0s`) on transient errors, recording retry metrics and events.
- **Idempotency:** Supports `Idempotency-Key` headers to prevent redundant agent processing and token costs.
- **Trace Context Propagation:** Automatically injects and extracts W3C OpenTelemetry trace context across the asynchronous queue boundary to preserve distributed Jaeger traces.

### 16.6 Running the Backend & Tests

Start the API Gateway:
```bash
uvicorn src.backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Start the Background Worker:
```bash
python -m src.backend.worker
```

Run Automated Tests:
```bash
pytest -v tests
```

Access Swagger Documentation:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

---

**Project:** Production Incident Triage and Runbook Assistant  
**Course:** ML System Design and AgentOps  
**Mini Project:** 08  
**Team:** Team 04