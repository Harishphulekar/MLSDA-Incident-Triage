# Runbook: Checkpoint I/O Throttling & WAL Burst Tuning

## Severity: SEV2
## Target Audience: Database Systems Engineer

### Symptoms
- Frequent checkpoint completion spikes occurring in under 1 minute.
- I/O wait latency increases significantly, stalling client write throughput.

### Diagnostic Steps
1. Review `checkpoint_completion_target` (default should be 0.9).
2. Measure checkpoint frequency in `pg_stat_bgwriter` (check `checkpoints_req` vs `checkpoints_timed`).

### Recommended Human Actions
- Increase `max_wal_size` (e.g. from default 1GB to 16GB or 32GB) to reduce forced checkpoints.
- Ensure `checkpoint_completion_target = 0.9` to spread I/O writes evenly across checkpoint intervals.
