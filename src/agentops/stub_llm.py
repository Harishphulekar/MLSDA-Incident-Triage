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
        elif "connection" in combined and ("exhausted" in combined or "max_connections" in combined):
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
                    "Verify PgBouncer connection pool saturation and queue depth."
                ],
                "routing_decision": "escalate_sre",
                "confidence": 0.92,
                "evidence_sufficient": True,
                "escalation_reason": None
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
