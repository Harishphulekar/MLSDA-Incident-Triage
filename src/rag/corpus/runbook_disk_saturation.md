# Runbook: Primary Database Disk Saturation Triage

## Severity: SEV1 / SEV2
## Target Audience: Production DBA & SRE On-Call

### Symptoms
- Disk space on PostgreSQL primary exceeds 80% and is climbing steadily.
- Application transactions risk being paused if disk hits 100% (PANIC: could not write to file "pg_wal").

### Diagnostic Steps
1. Determine if growth is in table data or WAL files:
   - Run `du -sh $PGDATA/base` (table data) vs `du -sh $PGDATA/pg_wal` (WAL files).
   - If table sizes and index sizes are not growing, the root cause is almost certainly WAL retention.
2. Investigate WAL retention causes:
   - Check `archive_command` failures in PostgreSQL logs.
   - Check `pg_replication_slots` for inactive replication slots or slots with large restart LSN lag.
   - Check if `wal_keep_size` is configured excessively high.

### Recommended Human Actions
- If an inactive replica slot is retaining WAL, obtain SRE approval and drop the slot:
  `SELECT pg_drop_replication_slot('slot_name');`
- If archive command is failing, check destination storage mount / credentials.
- Do NOT run manual `rm` on `pg_wal` files directly, as this risks database corruption.
