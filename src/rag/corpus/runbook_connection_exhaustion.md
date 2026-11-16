# Runbook RB-PG-003: Connection Exhaustion and High Database Latency

**Runbook ID:** RB-PG-003  
**Incident Category:** connection_exhaustion  
**Severity:** SEV-1 (Critical) / SEV-2 (High)  
**Target Audience:** SRE, DBA & Backend On-Call  
**Applicable Version:** PostgreSQL 16  
**Last Verified:** 2026-11-15  

---

## 1. Incident Overview & Symptoms

### Symptoms
- Application client services fail to establish database connections, logging:  
  `FATAL: remaining connection slots are reserved for non-replication superuser connections` or  
  `FATAL: sorry, too many clients already`.
- Application p95 and p99 query latency spikes dramatically from nominal < 50ms to > 5000ms.
- High host CPU context switching due to excessive concurrent PostgreSQL backend OS processes.
- Connection poolers (e.g. PgBouncer) report client queue depth saturation (`waiting clients` growing).

### Preconditions
- PostgreSQL 16 instance with configured `max_connections` (e.g., 200) and `superuser_reserved_connections` (default: 3).
- Multiple client application pods or services connecting either directly or via connection poolers.

---

## 2. Possible Causes

1. **Connection Leaks in Application Code:** Application microservices opening database connections without returning them to the pool or omitting connection closing logic in error handlers.
2. **Abandoned Idle-in-Transaction Connections:** Sessions holding open transactions (`state = 'idle in transaction'`), holding row or table locks, and blocking subsequent queries.
3. **Lock Contention / Deadlock Waves:** An exclusive lock on a frequently accessed table (e.g. unindexed foreign key update or schema migration) blocks numerous queries, causing queued backends to pile up until `max_connections` is exhausted.
4. **Sudden Client Traffic Surge:** Spike in web or mobile API traffic causing upstream autoscaling of application pods, with each pod spinning up new database connection pools.
5. **Slow Queries Exhausting Active Backend Slots:** Unoptimized sequential scans consuming long execution times and occupying connection slots.

---

## 3. Step-by-Step Investigation Procedure

### Step 3.1: Analyze Total Connection Counts by State
Connect using superuser reserved connection (`psql -U postgres`) and query session states:
```sql
SELECT 
    state, 
    count(*) AS session_count,
    round(100.0 * count(*) / current_setting('max_connections')::numeric, 1) AS pct_of_max
FROM pg_stat_activity 
GROUP BY state 
ORDER BY session_count DESC;

-- Total connections vs limits
SELECT 
    count(*) AS current_connections,
    current_setting('max_connections')::int AS max_connections,
    current_setting('superuser_reserved_connections')::int AS superuser_reserved
FROM pg_stat_activity;
```
**Interpretation:** If `current_connections` is within 3 of `max_connections`, non-superuser connections will immediately fail with `FATAL: remaining connection slots are reserved`.

### Step 3.2: Group Connections by Application and Client Host
Identify the source service or IP causing connection saturation:
```sql
SELECT 
    client_addr, 
    application_name, 
    usename, 
    count(*) AS connection_count
FROM pg_stat_activity 
GROUP BY client_addr, application_name, usename 
ORDER BY connection_count DESC 
LIMIT 10;
```

### Step 3.3: Detect Long-Running Idle-in-Transaction Sessions
Query sessions left in `idle in transaction` state, which pin resources and hold locks:
```sql
SELECT 
    pid, 
    usename, 
    client_addr, 
    application_name,
    now() - state_change AS idle_duration,
    now() - xact_start AS transaction_duration,
    query
FROM pg_stat_activity 
WHERE state = 'idle in transaction' 
ORDER BY transaction_duration DESC 
LIMIT 15;
```

### Step 3.4: Investigate Lock Contention and Blocked Processes
Determine if a chain of blocked queries is causing the connection spike:
```sql
SELECT 
    blocked_activity.pid AS blocked_pid,
    blocked_activity.usename AS blocked_user,
    blocking_activity.pid AS blocking_pid,
    blocking_activity.usename AS blocking_user,
    blocked_activity.query AS blocked_statement,
    blocking_activity.query AS current_statement_in_blocking_process,
    now() - blocked_activity.query_start AS blocked_duration,
    blocked_activity.wait_event_type,
    blocked_activity.wait_event
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks 
    ON blocking_locks.locktype = blocked_locks.locktype
    AND blocking_locks.database IS NOT DISTINCT FROM blocked_locks.database
    AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
    AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
    AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
    AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
    AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
    AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
    AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
    AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
    AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.granted;
```

---

## 4. Recommended Actions

### Action 4.1: Terminate Offending or Stuck Sessions
Terminate rogue sessions or root blocking PIDs to immediately release connections:
```sql
-- Terminate individual blocking or idle session
SELECT pg_terminate_backend(blocking_pid);

-- Terminate all idle-in-transaction sessions older than 5 minutes
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle in transaction'
  AND now() - state_change > interval '5 minutes'
  AND pid != pg_backend_pid();
```

### Action 4.2: Enforce Automatic Session & Transaction Timeouts
Prevent recurrence by establishing defensive timeouts in PostgreSQL 16:
```sql
-- Automatically terminate connections idle in transaction for > 60 seconds
ALTER SYSTEM SET idle_in_transaction_session_timeout = '60s';

-- Automatically abort statements exceeding 30 seconds
ALTER SYSTEM SET statement_timeout = '30s';

-- Automatically terminate completely idle connections after 10 minutes
ALTER SYSTEM SET idle_session_timeout = '10min';

-- Apply changes without restarting the database server
SELECT pg_reload_conf();
```

### Action 4.3: Right-Size Connection Pools in PgBouncer
- Verify that PgBouncer is deployed in `transaction` pooling mode.
- Set `default_pool_size = 20-30` connections per database to prevent application instances from exhausting PostgreSQL backend processes.
- Do NOT simply raise `max_connections` to 2000+, as PostgreSQL uses process-based concurrency; excessive processes cause RAM bloat and CPU thrashing.

---

## 5. Escalation Policy

| Condition | Action / Escalation Path | Required Sign-Off |
|---|---|---|
| Available connections < 10% of max_connections | Alert SRE and DBA on-call. Execute Step 3.1 & 3.2. | On-Call SRE |
| Non-superuser connection attempts failing (FATAL) | Declare SEV-1 incident. Terminate idle-in-transaction connections. | Incident Commander / DBA |
| Database completely unresponsive to superuser connections | Execute graceful failover to standby replica or kill rogue clients at PgBouncer layer. | Lead DBA / SRE Lead |
| Application connection leak identified in newly deployed service | Roll back offending application release or reduce pod replicas. | Engineering Lead |

---

## 6. Official Documentation Citations
- **PostgreSQL 16: Connection Settings and Limits**  
  Source: [https://www.postgresql.org/docs/16/runtime-config-connection.html](https://www.postgresql.org/docs/16/runtime-config-connection.html)  
  *Parameters:* `max_connections`, `superuser_reserved_connections`, `reserved_connections`.
- **PostgreSQL 16: The pg_stat_activity System View**  
  Source: [https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STAT-ACTIVITY-VIEW](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STAT-ACTIVITY-VIEW)  
  *Table 54.8:* Details connection states, transaction start times, and wait events.
- **PostgreSQL 16: Lock Contention and Deadlock Detection**  
  Source: [https://www.postgresql.org/docs/16/explicit-locking.html](https://www.postgresql.org/docs/16/explicit-locking.html)  
  *Section 13.3:* Details lock modes, conflict matrices, and deadlock timeout handling.
