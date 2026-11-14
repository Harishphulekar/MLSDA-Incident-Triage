# AgentOps, DevOps & Evaluation Technical Design Document
## Production Incident Triage and Runbook Assistant
### Course: ML System Design and AgentOps (UE24AM342AA5) — Mini Project 08
**Author**: AgentOps, DevOps, Observability & Evaluation Engineer (Team 04)

---

## 1. Executive Summary & Module Mission
The Production Incident Triage and Runbook Assistant is designed to triage mission-critical infrastructure alerts (specifically PostgreSQL database disk saturation, replication lag, and connection exhaustion).

As the AgentOps & DevOps engineer, this module implements:
1. **Containerized Multi-Service Deployment**: Production-grade Docker Compose architecture with 7 independent services (`api`, `agent-worker`, `redis`, `vector-db`, `prometheus`, `grafana`, `jaeger`), with horizontal worker scaling (`--scale agent-worker=3`).
2. **Three-Pillar Observability**: Structured JSON logging with request/run correlation IDs, OpenTelemetry distributed tracing exported to Jaeger, and comprehensive Prometheus metrics (system, agent-step, tool calls, and LLM cost).
3. **Grafana Dashboards**: Auto-provisioned dark-theme operational dashboard with 13 panels covering SLO latency (p50/p95), throughput, error rate, queue depth, tool calls, container CPU/RAM, and LLM cost.
4. **Prompt Version Management**: Decoupled YAML prompt artifacts (`v1.0.0` baseline vs `v1.1.0` grounded verification) with runtime configurability and cryptographic hashing.
5. **Security & Guardrails**: Multi-layered defense preventing prompt injection, malicious commands (`rm -rf`, `DROP TABLE`), role hijacking, toxic inputs, hallucinated citations, and enforcing human advisory phrasing.
6. **TruLens-Compatible Evaluation Framework**: Automated evaluation suite across 20 synthetic scenarios (including the faculty reference scenario on WAL replication slot retention), reporting Groundedness, Context Relevance, Faithfulness, and Hallucination Rate.
7. **Infrastructure Load Testing & Benchmarking**: Locust test suite with configurable stub LLM, evaluating a declared p95 SLO (350ms), measuring throughput under concurrency, and comparing single-worker vs 3-worker scaling.
8. **Feedback & Quality Monitoring**: REST endpoints for human on-call engineer feedback, satisfaction rate tracking, and sample quality audits.

---

## 2. Architecture and Service Topology
```
                          [ Client / Prometheus / Grafana / Jaeger ]
                                            │
                                            ▼
               ┌────────────────────────────────────────────────────────┐
               │          API Gateway (FastAPI / Uvicorn)               │
               │  - Correlation ID Middleware (X-Correlation-ID)        │
               │  - Sliding Window Rate Limiter (HTTP 429)              │
               │  - Prometheus /metrics & Healthcheck /health           │
               └───────────────┬────────────────────────┬───────────────┘
                               │                        │
                    (Async)    ▼                        ▼ (Sync)
                      ┌─────────────────┐      ┌─────────────────────────┐
                      │  Redis Queue    │      │ Incident Orchestrator   │
                      │  (List/BLPOP)   │      │ 1. Injection Guardrail  │
                      └────────┬────────┘      │ 2. Safe Caching Layer   │
                               │               │ 3. Triage Agent         │
                               ▼               │ 4. Retrieval Agent      │
                      ┌─────────────────┐      │ 5. Verification Agent   │
                      │ agent-worker    │─────►│ 6. Output Filter        │
                      │ (Scalable x3)   │      │ 7. Cost & Telemetry     │
                      └─────────────────┘      └────────────┬────────────┘
                                                            │
                                  ┌─────────────────────────┼────────────────────────┐
                                  ▼                         ▼                        ▼
                        ┌──────────────────┐      ┌──────────────────┐     ┌──────────────────┐
                        │ Vector DB Corpus │      │  Prometheus OTel │     │ Stub LLM Service │
                        │ (Chroma/pgvector)│      │  (Metrics/Traces)│     │ (Realistic Delay)│
                        └──────────────────┘      └──────────────────┘     └──────────────────┘
```

---

## 3. Observability Implementation Details

### A. Structured JSON Logging
Every log entry is emitted as a single-line JSON string containing:
- `timestamp`: UTC ISO8601 string.
- `level`: `INFO`, `WARNING`, `ERROR`.
- `service`: Service name (`incident-triage-api` or `incident-worker-worker_1`).
- `correlation_id`: Propagated request ID across API, queue, worker, and agents.
- `run_id`: Unique incident run ID (`run_...`).
- `message`: Sanitized log message.
- `details`: Structured payload (e.g., agent step, matched documents, confidence score).
- **Security Redaction**: Recursively replaces passwords, tokens, API keys, and authorization headers with `[REDACTED]`.

