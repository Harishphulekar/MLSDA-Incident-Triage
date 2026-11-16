# Runbook RB-PG-001: Disk Space Saturation and WAL Retention Triage

**Runbook ID:** RB-PG-001  
**Incident Category:** storage_and_wal  
**Severity:** SEV-1 (Critical) / SEV-2 (High)  
**Target Audience:** Production Database Administrators (DBA) & SRE On-Call  
**Applicable Version:** PostgreSQL 16  
**Last Verified:** 2026-11-15  

---

## 1. Incident Overview & Symptoms

### Symptoms
- Primary database host filesystem utilization exceeds critical warning threshold (> 85%) and continues to climb steadily.
- Application error logs risk throwing `PANIC: could not write to file "pg_wal/x": No space left on device`, which causes immediate database crash and crash-recovery failure.
- Storage monitoring alarms: Disk consumption rate exceeds 1 GB/minute without corresponding business transaction spikes.
- Crucially, table and index sizes remain constant or show normal minimal growth, while total disk usage climbs monotonically.

### Preconditions
- PostgreSQL 16 primary instance with streaming replication, replication slots, or continuous WAL archiving enabled.
- Physical replication slots (`pg_replication_slots`) created for standby replicas, reporting instances, or Change Data Capture (CDC) pipelines (e.g. Debezium).

---

## 2. Possible Causes

1. **Inactive or Stalled Replication Slot:** A physical or logical replication slot exists whose consumer is disconnected or lagging. PostgreSQL strictly retains all Write-Ahead Logs generated since the slot's `restart_lsn`.
2. **Archiver Command Failure:** `archive_command` is returning non-zero exit codes (e.g., target NFS/S3 storage full or unreachable), causing WAL files to accumulate in `pg_wal`.
3. **Over-provisioned WAL Retention:** `wal_keep_size` or `max_slot_wal_keep_size` is configured excessively high or set to `-1` (unlimited).
4. **Table / Index Bloat:** Autovacuum is blocked from cleaning dead tuples due to long-running transactions, holding `xmin` back.

---

## 3. Step-by-Step Investigation Procedure

### Step 3.1: Discriminate Between Table Data vs WAL Accumulation
Determine whether the disk growth is located in database relation files or WAL log segments:
```bash
# Check filesystem utilization
df -hT $PGDATA

# Compare relation data vs WAL directory size
du -sh $PGDATA/base
du -sh $PGDATA/pg_wal
```
**Expected Observation:** If `$PGDATA/base` is constant and `$PGDATA/pg_wal` is consuming tens or hundreds of gigabytes (multiple 16MB files), the root cause is **WAL retention**.

### Step 3.2: Investigate Replication Slots and Consumer Lag
Query `pg_replication_slots` on the primary instance to identify slot state and lag:
```sql
SELECT 
    slot_name,
    plugin,
    slot_type,
    active,
    active_pid,
    restart_lsn,
    wal_status,
    safe_wal_size,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained_wal_bytes
FROM pg_replication_slots
ORDER BY pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) DESC;
```
**Expected Observation:**
- An inactive slot (`active = false`) or an active slot with a consumer that cannot keep up.
- `retained_wal_bytes` showing multi-gigabyte lag.
- `wal_status` showing `'reserved'` or `'extended'`.

### Step 3.3: Verify WAL Generation Rate and Archiver Health
Check WAL statistics and archiver status:
```sql
-- Check archiver activity
SELECT 
    archived_count,
    last_archived_wal,
    last_archived_time,
    failed_count,
    last_failed_wal,
    last_failed_time
FROM pg_stat_archiver;

-- Check current WAL write location
SELECT pg_current_wal_lsn(), pg_walfile_name(pg_current_wal_lsn());
```
**Expected Observation:** If `failed_count` is increasing and `last_failed_wal` has a recent timestamp, WAL archiving is failing and accumulating WAL segments.

### Step 3.4: Check Active Streaming Standby Lag
```sql
SELECT 
    client_addr,
    application_name,
    state,
    sync_state,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn)) AS sent_lag,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS replay_lag
FROM pg_stat_replication;
```

---

## 4. Recommended Actions

### Action 4.1: Drop Inactive or Abandoned Replication Slot
If an inactive replication slot is identified and confirmed to belong to a decommissioned replica or an orphaned CDC consumer:
```sql
-- Requires DBA approval
SELECT pg_drop_replication_slot('stalled_slot_name');
```
*Note:* Once dropped, PostgreSQL's checkpointer will automatically recycle or remove unneeded WAL files at the next checkpoint, freeing disk space immediately.

### Action 4.2: Enforce Maximum Slot WAL Retention
Configure a protective ceiling to prevent any replication slot from filling the disk to 100%:
```sql
-- Limit maximum WAL retained by slots to 40GB
ALTER SYSTEM SET max_slot_wal_keep_size = '40GB';
SELECT pg_reload_conf();
```
*PostgreSQL 16 Behavior:* If a slot falls behind by more than `max_slot_wal_keep_size`, PostgreSQL invalidates the slot (`wal_status = 'lost'`), removes the WAL segments, and preserves primary database availability.

### Action 4.3: Remediate Failing WAL Archiver
If `pg_stat_archiver` shows failures:
- Check target backup volume/mount and network permissions.
- Test the `archive_command` manually as the `postgres` system user.

### Action 4.4: Emergency Manual Checkpoint
After dropping the slot or fixing the archiver, force a checkpoint to immediately free disk:
```sql
CHECKPOINT;
```

> [!CAUTION]
> **NEVER MANUALLY DELETE FILES IN `pg_wal/` WITH `rm`!**  
> Manually removing WAL segment files breaks the transaction log sequence, causes immediate crash upon commit, and requires catastrophic crash recovery from base backup.

---

## 5. Escalation Policy

| Condition | Action / Escalation Path | Required Sign-Off |
|---|---|---|
| Primary disk utilization > 85% and climbing | Alert on-call DBA & SRE. Initiate Runbook RB-PG-001 investigation. | SRE On-Call |
| Inactive replication slot identified with > 20GB lag | Contact standby/consumer owner. If non-responsive > 15m, drop slot. | Lead DBA / SRE Incident Commander |
| Disk space > 95% with imminent database crash risk | Emergency drop of stalled replication slot to safeguard primary. | Incident Commander / On-Call DBA |
| Unknown slot owner or unresolvable WAL archive failure | Escalate to Principal Database Architect and Infrastructure Lead. | DBA Lead |

---

## 6. Official Documentation Citations
- **PostgreSQL 16: Replication Slots and WAL Retention**  
  Source: [https://www.postgresql.org/docs/16/warm-standby.html#STREAMING-REPLICATION-SLOTS](https://www.postgresql.org/docs/16/warm-standby.html#STREAMING-REPLICATION-SLOTS)  
  *Section 27.2.6:* "A replication slot ensures that the primary will retain WAL logs needed by the standby even when disconnected."
- **PostgreSQL 16: pg_replication_slots System View**  
  Source: [https://www.postgresql.org/docs/16/view-pg-replication-slots.html](https://www.postgresql.org/docs/16/view-pg-replication-slots.html)  
  *Table 54.19:* "wal_status indicates whether WAL needed by this slot is still retained on the primary."
- **PostgreSQL 16: WAL Configuration and Limits**  
  Source: [https://www.postgresql.org/docs/16/wal-configuration.html](https://www.postgresql.org/docs/16/wal-configuration.html)  
  *Parameters:* `max_slot_wal_keep_size`, `wal_keep_size`, `max_wal_size`.
