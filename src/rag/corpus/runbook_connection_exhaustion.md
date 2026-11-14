# Runbook: Connection Exhaustion and Pool Saturation

## Severity: SEV2
## Target Audience: SRE & Backend On-Call

### Symptoms
- Application logs reporting `FATAL: remaining connection slots are reserved for non-replication superuser connections`.
- Spikes in connection count nearing `max_connections`.

### Diagnostic Steps
1. Query connection states:
   `SELECT state, count(*) FROM pg_stat_activity GROUP BY state;`
2. Check for long-running idle-in-transaction connections:
   `SELECT pid, now() - xact_start AS duration, query FROM pg_stat_activity WHERE state = 'idle in transaction' ORDER BY duration DESC;`
3. Inspect PgBouncer connection pooler metrics and client waiting queues.

### Recommended Human Actions
- Terminate stuck or rogue backend sessions:
  `SELECT pg_terminate_backend(pid);`
- Verify application connection pool sizing against PgBouncer limits.