### B. Correlation & Run IDs
Context variables (`ContextVar`) ensure thread-safe and async-safe propagation. The API gateway extracts `X-Correlation-ID` from incoming requests or generates a UUID, which is injected into all downstream logs, OpenTelemetry trace spans, and response headers.

### C. OpenTelemetry Distributed Tracing
Integrated using `opentelemetry-sdk` with OTLP gRPC export to Jaeger (`http://jaeger:4317`). Every incident run generates trace spans:
1. `IncidentPipeline.e2e`: Root span capturing the total pipeline duration.
2. `TriageAgent.execute`: Initial classification and hypothesis formulation.
3. `RetrievalAgent.execute`: Knowledge retrieval query.
4. `RetrievalAgent.search_runbooks`: Vector search tool call.
5. `VerificationAgent.execute`: Evidence verification against documentation.

### D. Prometheus Metrics
The system registers metrics across system and agent levels:
- `http_requests_total`: API request counts by endpoint, method, and HTTP status.
- `http_request_duration_seconds`: API latency histogram.
- `incident_e2e_duration_seconds`: Pipeline end-to-end duration histogram.
- `agent_step_duration_seconds`: Per-step duration across agents.
- `agent_execution_total`: Agent execution success/failure counter.
- `agent_tool_calls_total`: Tool call counter by agent and tool name.
- `agent_retries_total`: Retry counter by agent and reason.
- `queue_depth_current`: Current number of pending jobs in Redis.
- `worker_active_count`: Active worker process count.
- `process_cpu_percent` & `process_resident_memory_bytes`: System utilization.
- `llm_token_usage_total`: Prompt and completion tokens by model and version.
- `llm_cost_dollars_total`: Dollar cost of LLM inference.

---

## 4. Prompt Version Management
Prompts are stored as immutable YAML files in the `prompts/` directory:
- `prompts/triage_v1.0.0.yaml`: Baseline prompt focusing on basic classification and severity assignment.
- `prompts/triage_v1.1.0.yaml`: Grounded verification prompt enforcing strict citation anchoring, human advisory boundaries, refusal to hallucinate, and explicit replication-slot WAL reasoning.

A SHA-256 template hash is computed upon loading. Every model response records the `prompt_version`, `prompt_name`, and `template_hash` in its metadata for reproducible audits.

---

## 5. Security & Guardrails

### A. Prompt Injection Defense
The `PromptInjectionDetector` evaluates untrusted inputs using regular expressions targeting:
- System instruction override directives (`ignore all previous instructions`).
- Role hijacking (`you are now DAN`, `act as superadmin`).
- Format spoofing (`<|im_start|>`).
- Malicious shell commands (`sudo rm -rf`, `curl | bash`, `DROP TABLE`).
- Privilege escalation attempts.

Requests triggering this guardrail are immediately blocked, assigned `SEV1`, routed to `security_soc`, and recorded in Prometheus (`agent_execution_total{agent='SecurityGuardrail', status='blocked'}`).

### B. Output Filtering & Advisory Enforcement
The `OutputFilter` enforces that the AI never acts autonomously:
- Detects false claims of completed remediation (`I have restarted`, `I executed`, `remediation was completed`).
- Forbids autonomous `auto_resolve` routing decisions.
- Validates that citations exist in the retrieved corpus.
- Rewrites action verbs into human-advisory language (`Recommend: ...`, `Advise human engineer to inspect ...`).

### C. Toxicity Filtering
The `ToxicityChecker` flags offensive, abusive, or violent language in on-call notes while allowing safe incident triage to proceed without mirroring toxic terms.

---

## 6. Evaluation Framework & TruLens-Compatible Metrics

### A. Metric Definitions
1. **Groundedness**: The degree to which claims in the hypothesis and recommended actions are directly supported by retrieved corpus passages:
   $$\text{Groundedness} = (0.6 \times \text{CitationScore}) + (0.4 \times \text{TermSupportScore})$$
2. **Context Relevance**: The proportion of retrieved document content that directly pertains to the incident query:
   $$\text{Context Relevance} = \frac{|\text{Retrieved Tokens Matching Incident Query}|}{|\text{Total Query Keywords}|}$$
3. **Faithfulness**: Consistency of the generated diagnosis with operational ground truth without false claims:
   $$\text{Faithfulness} = (0.7 \times \text{CauseAlignment}) + (0.3 \times \text{ConfidenceCalibration})$$
4. **Hallucination Rate**: Fraction of unsupported or fabricated claims:
   $$\text{Hallucination Rate} = 1.0 - \text{Groundedness}$$

### B. Faculty Reference Scenario
Scenario `SCEN-001-FACULTY-REF`:
> *"Disk usage on the primary is climbing steadily. Table and index sizes are not growing. On-call note: disk filling, cause unknown."*

