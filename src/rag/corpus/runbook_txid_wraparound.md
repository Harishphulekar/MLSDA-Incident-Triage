# Runbook: Transaction ID Wraparound & Autovacuum Freeze

## Severity: SEV1
## Target Audience: Senior DBA On-Call

### Symptoms
- PostgreSQL log warning: `database must be vacuumed within X transactions to prevent shutdown`.
- Critical database failsafe enters read-only mode if age(datfrozenxid) hits 2 billion transactions.

### Diagnostic Steps
1. Identify database with oldest frozen transaction ID:
   `SELECT datname, age(datfrozenxid) FROM pg_database ORDER BY age(datfrozenxid) DESC;`
2. Check for long-running open snapshots or abandoned replication slots preventing vacuum freeze.

### Recommended Human Actions
- Terminate long-running uncommitted transactions or abandoned pg_dump sessions.
- Run aggressive manual `VACUUM FREEZE ANALYZE` on table with oldest relfrozenxid.
