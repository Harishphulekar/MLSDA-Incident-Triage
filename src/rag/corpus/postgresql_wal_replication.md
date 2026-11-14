# PostgreSQL Documentation: Chapter 26.2.5 - Replication Slots and WAL Retention

## Overview
Replication slots provide an automated way to ensure that the primary does not remove WAL segments until they have been consumed by all standbys, and that the primary does not remove rows which could cause a recovery conflict on a standby.

## WAL Retention Mechanism
A replication slot ensures that the primary will retain WAL logs needed by the standby even when disconnected.
If a standby becomes disconnected, or fails to consume WAL records, the primary will retain all WAL segments accumulated since the slot's `restart_lsn`.

## Risk of Disk Saturation
When a replication slot becomes inactive or lags behind, the primary server's WAL directory (`pg_wal` or `pg_xlog`) will continuously grow.
Crucially, table and index sizes remain constant because the disk consumption is caused exclusively by accumulated WAL segment files, not table data.

## Diagnostic Queries
1. Check replication slots status:
   `SELECT slot_name, plugin, slot_type, active, restart_lsn, wal_status FROM pg_replication_slots;`
2. Check replication lag on active standbys:
   `SELECT client_addr, application_name, state, sync_state, pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_lag_bytes FROM pg_stat_replication;`

## Remediation Protocol
- If an inactive standby is permanently decommissioned or cannot catch up:
  `SELECT pg_drop_replication_slot('slot_name');`
- Configure `max_slot_wal_keep_size` to prevent a stalled replication slot from filling the disk to 100%.