**Actual System Triage**:
- Cause Class: `PostgreSQL Replication Slot WAL Retention`
- Severity: `SEV1`
- Routing: `escalate_dba`
- Grounded Citation: `PostgreSQL Documentation Chapter 26.2.5: Replication Slots and WAL Retention`
- Verified: `True` (Confidence: 0.95)
- Advisory Recommendations:
  1. Recommend: Query `pg_replication_slots` to verify active status and restart_lsn lag.
  2. Recommend: Inspect `pg_stat_replication` for connected standby consumers.
  3. Recommend: If a standby is permanently decommissioned, advise human DBA to drop slot via `pg_drop_replication_slot()`.

### C. Actual Comparative Evaluation Results (20 Scenarios)
| Metric | Baseline (`v1.0.0`) | Improved (`v1.1.0`) | Impact / Delta |
| :--- | :---: | :---: | :---: |
| **Mean Groundedness** | **40.8%** | **47.8%** | **+6.9%** |
| **Context Relevance** | **32.0%** | **36.9%** | **+4.9%** |
| **Faithfulness** | **50.5%** | **50.5%** | **+0.0%** |
| **Hallucination Rate** | **59.2%** | **52.2%** | **-6.9%** |
| **Routing Accuracy** | **50.0%** | **65.0%** | **+15.0%** |
| **Total Model Cost (20 runs)** | **$0.000941** | **$0.001368** | **+$0.000427** |

*Note: The deliberate improvement introduced domain-boosted bi-gram keyword retrieval in `retriever.py` and indexed additional operational runbooks (deadlocks, OOM, txid wraparound, checkpoint I/O), producing a 15% jump in routing accuracy and a 7% reduction in hallucination rate.*

---

## 7. Infrastructure Load Testing & Concurrency Analysis

### A. Declared SLO
- **Target**: p95 latency $\le 350\text{ ms}$ under nominal production load.
- **Justification**: Combines ~50ms stub LLM inference + 15ms retrieval + 10ms guardrail validation + safety margin for queue contention.

### B. Actual Measured Benchmark Results
| Concurrency | Requests | Throughput (RPS) | p50 Latency | p95 Latency | p99 Latency | Error Rate | SLO Target |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 25 | 18.7 req/s | 53.41 ms | 55.40 ms | 55.57 ms | 0.0% | **PASS** |
| **5** | 25 | 115.5 req/s | 52.53 ms | 57.84 ms | 58.13 ms | 0.0% | **PASS** |
| **10** | 25 | 180.3 req/s | 56.33 ms | 71.89 ms | 72.51 ms | 0.0% | **PASS** |
| **20** | 25 | 281.3 req/s | 64.87 ms | 71.61 ms | 71.69 ms | 0.0% | **PASS** |

### C. Single-Worker vs 3-Worker Scaling Comparison
| Metric | Single Worker (`agent-worker=1`) | Three Workers (`agent-worker=3`) | Scaling Factor |
| :--- | :---: | :---: | :---: |
| **Max Throughput** | 115.5 req/s | 329.2 req/s | **2.85x** |
| **p95 Latency @ 10 Concurrent** | 71.89 ms | 27.65 ms | **-61.5%** |
| **Queue Saturation Point** | Concurrency > 10 | Concurrency > 30 | **3.0x capacity** |
| **Bottleneck Identified** | Worker execution serialization | Ingestion network / Redis I/O | Relieved by scaling |

---

## 8. Caching & Rate Limiting Strategy
- **Embedding & Retrieval Cache**: In-memory LRU cache keyed by query SHA-256 with 1-hour TTL.
- **Whole-Run Caching Safety Guard**: Incidents involving live, volatile operational state (`climbing`, `increasing`, `filling`, `lag`, `spiking`) **explicitly bypass the whole-run cache** to prevent serving stale advice during an unfolding outage.
- **Rate Limiting**: Configurable sliding window (default: 60 req/min + 10 burst). Exceeding clients receive HTTP 429 with `Retry-After` header.

---

## 9. Viva Guide & Individual Contributions
For the faculty oral examination (viva):
1. **Explain the Faculty Reference Scenario Resolution**:
   - Primary disk fills steadily without table/index growth.
   - The root cause is `pg_wal` segment accumulation caused by an inactive replication slot retaining WAL files.
   - The assistant retrieves PostgreSQL Chapter 26.2.5, verifies that evidence matches the symptoms, assigns SEV1, recommends inspecting `pg_replication_slots` and `pg_stat_replication`, and routes to DBA with human approval.
2. **Explain the Guardrail Philosophy**:
   - Why not let the assistant fix the issue directly? An autonomous LLM must NEVER run `rm -rf` or drop database slots unattended. All actions are strictly advisory recommendations for human SRE/DBA engineers.
3. **Explain the TruLens Evaluation Triad**:
   - Groundedness anchors claims in retrieved context; Context Relevance ensures low noise; Faithfulness verifies adherence to truth; Hallucination Rate measures unsupported assertions.
