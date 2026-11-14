# Runbook: PostgreSQL Lock Contention and Deadlock Spike

## Severity: SEV2
## Target Audience: SRE & DBA On-Call

### Symptoms
- Deadlock rate exceeding threshold (> 10/sec).
- Transactions aborted with error: `deadlock detected: Process waiting for ShareLock on transaction`.

### Diagnostic Steps
1. Inspect `log_lock_waits` and postgresql logs for cyclical dependency graphs.
2. Query active blocking queries:
   `SELECT blocked_locks.pid AS blocked_pid, blocking_locks.pid AS blocking_pid, blocked_activity.query AS blocked_statement FROM pg_catalog.pg_locks blocked_locks JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype;`

### Recommended Human Actions
- Advise developers to ensure identical table/row update order across all concurrent transactions.
- Tune `deadlock_timeout` parameter if lock detection triggers prematurely.
