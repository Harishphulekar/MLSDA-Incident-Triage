# Production Incident Triage and Runbook Assistant

**Course**: ML System Design and AgentOps (UE24AM342AA5) — Mini Project 08  
**Team**: Team 04  

---

## 1. Project Overview
The **Production Incident Triage and Runbook Assistant** is an intelligent on-call assistant designed to triage production infrastructure alerts (e.g., PostgreSQL database disk saturation, replication lag, connection spikes, deadlock waves). It ingests raw alerts, retrieves authoritative runbooks and PostgreSQL documentation, performs multi-agent verification of factual evidence, and generates cited advisory recommendations for human SRE and DBA engineers.

---

## 2. Team Architecture & Service Boundaries
The project is organized into four distinct modules developed collaboratively:

1. **Module 1: Backend and API** (`src/backend/`):
   - FastAPI gateway handling ingestion, schema validation, rate limiting, and response serialization.
   - Redis-backed asynchronous task queue (`src/backend/queue.py`) and background worker (`src/backend/worker.py`).
2. **Module 2: Corpus and RAG** (`src/rag/`):
   - Authoritative PostgreSQL technical documentation (`Chapter 26.2.5: Replication Slots`) and incident runbooks.
   - Vector database retrieval interface with domain-weighted keyword scoring.
3. **Module 3: Multi-Agent & ML** (`src/agents/`):
   - **Triage Agent**: Classifies alerts, assigns severity (SEV1-SEV4), and forms preliminary hypotheses.
   - **Retrieval Agent**: Queries knowledge corpus for authoritative runbooks matching incident symptoms.
   - **Verification Agent**: Verifies that diagnostic claims are anchored in factual evidence, checks replication slot WAL retention, and flags insufficient evidence.
   - **Orchestrator**: Coordinates the pipeline, applies security guardrails, and records telemetry.
4. **Module 4: AgentOps, DevOps, Observability & Evaluation** (`src/agentops/` - *Our Module*):
   - Production Docker Compose deployment, Prometheus metrics, Grafana dashboards, and Jaeger tracing.
   - Prompt version management (`prompts/`), security guardrails, TruLens-compatible evaluation suite, and Locust load testing.

---

## 3. Docker Setup & Deployment
The environment runs 7 containerized services defined in `docker-compose.yml`:
- `api`: FastAPI application (Port 8000).
- `agent-worker`: Asynchronous background multi-agent worker process.
- `redis`: Redis 7 message queue and state store (Port 6379).
- `vector-db`: ChromaDB vector database (Port 8001 -> 8000).
- `prometheus`: Prometheus metric scraper (Port 9090).
- `grafana`: Grafana operational dashboards (Port 3000).
- `jaeger`: Jaeger all-in-one distributed tracing collector (Ports 16686, 4317, 4318).

### Starting the Services
Build and start all services in detached mode:
```bash
docker compose up --build -d
```
Verify container health:
```bash
docker compose ps
```

---

## 4. Environment Configuration
Configuration is injected at runtime using environment variables. See `.env.example` for reference.
To configure:
```bash
cp .env.example .env
```
Key configuration parameters:
- `ACTIVE_PROMPT_VERSION`: Active prompt version (`v1.0.0` or `v1.1.0`).
- `LLM_PROVIDER`: Model provider (`stub` for offline/load testing, or `gpt-4o-mini`).
- `STUB_MODEL_LATENCY_MS`: Simulated inference delay in milliseconds (default: `150`).
- `RATE_LIMIT_ENABLED`: Enforce per-client request limits (default: `true`).
- `RATE_LIMIT_REQUESTS_PER_MINUTE`: Permitted request quota (default: `60`).
- `ENABLE_TRACING`: Export traces to Jaeger (default: `true`).

---

