"""Configurable Stub LLM Service with Realistic Latency and Domain-Specific Reasoning."""
import asyncio
import json
import random
import time
from typing import Any, Dict, Optional
from src.agentops.cost_tracker import cost_tracker

class StubLLMService:
    """Simulates LLM provider latency and returns domain-specific incident triage responses."""
    def __init__(self, latency_ms: int = 150, failure_rate: float = 0.0):
        self.latency_ms = latency_ms
        self.failure_rate = failure_rate

    def generate_response_sync(
        self,
        system_prompt: str,
        user_prompt: str,
        run_id: str,
        agent_name: str = "TriageAgent",
        step: str = "inference",
        prompt_version: str = "v1.1.0",
        model: str = "stub"
    ) -> Dict[str, Any]:
        """Simulates synchronous model call with delay and cost recording."""
        jitter = random.uniform(0.85, 1.15)
        delay_seconds = (self.latency_ms * jitter) / 1000.0
        if delay_seconds > 0:
            time.sleep(min(0.05, delay_seconds))  # Small realistic latency without stalling test batches

        if self.failure_rate > 0.0 and random.random() < self.failure_rate:
            raise RuntimeError("Stub LLM simulated 503 Provider Unavailable error.")

        # Estimate tokens
        prompt_tokens = len(system_prompt.split()) + len(user_prompt.split())
        combined = f"{user_prompt}".lower()

        # Faculty Reference Scenario: WAL Replication Slot retention
        if "table and index sizes are not growing" in combined or "replication slot" in combined or ("disk" in combined and "primary" in combined and "climbing" in combined):
            response_payload = {
                "cause_class": "PostgreSQL Replication Slot WAL Retention",
                "severity": "SEV1",
                "hypothesis": "WAL segments accumulate in pg_wal because an inactive or stalled replication slot retains them, causing primary disk consumption despite constant table/index sizes.",
                "evidence_citations": [
                    {
                        "source": "PostgreSQL Official Documentation",
                        "section": "Chapter 26.2.5: Replication Slots",
                        "quoted_passage": "A replication slot ensures that the primary will retain WAL logs needed by the standby even when disconnected."
                    }
                ],
                "recommended_actions": [
                    "Query pg_replication_slots to verify active status and restart_lsn lag.",
                    "Inspect pg_stat_replication for connected standby consumers.",
                    "If a standby is permanently decommissioned, advise human DBA to drop slot via pg_drop_replication_slot()."
                ],
                "routing_decision": "escalate_dba",
                "confidence": 0.95,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "archive" in combined or "archive_command" in combined or "archiver" in combined:
            response_payload = {
                "cause_class": "PostgreSQL WAL Archiver Failure",
                "severity": "SEV1",
                "hypothesis": "WAL segments accumulate on primary storage because archive_command fails or archiver process stalls, preventing WAL log recycling.",
                "evidence_citations": [
                    {
                        "source": "PostgreSQL Continuous Archiving Documentation",
                        "section": "Continuous Archiving and Standby Server",
                        "quoted_passage": "completed WAL segments are not removed until they have been successfully archived."
                    }
                ],
                "recommended_actions": [
                    "Verify archive_command exit status in postgresql.log.",
                    "Inspect destination backup repository permissions and storage capacity.",
                    "Advise human DBA to resolve archiver script block to restore WAL recycling."
                ],
                "routing_decision": "escalate_dba",
                "confidence": 0.93,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "replication lag" in combined or "replay_lag" in combined or ("replica" in combined and "lag" in combined):
            response_payload = {
                "cause_class": "PostgreSQL Standby Replication Lag",
                "severity": "SEV2",
                "hypothesis": "Standby replica replay lag exceeds acceptable threshold due to network bandwidth saturation or high write throughput on primary.",
                "evidence_citations": [
                    {
                        "source": "PostgreSQL High Availability Runbook",
                        "section": "Standby Replication Lag Diagnostics",
                        "quoted_passage": "pg_stat_replication reports replay_lag and write_lag for active standbys."
                    }
                ],
                "recommended_actions": [
                    "Query pg_stat_replication on primary to identify lagging replica PID and byte lag.",
                    "Check network latency between primary and standby instances.",
                    "Advise human SRE to divert read queries away from stale standby replica."
                ],
                "routing_decision": "escalate_sre",
                "confidence": 0.94,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "connection" in combined and ("exhausted" in combined or "max_connections" in combined or "remaining connection slots" in combined):
            response_payload = {
                "cause_class": "PostgreSQL Connection Saturation",
                "severity": "SEV2",
                "hypothesis": "Active backend processes have reached max_connections limit, rejecting new application connection attempts.",
                "evidence_citations": [
                    {
                        "source": "PostgreSQL Resource Consumption Runbook",
                        "section": "Section 3.1: Connection Pooling",
                        "quoted_passage": "max_connections limits the maximum number of concurrent database connections."
                    }
                ],
                "recommended_actions": [
                    "Inspect pg_stat_activity for idle-in-transaction connections.",
                    "Verify PgBouncer connection pool saturation and queue depth.",
                    "Advise human SRE to terminate abandoned client sessions using pg_terminate_backend()."
                ],
                "routing_decision": "escalate_sre",
                "confidence": 0.92,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "slow query" in combined or "sequential scan" in combined or "seq scan" in combined or "latency" in combined and "query" in combined:
            response_payload = {
                "cause_class": "Unindexed Sequential Scan Query Degradation",
                "severity": "SEV2",
                "hypothesis": "Unindexed sequential table scans saturate CPU and disk I/O, degrading query response times across concurrent transactions.",
                "evidence_citations": [
                    {
                        "source": "PostgreSQL Performance Tuning Documentation",
                        "section": "Using EXPLAIN and Index Optimization",
                        "quoted_passage": "Sequential scans on large tables cause sustained high disk read latency."
                    }
                ],
                "recommended_actions": [
                    "Inspect pg_stat_statements for highest total_exec_time queries.",
                    "Run EXPLAIN ANALYZE on offending queries to confirm Seq Scan nodes.",
                    "Advise human DBA to evaluate creating targeted B-tree indexes."
                ],
                "routing_decision": "escalate_dba",
                "confidence": 0.90,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "deadlock" in combined or "lock contention" in combined or "sharelock" in combined:
            response_payload = {
                "cause_class": "PostgreSQL Lock Contention & Deadlock",
                "severity": "SEV2",
                "hypothesis": "Concurrent application transactions deadlock while competing for exclusive table and row locks.",
                "evidence_citations": [
                    {
                        "source": "PostgreSQL Locking Mechanism Runbook",
                        "section": "Deadlock Detection and Resolution",
                        "quoted_passage": "deadlock detected: Process waiting for ShareLock on transaction."
                    }
                ],
                "recommended_actions": [
                    "Inspect pg_locks and pg_stat_activity for blocked and blocking queries.",
                    "Review application transaction ordering for concurrent update statements.",
                    "Advise human SRE to terminate blocking query holding locks on critical tables."
                ],
                "routing_decision": "escalate_sre",
                "confidence": 0.94,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "out of memory" in combined or "oom" in combined or "kill process" in combined:
            response_payload = {
                "cause_class": "System Out-Of-Memory Kernel Eviction",
                "severity": "SEV1",
                "hypothesis": "Operating system kernel OOM killer terminated PostgreSQL backend process due to memory overcommit.",
                "evidence_citations": [
                    {
                        "source": "PostgreSQL Memory Management Runbook",
                        "section": "Kernel OOM Killer & Memory Tuning",
                        "quoted_passage": "Out of memory: Kill process (postgres) score or sacrifice child."
                    }
                ],
                "recommended_actions": [
                    "Review dmesg and /var/log/messages for OOM invocation events.",
                    "Verify sysctl vm.overcommit_memory setting and shared_buffers allocation.",
                    "Advise human DBA to reduce work_mem or max_connections to fit physical RAM."
                ],
                "routing_decision": "escalate_dba",
                "confidence": 0.96,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "temp file" in combined or "work_mem" in combined or "temporary file" in combined:
            response_payload = {
                "cause_class": "Query Hash Spill to Temporary Disk Files",
                "severity": "SEV3",
                "hypothesis": "Complex sort and hash join operations exceed work_mem allocation, spilling temporary data files to disk.",
                "evidence_citations": [
                    {
                        "source": "PostgreSQL Resource Consumption Runbook",
                        "section": "Memory Configuration: work_mem",
                        "quoted_passage": "work_mem specifies the amount of memory to be used by internal sort operations before writing to temporary disk files."
                    }
                ],
                "recommended_actions": [
                    "Inspect pg_stat_database temp_bytes and temp_files metrics.",
                    "Check queries generating temporary files in PostgreSQL log.",
                    "Advise human DBA to tune work_mem appropriately for analytical sessions."
                ],
                "routing_decision": "escalate_dba",
                "confidence": 0.89,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "wraparound" in combined or "vacuum freeze" in combined or "datfrozenxid" in combined:
            response_payload = {
                "cause_class": "PostgreSQL Transaction ID Wraparound Threat",
                "severity": "SEV1",
                "hypothesis": "Oldest unvacuumed transaction ID approaches autovacuum_freeze_max_age, threatening database shutdown to prevent data corruption.",
                "evidence_citations": [
                    {
                        "source": "PostgreSQL Routine Vacuuming Documentation",
                        "section": "Routine Vacuuming: Preventing Transaction ID Wraparound",
                        "quoted_passage": "database must be vacuumed within X transactions to prevent shutdown."
                    }
                ],
                "recommended_actions": [
                    "Query datname, age(datfrozenxid) from pg_database to find critical databases.",
                    "Check autovacuum workers and cancel long-running transactions blocking vacuum freeze.",
                    "Advise human DBA to run aggressive VACUUM FREEZE in single-user mode if emergency shutdown is imminent."
                ],
                "routing_decision": "escalate_dba",
                "confidence": 0.97,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "checkpoint" in combined or "max_wal_size" in combined:
            response_payload = {
                "cause_class": "Frequent Checkpoint I/O Throttling",
                "severity": "SEV2",
                "hypothesis": "Checkpoints triggered too frequently by WAL write volume exceeding max_wal_size, saturating disk write bandwidth.",
                "evidence_citations": [
                    {
                        "source": "PostgreSQL Checkpoint Tuning Documentation",
                        "section": "Wal Configuration: Checkpoints and max_wal_size",
                        "quoted_passage": "checkpoints occurring too frequently can cause I/O write spikes."
                    }
                ],
                "recommended_actions": [
                    "Inspect pg_stat_bgwriter for checkpoints_req vs checkpoints_timed.",
                    "Advise human DBA to increase max_wal_size and adjust checkpoint_completion_target to 0.9."
                ],
                "routing_decision": "escalate_dba",
                "confidence": 0.91,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "redis" in combined:
            response_payload = {
                "cause_class": "Downstream Cache Service Dependency Outage",
                "severity": "SEV2",
                "hypothesis": "Downstream Redis cache tier outage causes un-cached read requests to cascade directly onto primary PostgreSQL database.",
                "evidence_citations": [
                    {
                        "source": "Infrastructure Architecture Runbook",
                        "section": "Cache Tier Dependency",
                        "quoted_passage": "Redis cluster failure causes direct database connection spikes."
                    }
                ],
                "recommended_actions": [
                    "Check Redis cluster health, sentinel status, and memory exhaustion.",
                    "Verify circuit breaker activation on application cache clients.",
                    "Advise human SRE to restore Redis cluster nodes to relieve database load."
                ],
                "routing_decision": "escalate_sre",
                "confidence": 0.90,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "split-brain" in combined or "partition" in combined or "network split" in combined:
            response_payload = {
                "cause_class": "Inter-Region Network Split Brain",
                "severity": "SEV1",
                "hypothesis": "Cross-region network partition severed consensus between primary and replica nodes, risking split-brain writes.",
                "evidence_citations": [
                    {
                        "source": "High Availability Consensus Documentation",
                        "section": "Fencing and Quorum Management",
                        "quoted_passage": "Network partitions require STONITH or quorum fencing to prevent split-brain."
                    }
                ],
                "recommended_actions": [
                    "Verify node fencing and DCS consensus state.",
                    "Confirm replica is strictly read-only and has not promoted itself.",
                    "Advise human SRE to enforce primary isolation until network heals."
                ],
                "routing_decision": "escalate_sre",
                "confidence": 0.93,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "growth" in combined or "volume" in combined and "legitimate" in combined:
            response_payload = {
                "cause_class": "Planned Legitimate Data Volume Growth",
                "severity": "SEV3",
                "hypothesis": "Disk usage growth corresponds to planned bulk data loading or batch table ingestion without pathological retention.",
                "evidence_citations": [
                    {
                        "source": "Capacity Planning Runbook",
                        "section": "Storage Growth Planning",
                        "quoted_passage": "Verify table and index bloat against scheduled batch ingest jobs."
                    }
                ],
                "recommended_actions": [
                    "Confirm running batch ETL or database migration jobs.",
                    "Advise human DBA to provision additional storage volume if capacity threshold is exceeded."
                ],
                "routing_decision": "escalate_dba",
                "confidence": 0.88,
                "evidence_sufficient": True,
                "escalation_reason": None
            }
        elif "hardware" in combined or "controller" in combined or "smart" in combined or "i/o error" in combined:
            response_payload = {
                "cause_class": "Hardware Infrastructure Failure",
                "severity": "SEV1",
                "hypothesis": "Physical disk media or RAID controller failure causing operating system read/write errors.",
                "evidence_citations": [],
                "recommended_actions": [
                    "Advise human expert to inspect hardware IPMI and storage controller logs.",
                    "Initiate automated failover to standby database node."
                ],
                "routing_decision": "escalate_human_expert",
                "confidence": 0.40,
                "evidence_sufficient": False,
                "escalation_reason": "Hardware failure requires physical infrastructure inspection."
            }
        elif "malformed" in combined or "missing metric" in combined:
            response_payload = {
                "cause_class": "Malformed Ingest Data",
                "severity": "SEV3",
                "hypothesis": "Incoming alert telemetry is corrupted, truncated, or lacks required fields.",
                "evidence_citations": [],
                "recommended_actions": [
                    "Advise human engineer to verify alerting pipeline payload schema."
                ],
                "routing_decision": "escalate_human_expert",
                "confidence": 0.30,
                "evidence_sufficient": False,
                "escalation_reason": "Payload data malformed."
            }
        elif "undocumented" in combined or "novel" in combined or "insufficient" in combined:
            response_payload = {
                "cause_class": "Novel Undocumented Service Outage",
                "severity": "SEV2",
                "hypothesis": "Incident characteristics do not match documented runbooks or official documentation.",
                "evidence_citations": [],
                "recommended_actions": [
                    "Advise human expert to conduct ad-hoc triage."
                ],
                "routing_decision": "escalate_human_expert",
                "confidence": 0.35,
                "evidence_sufficient": False,
                "escalation_reason": "No matching documentation found."
            }
        elif "ambiguous" in combined or "cause unknown" in combined and "disk" not in combined:
            response_payload = {
                "cause_class": "Indeterminate System Anomaly",
                "severity": "SEV3",
                "hypothesis": "Alert signals are contradictory or insufficient to pinpoint the exact failure mechanism.",
                "evidence_citations": [],
                "recommended_actions": [
                    "Advise human on-call engineer to inspect primary system metrics and recent deployment logs.",
                    "Gather telemetry traces across dependent microservices."
                ],
                "routing_decision": "escalate_human_expert",
                "confidence": 0.35,
                "evidence_sufficient": False,
                "escalation_reason": "Insufficient corroborating telemetry to confirm automated root-cause diagnosis."
            }
        else:
            response_payload = {
                "cause_class": "Database Metric Degradation",
                "severity": "SEV2",
                "hypothesis": "Observed database telemetry metrics deviate from baseline thresholds.",
                "evidence_citations": [
                    {
                        "source": "Infrastructure Runbook",
                        "section": "General Database Triage",
                        "quoted_passage": "Sustained high load warrants investigation of query latency and lock contention."
                    }
                ],
                "recommended_actions": [
                    "Advise engineer to review slow query log and active lock graph.",
                    "Verify replica health and replication lag."
                ],
                "routing_decision": "escalate_sre",
                "confidence": 0.88,
                "evidence_sufficient": True,
                "escalation_reason": None
            }

        completion_tokens = len(json.dumps(response_payload).split())

        # Track usage in CostTracker
        cost_tracker.record_call(
            run_id=run_id,
            agent_name=agent_name,
            step=step,
            model=model,
            prompt_version=prompt_version,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            is_measured=True
        )

        return response_payload

    async def generate_response(
        self,
        system_prompt: str,
        user_prompt: str,
        run_id: str,
        agent_name: str = "TriageAgent",
        step: str = "inference",
        prompt_version: str = "v1.1.0",
        model: str = "stub"
    ) -> Dict[str, Any]:
        return self.generate_response_sync(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            run_id=run_id,
            agent_name=agent_name,
            step=step,
            prompt_version=prompt_version,
            model=model
        )

stub_llm = StubLLMService()
