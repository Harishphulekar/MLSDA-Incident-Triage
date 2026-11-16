---
document_id: pg16_view_pg_replication_slots
title: "PostgreSQL 16: pg_replication_slots View and Slot Management"
source_url: https://www.postgresql.org/docs/16/view-pg-replication-slots.html
postgresql_version: "16"
topic: replication
category: replication_slots
retrieved_date: "2026-11-15"
---

# PostgreSQL 16: pg_replication_slots View and Slot Management

Source: [https://www.postgresql.org/docs/16/view-pg-replication-slots.html](https://www.postgresql.org/docs/16/view-pg-replication-slots.html)  
PostgreSQL Version: 16  
Incident Category: replication_slots

## 54.19.  pg_replication_slots

The  pg_replication_slots  view provides a listing of all replication slots that currently exist on the database cluster, along with their current state.

For more on replication slots, see  Section 27.2.6  and  Chapter 49 .

Table 54.19.  pg_replication_slots  Columns

| Column Type   Description |
| --- |
| slot_name   name   A unique, cluster-wide identifier for the replication slot |
| plugin   name   The base name of the shared object containing the output plugin this logical slot is using, or null for physical slots. |
| slot_type   text   The slot type:  physical  or  logical |
| datoid   oid  (references  pg_database . oid )   The OID of the database this slot is associated with, or null. Only logical slots have an associated database. |
| database   name  (references  pg_database . datname )   The name of the database this slot is associated with, or null. Only logical slots have an associated database. |
| temporary   bool   True if this is a temporary replication slot. Temporary slots are not saved to disk and are automatically dropped on error or when the session has finished. |
| active   bool   True if this slot is currently actively being used |
| active_pid   int4   The process ID of the session using this slot if the slot is currently actively being used.  NULL  if inactive. |
| xmin   xid   The oldest transaction that this slot needs the database to retain.  VACUUM  cannot remove tuples deleted by any later transaction. |
| catalog_xmin   xid   The oldest transaction affecting the system catalogs that this slot needs the database to retain.  VACUUM  cannot remove catalog tuples deleted by any later transaction. |
| restart_lsn   pg_lsn   The address ( LSN ) of oldest WAL which still might be required by the consumer of this slot and thus won't be automatically removed during checkpoints unless this LSN gets behind more than  max_slot_wal_keep_size  from the current LSN.  NULL  if the  LSN  of this slot has never been reserved. |
| confirmed_flush_lsn   pg_lsn   The address ( LSN ) up to which the logical slot's consumer has confirmed receiving data. Data corresponding to the transactions committed before this  LSN  is not available anymore.  NULL  for physical slots. |
| wal_status   text   Availability of WAL files claimed by this slot. Possible values are:         reserved  means that the claimed files are within  max_wal_size .       extended  means that  max_wal_size  is exceeded but the files are still retained, either by the replication slot or by  wal_keep_size .       unreserved  means that the slot no longer retains the required WAL files and some of them are to be removed at the next checkpoint. This typically occurs when  max_slot_wal_keep_size  is set to a non-negative value. This state can return to  reserved  or  extended .       lost  means that this slot is no longer usable. |
| safe_wal_size   int8   The number of bytes that can be written to WAL such that this slot is not in danger of getting in state "lost". It is NULL for lost slots, as well as if  max_slot_wal_keep_size  is  -1 . |
| two_phase   bool   True if the slot is enabled for decoding prepared transactions. Always false for physical slots. |
| conflicting   bool   True if this logical slot conflicted with recovery (and so is now invalidated). Always NULL for physical slots. |