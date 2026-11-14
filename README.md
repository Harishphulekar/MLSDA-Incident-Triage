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

- `docs/AGENTOPS_SYSTEM_DESIGN.md` — AgentOps architecture and design.
- `docs/AGENTOPS_AUDIT_REPORT.md` — Implementation audit, verification status and identified limitations.

---

**Project:** Production Incident Triage and Runbook Assistant  
**Course:** ML System Design and AgentOps  
**Mini Project:** 08  
**Team:** Team 04