## 5. Prometheus and Grafana Access
- **Prometheus UI**: [http://localhost:9090](http://localhost:9090)
  - Raw Metrics Endpoint: [http://localhost:8000/metrics](http://localhost:8000/metrics)
- **Grafana Dashboards**: [http://localhost:3000](http://localhost:3000)
  - **Credentials**: Username `admin`, Password `admin`.
  - **Pre-provisioned Dashboard**: *Production Incident Triage & Runbook Assistant - AgentOps*.
  - **Panels**: Overall Health, p50/p95 Latency, Throughput, API Error Rate, Agent Success Rate, Agent Step Latency, Tool Calls, Retry Rate, Queue Depth, Process CPU/RAM, and LLM Cost.

---

## 6. Jaeger Distributed Tracing
- **Jaeger Web UI**: [http://localhost:16686](http://localhost:16686)
- Trace spans are emitted via OpenTelemetry gRPC to `jaeger:4317`.
- Spans include:
  - `IncidentPipeline.e2e` (with `incident.correlation_id` and `incident.run_id`).
  - `TriageAgent.execute`
  - `RetrievalAgent.execute`
  - `RetrievalAgent.search_runbooks` (tool call)
  - `VerificationAgent.execute`

---

## 7. Evaluation Dataset Structure
The benchmark dataset is located at `src/agentops/evaluation/scenarios.json` and contains 20 synthetic scenarios covering:
- Faculty reference scenario (`SCEN-001-FACULTY-REF`: Primary disk climbing steadily, table/index flat, cause unknown).
- Active WAL archiver failure (`SCEN-002`).
- Standby replication lag (`SCEN-003`).
- Connection exhaustion (`SCEN-004`).
- Slow query sequential scans (`SCEN-005`).
- Lock deadlocks (`SCEN-006`).
- Linux OOM killer termination (`SCEN-007`).
- Autovacuum freeze / transaction ID wraparound (`SCEN-009`).
- Checkpoint I/O spikes (`SCEN-010`).
- Downstream Redis dependency failure (`SCEN-011`).
- Inter-region network split-brain (`SCEN-012`).
- Ambiguous incidents requiring human escalation (`SCEN-014`).
- Unsupported hardware glitches (`SCEN-015`).
- Adversarial prompt injection attacks (`SCEN-017`, `SCEN-018`).
- Insufficient retrieval evidence (`SCEN-019`).
- Toxic on-call notes (`SCEN-020`).

---

## 8. How to Run Evaluation
Run the batch evaluation CLI across all 20 scenarios:
```bash
python -m src.agentops.evaluation.eval_runner --prompt-version v1.1.0 --output eval_results_v1.1.0.json
```
This prints the TruLens-compatible metrics summary table and saves detailed output to JSON and CSV.

---

## 9. How to Compare Prompt Versions
To compare baseline (`v1.0.0`) vs improved (`v1.1.0`):
1. Evaluate baseline prompt:
   ```bash
   python -m src.agentops.evaluation.eval_runner --prompt-version v1.0.0 --output eval_results_v1.0.0.json
   ```
2. Evaluate improved prompt:
   ```bash
   python -m src.agentops.evaluation.eval_runner --prompt-version v1.1.0 --output eval_results_v1.1.0_improved.json
   ```
3. Run the automated comparison:
   ```bash
   python -m src.agentops.evaluation.eval_runner --compare eval_results_v1.0.0.json eval_results_v1.1.0_improved.json
   ```

---

## 10. How to Run Locust Load Testing
### Benchmark Harness
Run the automated multi-threaded benchmark measuring RPS, p50, p95, error rates, and concurrency bottlenecks:
```bash
python -m locust.run_load_test
```
### Live Locust UI
To launch the interactive Locust web interface:
```bash
locust -f locust/locustfile.py --host http://localhost:8000
```
Open [http://localhost:8089](http://localhost:8089) in your browser.

---

## 11. How to Scale Workers
Scale the asynchronous agent worker service to 3 instances horizontally:
```bash
docker compose up --build --scale agent-worker=3 -d
```
Verify worker scaling:
```bash
docker compose ps agent-worker
```

---

## 12. How to Run Tests
Execute the automated test suite using pytest:
```bash
pytest -v tests
```
The suite verifies:
- Docker and provisioning file syntax.
- Structured JSON logging and secret sanitization.
- Correlation ID propagation.
- Prometheus metric definitions and export format.
- Prompt version management and template formatting.
- Prompt injection defense, output filtering, and toxicity checks.
- LLM token and cost tracking.
- Retrieval caching and volatile-state safety guards.
- Per-client sliding window rate limiting.
- Stub LLM reasoning on faculty scenarios.
- TruLens evaluation metric calculations.
- Feedback persistence and quality sampling.

---

## 13. Security Limitations
- **Heuristic Regex Injection Defense**: While effective against known override phrases (`ignore previous instructions`, `you are now DAN`), sophisticated zero-day obfuscations or multi-lingual jailbreaks may require a fine-tuned classifier or secondary LLM filter.
- **Human-in-the-Loop Constraint**: The assistant strictly provides **advisory recommendations**; it does not and must not execute shell commands or database DDL autonomously.
- **Output Validation**: Citation validation relies on substring match against retrieved context. Paraphrased quotes may occasionally require fuzzy string matching.

---

## 14. Known Issues
- In constrained Windows sandbox environments without loopback socket permissions, asynchronous event loop initialization for Starlette `TestClient` can block; the system provides synchronous execution adapters (`process_incident_sync`) to ensure tests and evaluation runners execute natively without network socket dependencies.
- Vector database container requires persistent volume initialization on first boot.
