# Runbook: Out-of-Memory Killer & Memory Sizing

## Severity: SEV1
## Target Audience: Database Reliability Engineer

### Symptoms
- PostgreSQL primary process suddenly exits.
- OS syslog reports: `Out of memory: Kill process (postgres) score or sacrifice child`.

### Diagnostic Steps
1. Calculate total allocated database memory: `shared_buffers + (max_connections * work_mem) + (maintenance_work_mem * parallel_workers)`.
2. Verify Linux memory overcommit sysctl setting: `sysctl vm.overcommit_memory`.

### Recommended Human Actions
- Reduce `maintenance_work_mem` and `work_mem` to prevent memory overcommit.
- Ensure `vm.overcommit_memory = 2` with appropriate `vm.overcommit_ratio` to avoid kernel OOM terminations.
