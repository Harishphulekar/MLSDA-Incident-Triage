# Runbook RB-PG-002: Standby Replication Lag and Desynchronization

**Runbook ID:** RB-PG-002  
**Incident Category:** replication_lag  
**Severity:** SEV-2 (High)  
**Target Audience:** Database Reliability Engineers, DBA & SRE On-Call  
**Applicable Version:** PostgreSQL 16  
**Last Verified:** 2026-11-15  

---

## 1. Incident Overview & Symptoms

### Symptoms
- Standby replica replication lag metric exceeds Service Level Objective (SLO): replay lag > 100 MB or delay > 60 seconds.
- Application read traffic routed to read replicas observes stale data, causing read-after-write inconsistencies.
- Replication monitoring alert: `PostgreSQLReplicationLagHigh` firing on Grafana / Alertmanager.
- Standby lag steadily increases during high-write batch operations or analytical report execution.

### Preconditions
- PostgreSQL 16 streaming replication architecture with primary and one or more read-only standby instances.
- Standby configured with `hot_standby = on` to serve client read queries.

---

## 2. Possible Causes

1. **Standby Replay Lock Conflicts:** Long-running analytical or read queries on the standby hold locks on relations or buffer pins that conflict with WAL replay (e.g. `AccessExclusiveLock` from vacuum cleanup or DDL).
2. **Resource Saturation on Standby:** Standby disk I/O, memory, or single-threaded startup process CPU bottlenecked compared to multi-threaded write throughput on the primary.
3. **Network Latency or Packet Loss:** Network bottleneck between primary and standby delaying WAL streaming over TCP.
4. **WAL Sender / Receiver Stoppage:** Replication connection dropped due to `wal_sender_timeout` or `wal_receiver_timeout`.
5. **Replication Slot Stalled or Lagging:** The slot on the primary is lagging behind `pg_current_wal_lsn()`.

---

## 3. Step-by-Step Investigation Procedure

### Step 3.1: Measure Replication Lag on Primary
Execute on the primary instance to identify each connected standby and its lag breakdown:
```sql
SELECT 
    application_name,
    client_addr,
    client_port,
    state,
    sync_state,
    pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn) AS sent_lag_bytes,
    pg_wal_lsn_diff(sent_lsn, write_lsn) AS write_lag_bytes,
    pg_wal_lsn_diff(write_lsn, flush_lsn) AS flush_lag_bytes,
    pg_wal_lsn_diff(flush_lsn, replay_lsn) AS replay_lag_bytes,
    round(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) / (1024*1024), 2) AS total_lag_mb,
    now() - reply_time AS last_reply_age
FROM pg_stat_replication;
```
**Interpretation:**
- High `sent_lag_bytes`: Network bandwidth bottleneck or primary WAL sender thread CPU saturation.
- High `write_lag_bytes` or `flush_lag_bytes`: Standby storage write/flush latency.
- High `replay_lag_bytes`: Standby recovery process replay bottleneck or read query conflicts.

### Step 3.2: Inspect WAL Receiver on Standby
Execute on the lagging standby instance:
```sql
SELECT 
    status,
    receive_start_lsn,
    received_lsn,
    last_msg_send_time,
    last_msg_receipt_time,
    latest_end_lsn,
    latest_end_time,
    slot_name,
    conninfo
FROM pg_stat_wal_receiver;
```

### Step 3.3: Check Standby Recovery Conflicts
Check if read queries are pausing recovery on the standby:
```sql
SELECT 
    datname,
    confl_tablespace,
    confl_lock,
    confl_snapshot,
    confl_bufferpin,
    confl_deadlock
FROM pg_stat_database_conflicts;
```
**Expected Observation:** Rapidly climbing `confl_lock` or `confl_snapshot` indicates standby queries are being canceled or delaying WAL replay.

### Step 3.4: Inspect Replication Slots on Primary
```sql
SELECT 
    slot_name,
    slot_type,
    active,
    active_pid,
    restart_lsn,
    wal_status
FROM pg_replication_slots;
```

---

## 4. Recommended Actions

### Action 4.1: Terminate Blocking Read Queries on Standby
If recovery conflict counters are rising, identify and terminate the long-running queries on the standby:
```sql
-- On Standby: Find long-running queries
SELECT pid, now() - query_start AS duration, query, state
FROM pg_stat_activity
WHERE state != 'idle' AND query NOT ILIKE '%pg_stat%'
ORDER BY duration DESC LIMIT 5;

-- Terminate rogue query
SELECT pg_terminate_backend(pid);
```

### Action 4.2: Tune Standby Streaming Delay Limits
Configure how long the standby will pause WAL replay for conflicting queries before canceling them:
```sql
-- Set streaming delay ceiling to 30 seconds
ALTER SYSTEM SET max_standby_streaming_delay = '30s';
ALTER SYSTEM SET max_standby_archive_delay = '30s';
SELECT pg_reload_conf();
```

### Action 4.3: Enable Hot Standby Feedback
Enable feedback to inform the primary about standby query requirements, preventing premature vacuum of rows:
```sql
-- On Standby
ALTER SYSTEM SET hot_standby_feedback = on;
SELECT pg_reload_conf();
```
*Caution:* Monitor primary table bloat when enabling `hot_standby_feedback`, as long transactions on standby will defer vacuuming on the primary.

### Action 4.4: Remove Unhealthy Standby from Traffic Pool
If replication lag exceeds 500 MB and the replica cannot recover within SLO, temporarily remove the replica node from the load balancer / DNS pool to prevent application errors.

---

## 5. Escalation Policy

| Condition | Action / Escalation Path | Required Sign-Off |
|---|---|---|
| Replay lag > 100 MB for > 15 minutes | Alert on-call DBA. Investigate query conflicts and standby I/O. | On-Call SRE |
| Standby replication disconnected (`state != 'streaming'`) | Restart WAL receiver or check network connectivity to primary. | DBA On-Call |
| Replication lag > 500 MB impacting read-heavy application services | Drain read traffic from affected replica; route reads to alternate standby. | SRE Incident Commander |
| Replication slot marked `wal_status = 'lost'` | Standby requires full rebuild from `pg_basebackup`. | Lead DBA |

---

## 6. Official Documentation Citations
- **PostgreSQL 16: Streaming Replication and Standby Management**  
  Source: [https://www.postgresql.org/docs/16/warm-standby.html](https://www.postgresql.org/docs/16/warm-standby.html)  
  *Section 27.2.5:* "Streaming replication allows a standby server to stay more up-to-date than is possible with file-based log shipping."
- **PostgreSQL 16: pg_stat_replication Statistics View**  
  Source: [https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STAT-REPLICATION-VIEW](https://www.postgresql.org/docs/16/monitoring-stats.html#MONITORING-PG-STAT-REPLICATION-VIEW)  
  *Table 54.20:* Provides real-time view of WAL sender activity, sent_lsn, write_lsn, flush_lsn, and replay_lsn.
- **PostgreSQL 16: Standby Server Configuration & Conflicts**  
  Source: [https://www.postgresql.org/docs/16/runtime-config-replication.html#RUNTIME-CONFIG-REPLICATION-STANDBY](https://www.postgresql.org/docs/16/runtime-config-replication.html#RUNTIME-CONFIG-REPLICATION-STANDBY)  
  *Parameters:* `max_standby_streaming_delay`, `hot_standby_feedback`, `wal_receiver_timeout`.
