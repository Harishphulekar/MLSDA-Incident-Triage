---
document_id: pg16_monitoring_locks
title: "PostgreSQL 16: Viewing Locks and Concurrency"
source_url: https://www.postgresql.org/docs/16/monitoring-locks.html
postgresql_version: "16"
topic: monitoring
category: monitoring
retrieved_date: "2026-11-15"
---

# PostgreSQL 16: Viewing Locks and Concurrency

Source: [https://www.postgresql.org/docs/16/monitoring-locks.html](https://www.postgresql.org/docs/16/monitoring-locks.html)  
PostgreSQL Version: 16  
Incident Category: monitoring

## 28.3. Viewing Locks

Another useful tool for monitoring database activity is the  pg_locks  system table. It allows the database administrator to view information about the outstanding locks in the lock manager. For example, this capability can be used to:

- View all the locks currently outstanding, all the locks on relations in a particular database, all the locks on a particular relation, or all the locks held by a particular  PostgreSQL  session.
- Determine the relation in the current database with the most ungranted locks (which might be a source of contention among database clients).
- Determine the effect of lock contention on overall database performance, as well as the extent to which contention varies with overall database traffic.

Details of the  pg_locks  view appear in  Section 54.12 . For more information on locking and managing concurrency with  PostgreSQL , refer to  Chapter 13 .