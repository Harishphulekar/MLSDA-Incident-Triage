# Production Incident Severity and Escalation Policy

**Policy Version:** 1.0.0  
**Effective Date:** 2026-11-15  
**Target Environment:** PostgreSQL 16 Enterprise Production  
**Authority:** SRE & Database Reliability Engineering  

---

## 1. Purpose & Scope

This policy governs the categorization, triage, investigation, evidence requirements, and human escalation protocols for all production incidents involving database infrastructure, connection layers, and high-availability streaming clusters.

---

## 2. Severity Classification Matrix

### SEV-1: Critical Incident (Response SLA: < 5 Minutes)
- **Conditions:**
  - Primary database disk utilization $\ge 90\%$ and climbing steadily ($> 500\text{ MB/min}$).
  - Inactive replication slot retaining WAL threatening database crash (`PANIC: could not write to file "pg_wal"`).
  - Connection exhaustion at `max_connections` causing widespread application `FATAL` errors.
  - Primary crash, total network partition, or transaction ID wraparound emergency.
- **Operational Impact:** Complete service outage, loss of write capacity, severe customer SLA violation.
- **Evidence Required:** Filesystem metrics, `pg_replication_slots` showing multi-gigabyte lag, or `pg_stat_activity` showing zero available connections.
- **Human Approval Requirements:** **Mandatory Two-Person Sign-Off** (Incident Commander + Lead DBA). Automated destructive remediation is strictly prohibited.

### SEV-2: High Severity Incident (Response SLA: < 15 Minutes)
- **Conditions:**
  - Standby replica replication lag exceeds SLO ($> 100\text{ MB}$ or $> 60\text{ seconds}$).
  - Primary disk utilization between $75\%$ and $89\%$.
  - Connection usage $\ge 80\%$ with growing PgBouncer wait queues.
  - Persistent lock contention or high deadlock frequency ($> 10/\text{min}$).
- **Operational Impact:** Read traffic desynchronization, P95/P99 latency regressions.
- **Evidence Required:** `pg_stat_replication` lag metrics, `pg_stat_activity` wait events, or `pg_stat_archiver` failure counts.
- **Human Approval Requirements:** On-Call DBA / SRE approval before terminating backend PIDs or modifying configuration parameters.

### SEV-3: Medium Severity Incident (Response SLA: < 60 Minutes)
- **Conditions:** Isolated slow query regressions, temporary disk spikes ($65\%-74\%$), autovacuum freeze warnings with $> 20\text{M}$ transactions remaining.
- **Operational Impact:** Localized non-critical performance degradation; zero user-facing downtime.
- **Evidence Required:** `pg_stat_statements`, EXPLAIN query plans, or autovacuum logs.
- **Human Approval Requirements:** Standard engineering review during maintenance window.

### SEV-4: Low Severity / Advisory (Response SLA: < 240 Minutes)
- **Conditions:** Minor configuration drift, non-critical log warnings, preventative optimization recommendations.
- **Operational Impact:** Zero operational impact.
- **Human Approval Requirements:** Standard Jira ticket / PR review.

---

## 3. Ambiguous Incidents and Insufficient Evidence Policy

> [!IMPORTANT]
> **EVIDENCE SUFFICIENCY GATE**  
> Whenever an incident alert or on-call observation lacks definitive evidence, exhibits conflicting symptoms, or retrieval confidence is below $0.70$, the triage assistant **MUST NOT** formulate speculative hypotheses or recommend unverified interventions.
>
> In such events, the system must set:
> - `evidence_sufficient = false`
> - `routing_decision = "escalate_human_expert"`
> - Detail explicit `escalation_reason` and output suggested diagnostic queries.

---

## 4. Human Approval Guardrails

> [!CAUTION]
> **NO AUTOMATED DESTRUCTIVE ACTIONS**  
> Under no circumstances may an automated agent directly execute cluster-mutating operations:
> - `SELECT pg_drop_replication_slot(...)`
> - `SELECT pg_terminate_backend(...)`
> - `ALTER SYSTEM SET ...`
> - `rm -rf $PGDATA`
> - Process kills or node restarts
>
> The assistant acts solely as an advisory intelligence tool providing verifiable evidence and suggested diagnostic queries to human responders.
