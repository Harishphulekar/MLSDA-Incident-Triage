# Runbook: Standby Replication Lag and Desynchronization

## Severity: SEV2
## Target Audience: Database Reliability Engineers

### Symptoms
- Standby replica lag metric exceeds SLO (> 100MB or > 60 seconds).
- Read replicas serving stale data to application services.

### Diagnostic Steps
1. Measure replication lag on the primary:
   `SELECT client_addr, application_name, state, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes FROM pg_stat_replication;`
2. Check network latency and packet loss between primary and standby instances.
3. Check CPU/IO load on the replica to see if replay process is bottlenecked.

### Recommended Human Actions
- Check if replica hardware is undersized for current write throughput.
- Ensure standby has adequate `max_standby_streaming_delay` to avoid query conflicts pausing WAL replay.
