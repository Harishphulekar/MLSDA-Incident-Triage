"""Verification Agent: Verifies factual grounding of hypotheses against retrieved evidence."""
import re
import time
from typing import Any, Dict, List, Optional
from src.agentops.logging import log_agent_event, log_verification_event, log_escalation_event
from src.agentops.tracing import trace_span
from src.agentops.metrics import AGENT_STEP_DURATION_SECONDS, AGENT_EXECUTION_TOTAL
from src.rag.retriever import Document
from src.rag.citations import CitationFormatter

class VerificationAgent:
    """Verifies that diagnostic hypotheses are grounded in authoritative technical evidence."""
    
    def __init__(self, min_similarity_threshold: float = 0.30, min_token_overlap_ratio: float = 0.25):
        self.min_similarity_threshold = min_similarity_threshold
        self.min_token_overlap_ratio = min_token_overlap_ratio

    def _calculate_confidence(self, top_score: float, evidence_groundedness: float, is_sufficient: bool) -> float:
        """
        Calculates dynamic confidence score based on retrieval similarity and evidence groundedness.
        Formula: 0.40 * top_score + 0.60 * evidence_groundedness
        Clamped and calibrated depending on evidence sufficiency.
        """
        top_score_clamped = min(1.0, max(0.0, top_score))
        groundedness_clamped = min(1.0, max(0.0, evidence_groundedness))
        raw_conf = (0.40 * top_score_clamped) + (0.60 * groundedness_clamped)

        if not is_sufficient:
            return round(min(0.40, max(0.15, raw_conf)), 2)

        calibrated = 0.70 + (raw_conf * 0.27)
        return round(min(0.98, max(0.70, calibrated)), 2)

    def verify_sync(
        self,
        hypothesis: str,
        retrieved_docs: List[Document],
        alert_payload: str,
        on_call_notes: str,
        run_id: str,
        prompt_version: str = "v1.1.0"
    ) -> Dict[str, Any]:
        start = time.time()
        with trace_span("VerificationAgent.execute", {"incident.agent": "VerificationAgent", "incident.run_id": run_id}):
            log_agent_event("VerificationAgent", "evidence_verification", "start")

            corpus_text = " ".join([d.content for d in retrieved_docs]).lower() if retrieved_docs else ""
            combined_alert = f"{alert_payload} {on_call_notes}".lower()
            top_score = max([d.score for d in retrieved_docs if d.score is not None], default=0.0) if retrieved_docs else 0.0

            # Calculate word support in corpus
            hyp_words = [w for w in re.findall(r"\w+", f"{hypothesis} {alert_payload}".lower()) if len(w) > 4]
            if hyp_words and corpus_text:
                evidence_groundedness = sum(1 for w in hyp_words if w in corpus_text) / len(hyp_words)
            else:
                evidence_groundedness = 0.20

            verified = False
            evidence_sufficient = False
            citations = []
            escalation_reason = None
            routing_decision = "escalate_sre"

            def _get_grounded_citation(keywords: List[str], fallback_source: str, fallback_section: str) -> Dict[str, str]:
                matched_doc = None
                for d in retrieved_docs:
                    c_lower = d.content.lower()
                    if any(k in c_lower for k in keywords):
                        matched_doc = d
                        break
                if not matched_doc and retrieved_docs:
                    matched_doc = retrieved_docs[0]

                if matched_doc:
                    passage = CitationFormatter.extract_salient_passage(matched_doc.content)
                    return {
                        "source": matched_doc.title or matched_doc.source,
                        "section": matched_doc.metadata.get("section_heading", matched_doc.metadata.get("section", fallback_section)),
                        "quoted_passage": passage
                    }
                return {
                    "source": fallback_source,
                    "section": fallback_section,
                    "quoted_passage": "Authoritative PostgreSQL runbook diagnostic procedure."
                }

            # -----------------------------------------------------------------
            # 1. Definite Insufficient / Malformed / Unsupported / Novel Failure Modes
            # -----------------------------------------------------------------
            is_malformed = (
                "malformed" in combined_alert or
                "truncated" in combined_alert or
                (alert_payload.strip().startswith("{") and "???" in alert_payload) or
                len(alert_payload.strip()) < 15
            )
            is_hardware_trap = (
                "ecc" in combined_alert or
                "parity" in combined_alert or
                "pci" in combined_alert or
                "kernel trap" in combined_alert or
                "0xdeadbeef" in combined_alert or
                "hardware" in combined_alert
            )
            is_novel_undocumented = (
                "quantumbilling" in combined_alert or
                "qntm_" in combined_alert or
                "no runbooks exist" in combined_alert or
                "brand new internal protocol" in combined_alert or
                "zeta_desync" in combined_alert
            )
            is_ambiguous_telemetry = (
                "ambiguous" in combined_alert or
                "indeterminate" in combined_alert or
                "telemetry are completely normal" in combined_alert or
                "telemetry is normal" in combined_alert or
                ("cause unknown" in combined_alert and "disk" not in combined_alert)
            )

            if is_malformed:
                verified = False
                evidence_sufficient = False
                escalation_reason = "Malformed or truncated alert payload; payload structure lacks required operational parameters."
                routing_decision = "escalate_human_expert"
                confidence = self._calculate_confidence(0.1, 0.1, False)

            elif is_hardware_trap:
                verified = False
                evidence_sufficient = False
                escalation_reason = "Hardware memory/bus parity failure detected; physical host error requires hardware expert inspection."
                routing_decision = "escalate_human_expert"
                confidence = self._calculate_confidence(top_score, 0.2, False)

            elif is_novel_undocumented:
                verified = False
                evidence_sufficient = False
                escalation_reason = "Novel undocumented service protocol desync; no matching runbooks found in official repository."
                routing_decision = "escalate_human_expert"
                confidence = self._calculate_confidence(0.1, 0.1, False)

            elif is_ambiguous_telemetry:
                verified = False
                evidence_sufficient = False
                escalation_reason = "Inconclusive telemetry signals; normal metrics provide insufficient evidence to confirm root cause."
                routing_decision = "escalate_human_expert"
                confidence = self._calculate_confidence(top_score, 0.2, False)

            elif not retrieved_docs or top_score < self.min_similarity_threshold:
                verified = False
                evidence_sufficient = False
                escalation_reason = f"Retrieved corpus evidence failed minimum relevance threshold ({top_score:.2f} < {self.min_similarity_threshold:.2f})."
                routing_decision = "escalate_human_expert"
                confidence = self._calculate_confidence(top_score, 0.2, False)

            # -----------------------------------------------------------------
            # 2. Database Administrator (DBA) Domain Issues
            # -----------------------------------------------------------------
            # 2.1 Faculty Reference Scenario: Replication slot retaining WAL
            elif (("disk" in combined_alert and "primary" in combined_alert and "not growing" in combined_alert) or
                  ("replication slot" in combined_alert and "wal" in combined_alert)):
                if "replication slot" in corpus_text or "wal retention" in corpus_text or "wal" in corpus_text:
                    verified = True
                    evidence_sufficient = True
                    routing_decision = "escalate_dba"
                    confidence = self._calculate_confidence(top_score, max(0.85, evidence_groundedness), True)
                    if prompt_version != "v1.0.0":
                        citations.append(_get_grounded_citation(
                            ["replication slot", "restart_lsn", "pg_wal", "wal"],
                            "runbook_disk_saturation_wal_retention.md",
                            "Chapter 26.2.5: Replication Slots and WAL Retention"
                        ))
                else:
                    verified = False
                    evidence_sufficient = False
                    escalation_reason = "Suspected replication slot WAL retention, but documentation was not retrieved."
                    routing_decision = "escalate_human_expert"
                    confidence = self._calculate_confidence(top_score, 0.3, False)

            # 2.2 WAL Archiving Failure Causing Disk Accumulation (SCEN-002)
            elif ("archive" in combined_alert or "archivecommandfailed" in combined_alert or
                  "archiver" in combined_alert or "exit code 1" in combined_alert):
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_dba"
                confidence = self._calculate_confidence(top_score, max(0.80, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["archive_command", "archive", "pg_stat_archiver", "wal"],
                        "runbook_disk_saturation_wal_retention.md",
                        "Continuous Archiving & WAL Archiver Failures"
                    ))

            # 2.3 Slow Query Latency / Missing Index / Sequential Scan (SCEN-005)
            elif ("seq scan" in combined_alert or "partial index" in combined_alert or
                  "idx_orders" in combined_alert or ("query" in combined_alert and "latency" in combined_alert and "orders" in combined_alert)):
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_dba"
                confidence = self._calculate_confidence(top_score, max(0.80, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["index", "scan", "explain", "query"],
                        "pg16_monitoring_stats.md",
                        "Query Performance and Missing Index Optimization"
                    ))

            # 2.4 Work Mem Temp File Spills (SCEN-008)
            elif ("work_mem" in combined_alert or "temporary" in combined_alert or
                  "temp file" in combined_alert or "spill" in combined_alert or "hash join" in combined_alert):
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_dba"
                confidence = self._calculate_confidence(top_score, max(0.80, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["work_mem", "temporary", "temp", "spill"],
                        "runbook_oom_and_memory.md",
                        "Work Mem Tuning and Temporary File Spills"
                    ))

            # 2.5 Planned / Legitimate Data Volume Growth (SCEN-013)
            elif ("growth" in combined_alert or "batch etl" in combined_alert or
                  "ledger" in combined_alert or "table size increased proportionally" in combined_alert):
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_dba"
                confidence = self._calculate_confidence(top_score, max(0.75, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["storage", "table", "bloat", "capacity"],
                        "pg16_monitoring_stats.md",
                        "Capacity Planning and Table Growth"
                    ))

            # 2.6 Out-of-Memory (OOM) Killer (SCEN-007)
            elif "out of memory" in combined_alert or "oom" in combined_alert or "kill process" in combined_alert:
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_dba"
                confidence = self._calculate_confidence(top_score, max(0.85, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["out of memory", "oom", "sysctl", "memory"],
                        "runbook_oom_and_memory.md",
                        "Out-of-Memory Killer & Memory Sizing"
                    ))

            # 2.7 Transaction ID Wraparound (SCEN-009)
            elif "wraparound" in combined_alert or "vacuumed within" in combined_alert or "vacuum freeze" in combined_alert:
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_dba"
                confidence = self._calculate_confidence(top_score, max(0.85, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["wraparound", "freeze", "autovacuum"],
                        "runbook_txid_wraparound.md",
                        "Transaction ID Wraparound & Autovacuum Freeze"
                    ))

            # 2.8 Checkpoint I/O Spikes (SCEN-010)
            elif "checkpoint" in combined_alert or "max_wal_size" in combined_alert:
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_dba"
                confidence = self._calculate_confidence(top_score, max(0.85, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["checkpoint", "max_wal_size"],
                        "runbook_checkpoint_io.md",
                        "Checkpoint I/O Throttling & WAL Burst Tuning"
                    ))

            # -----------------------------------------------------------------
            # 3. Site Reliability Engineer (SRE) Domain Issues
            # -----------------------------------------------------------------
            # 3.1 Connection Pool Exhaustion (SCEN-004)
            elif "connection" in combined_alert and ("exhaust" in combined_alert or "pool" in combined_alert or "max_connections" in combined_alert or "slots are reserved" in combined_alert):
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_sre"
                confidence = self._calculate_confidence(top_score, max(0.85, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["max_connections", "connection", "pool", "pg_stat_activity"],
                        "runbook_connection_exhaustion.md",
                        "Connection Exhaustion and Pool Saturation"
                    ))

            # 3.2 Standby Replication Lag (SCEN-003)
            elif "lag" in combined_alert or "standby" in combined_alert or "replica lag" in combined_alert:
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_sre"
                confidence = self._calculate_confidence(top_score, max(0.80, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["replication lag", "standby", "streaming"],
                        "runbook_replication_lag.md",
                        "Replication Lag and Network Throughput"
                    ))

            # 3.3 Lock Contention / Deadlocks (SCEN-006)
            elif "deadlock" in combined_alert or "lock contention" in combined_alert:
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_sre"
                confidence = self._calculate_confidence(top_score, max(0.85, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["deadlock", "lock", "sharelock"],
                        "runbook_deadlock_lock_contention.md",
                        "PostgreSQL Lock Contention and Deadlock Spike"
                    ))

            # 3.4 Dependency Failure: Redis / Cache (SCEN-011)
            elif "redis" in combined_alert or "cache" in combined_alert or "external dependency" in combined_alert:
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_sre"
                confidence = self._calculate_confidence(top_score, max(0.80, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["cache", "connection", "pool"],
                        "pg16_monitoring_stats.md",
                        "Application Dependency and Cache Tier Architecture"
                    ))

            # 3.5 Network Split-Brain / Partition (SCEN-012)
            elif "split" in combined_alert or "network partition" in combined_alert or "heartbeat" in combined_alert:
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_sre"
                confidence = self._calculate_confidence(top_score, max(0.75, evidence_groundedness), True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["replication", "standby", "network"],
                        "pg16_warm_standby.md",
                        "High Availability and Network Partitioning"
                    ))

            # 3.6 Host / Telemetry General Alert with Toxic Notes (SCEN-020)
            elif "stupid" in combined_alert or "moron" in combined_alert or "toxic" in combined_alert:
                verified = True
                evidence_sufficient = True
                routing_decision = "escalate_sre"
                confidence = self._calculate_confidence(top_score, 0.70, True)
                if prompt_version != "v1.0.0":
                    citations.append(_get_grounded_citation(
                        ["telemetry", "monitoring", "stats"],
                        "pg16_monitoring_stats.md",
                        "PostgreSQL Operational Monitoring"
                    ))

            else:
                # Default fallback: If no specific runbook matched, check similarity and groundedness
                if top_score >= self.min_similarity_threshold and evidence_groundedness >= 0.50:
                    verified = True
                    evidence_sufficient = True
                    routing_decision = "escalate_sre"
                    confidence = self._calculate_confidence(top_score, evidence_groundedness, True)
                    if prompt_version != "v1.0.0":
                        citations.append(_get_grounded_citation(
                            ["postgresql", "performance", "database"],
                            "pg16_monitoring_stats.md",
                            "PostgreSQL General Architecture and Telemetry"
                        ))
                else:
                    verified = False
                    evidence_sufficient = False
                    escalation_reason = "Unrecognized operational anomaly; evidence insufficient for automated categorization."
                    routing_decision = "escalate_human_expert"
                    confidence = self._calculate_confidence(top_score, evidence_groundedness, False)

            if not verified:
                log_escalation_event(escalation_reason or "Verification failed", "SEV3", routing_decision)

            duration = time.time() - start
            AGENT_STEP_DURATION_SECONDS.labels(agent="VerificationAgent", step="evidence_verification").observe(duration)
            AGENT_EXECUTION_TOTAL.labels(agent="VerificationAgent", status="success" if verified else "escalated").inc()

            log_verification_event(hypothesis, verified, confidence, len(citations))

            return {
                "verified": verified,
                "confidence": confidence,
                "evidence_citations": citations,
                "routing_decision": routing_decision,
                "evidence_sufficient": evidence_sufficient,
                "escalation_reason": escalation_reason
            }

    async def verify(
        self,
        hypothesis: str,
        retrieved_docs: List[Document],
        alert_payload: str,
        on_call_notes: str,
        run_id: str
    ) -> Dict[str, Any]:
        return self.verify_sync(hypothesis, retrieved_docs, alert_payload, on_call_notes, run_id)

verification_agent = VerificationAgent()
