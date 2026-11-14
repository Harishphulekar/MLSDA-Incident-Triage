"""Agent Service Adapter Layer: Connects Backend to Multi-Agent Orchestration."""
from datetime import datetime, timezone
import time
from typing import Any, Dict, List, Optional

from src.agentops.logging import app_logger
from src.agentops.tracing import trace_span
from src.backend.schemas import IncidentResultResponse

class BaseAgentAdapter:
    """Interface for incident triage agent adapters."""
    async def triage_incident(self, task_payload: Dict[str, Any]) -> IncidentResultResponse:
        raise NotImplementedError

class RealAgentOrchestratorAdapter(BaseAgentAdapter):
    """
    Production adapter that invokes Member 3's Multi-Agent Orchestrator
    (Triage Agent, Retrieval Agent, and Verification Agent).
    """

    async def triage_incident(self, task_payload: Dict[str, Any]) -> IncidentResultResponse:
        from src.agents.orchestrator import incident_orchestrator

        run_id = task_payload.get("run_id", "unknown_run")
        alert_id = task_payload.get("alert_id", "unknown_alert")
        correlation_id = task_payload.get("correlation_id", "unknown_corr")
        prompt_version = task_payload.get("prompt_version", "v1.1.0")
        client_id = task_payload.get("client_id", "backend_worker")
        created_at = task_payload.get("created_at") or datetime.now(timezone.utc).isoformat()

        # Build comprehensive incident text representation for multi-agent reasoning
        db = task_payload.get("database", "postgresql")
        db_ver = task_payload.get("database_version", "16")
        metric = task_payload.get("metric", "metric")
        obs_val = task_payload.get("observed_value", 0)
        thresh = task_payload.get("threshold", 0)
        sev = task_payload.get("severity", "warning")
        notes = task_payload.get("on_call_note", "") or task_payload.get("on_call_notes", "")

        # Format alert narrative
        if "raw_alert_text" in task_payload and task_payload["raw_alert_text"]:
            alert_narrative = task_payload["raw_alert_text"]
        else:
            alert_narrative = (
                f"Alert {alert_id}: Target database {db} (version {db_ver}) reported {metric} "
                f"at {obs_val} exceeding threshold {thresh}. Alert severity: {sev}."
            )

        with trace_span("AgentServiceAdapter.execute", {
            "incident.run_id": run_id,
            "incident.alert_id": alert_id,
            "incident.database": db
        }):
            app_logger.info(f"Invoking Member 3 Orchestrator for run '{run_id}', alert '{alert_id}'")

            # Invoke Member 3 multi-agent pipeline
            orchestrator_output = await incident_orchestrator.process_incident(
                alert_payload=alert_narrative,
                on_call_notes=notes,
                client_id=client_id,
                correlation_id=correlation_id,
                run_id=run_id,
                prompt_version=prompt_version
            )

            completed_at = datetime.now(timezone.utc).isoformat()

            # Map orchestrator output fields to unified contract
            symptom_class = orchestrator_output.get("cause_class") or "General Infrastructure Degradation"
            probable_root_cause = orchestrator_output.get("hypothesis") or "Pending root cause determination."
            severity_assessed = orchestrator_output.get("severity") or sev
            citations = orchestrator_output.get("evidence_citations") or []
            recommended_actions = orchestrator_output.get("recommended_actions") or [
                "Inspect database telemetry and operational logs.",
                "Review active connection pools and disk utilization."
            ]
            routing_decision = orchestrator_output.get("routing_decision") or "escalate_sre"
            confidence = float(orchestrator_output.get("confidence", 0.75))
            escalation_reason = orchestrator_output.get("escalation_reason")

            # Determine escalation requirement
            escalation_required = bool(
                escalation_reason or
                (routing_decision and routing_decision.startswith("escalate_")) or
                not orchestrator_output.get("evidence_sufficient", True)
            )

            # Extract human-readable evidence points
            evidence = []
            for c in citations:
                passage = c.get("quoted_passage") or c.get("section") or c.get("source")
                if passage:
                    evidence.append(passage)
            if not evidence and "evidence" in orchestrator_output:
                evidence = orchestrator_output["evidence"]
            if not evidence:
                evidence.append(f"Observed {metric} = {obs_val} (threshold: {thresh}) on {db}.")

            final_status = "escalated" if escalation_required and not orchestrator_output.get("evidence_sufficient") else "completed"
            if orchestrator_output.get("status") == "blocked":
                final_status = "blocked"

            return IncidentResultResponse(
                run_id=run_id,
                alert_id=alert_id,
                status=final_status,
                symptom_class=symptom_class,
                probable_root_cause=probable_root_cause,
                severity=severity_assessed,
                evidence=evidence,
                documentation_citations=citations,
                recommended_actions=recommended_actions,
                escalation_required=escalation_required,
                escalation_reason=escalation_reason,
                confidence=confidence,
                routing_decision=routing_decision,
                created_at=created_at,
                completed_at=completed_at,
                cost=orchestrator_output.get("cost")
            )

class MockAgentAdapter(BaseAgentAdapter):
    """
    Mock agent adapter for development, testing, and isolated staging environments.
    Explicitly labeled as mock to adhere strictly to project integrity guidelines.
    """

    async def triage_incident(self, task_payload: Dict[str, Any]) -> IncidentResultResponse:
        run_id = task_payload.get("run_id", "mock_run")
        alert_id = task_payload.get("alert_id", "mock_alert")
        created_at = task_payload.get("created_at") or datetime.now(timezone.utc).isoformat()
        metric = task_payload.get("metric", "disk_usage")
        obs_val = task_payload.get("observed_value", 85)

        return IncidentResultResponse(
            run_id=run_id,
            alert_id=alert_id,
            status="completed",
            symptom_class=f"[MOCK] Simulated {metric} Anomaly",
            probable_root_cause=f"[MOCK-ONLY] Synthetic test root cause for {metric}={obs_val}.",
            severity=task_payload.get("severity", "warning"),
            evidence=[f"[MOCK EVIDENCE] Simulated reading: {metric} at {obs_val}"],
            documentation_citations=[{
                "source": "mock_runbook.md",
                "section": "Simulated Diagnostic Section",
                "quoted_passage": "Mock documentation reference for automated test validation."
            }],
            recommended_actions=["[MOCK] Test advisory step 1", "[MOCK] Test advisory step 2"],
            escalation_required=False,
            escalation_reason=None,
            confidence=0.88,
            routing_decision="mock_sre",
            created_at=created_at,
            completed_at=datetime.now(timezone.utc).isoformat(),
            cost={"total_tokens": 100, "total_cost_dollars": 0.000015}
        )

class AgentService:
    """Primary service entrypoint for multi-agent triage operations."""

    def __init__(self, adapter: Optional[BaseAgentAdapter] = None):
        # Default to real multi-agent orchestrator
        self.adapter = adapter or RealAgentOrchestratorAdapter()

    def set_adapter(self, adapter: BaseAgentAdapter):
        """Allows switching adapter for unit testing or offline staging."""
        self.adapter = adapter

    async def execute_triage(self, task_payload: Dict[str, Any]) -> IncidentResultResponse:
        return await self.adapter.triage_incident(task_payload)

agent_service = AgentService()
