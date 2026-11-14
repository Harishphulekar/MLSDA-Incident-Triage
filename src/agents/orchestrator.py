"""Multi-Agent Orchestrator with Guardrails and Full Observability Integration."""
import time
import uuid
from typing import Any, Dict, Optional
from src.agentops.logging import (
    app_logger,
    correlation_id_ctx,
    run_id_ctx,
    log_agent_event,
    log_escalation_event
)
from src.agentops.tracing import trace_span
from src.agentops.metrics import (
    INCIDENT_E2E_DURATION_SECONDS,
    AGENT_STEPS_PER_RUN,
    AGENT_EXECUTION_TOTAL
)
from src.agentops.guardrails.injection_detector import injection_detector
from src.agentops.guardrails.toxicity import toxicity_checker
from src.agentops.guardrails.output_filter import output_filter
from src.agentops.caching import incident_cache
from src.agentops.cost_tracker import cost_tracker
from src.agents.triage_agent import triage_agent
from src.agents.retrieval_agent import retrieval_agent
from src.agents.verification_agent import verification_agent

class IncidentOrchestrator:
    """Coordinates end-to-end incident triage, verification, guardrails, and telemetry."""

    def process_incident_sync(
        self,
        alert_payload: str,
        on_call_notes: str,
        client_id: str = "default_client",
        correlation_id: Optional[str] = None,
        run_id: Optional[str] = None,
        prompt_version: str = "v1.1.0"
    ) -> Dict[str, Any]:
        start_time = time.time()
        
        # 1. Establish Run ID and Correlation ID context
        r_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        c_id = correlation_id or f"corr_{uuid.uuid4().hex[:12]}"
        
        correlation_id_token = correlation_id_ctx.set(c_id)
        run_id_token = run_id_ctx.set(r_id)

        try:
            with trace_span("IncidentPipeline.e2e", {
                "incident.run_id": r_id,
                "incident.correlation_id": c_id,
                "client.id": client_id,
                "prompt.version": prompt_version
            }):
                app_logger.info(f"Starting incident triage pipeline for run '{r_id}'")

                # 2. Security Guardrail: Input Injection Defense
                combined_input = f"{alert_payload} {on_call_notes}"
                injection_verdict = injection_detector.evaluate(combined_input)
                if not injection_verdict.is_safe:
                    app_logger.warning(
                        f"Security Guardrail Triggered: Prompt injection detected in run {r_id}",
                        extra={"category": injection_verdict.category, "risk_score": injection_verdict.risk_score}
                    )
                    log_escalation_event("Prompt injection blocked", "SEV1", "security_soc")
                    AGENT_EXECUTION_TOTAL.labels(agent="SecurityGuardrail", status="blocked").inc()
                    
                    return {
                        "run_id": r_id,
                        "correlation_id": c_id,
                        "status": "blocked",
                        "cause_class": "Security Violation: Prompt Injection",
                        "severity": "SEV1",
                        "hypothesis": "Input contained disallowed prompt injection or system override instructions.",
                        "recommended_actions": ["Notify InfoSec SOC of attempted prompt injection attack."],
                        "routing_decision": "security_soc",
                        "evidence_sufficient": False,
                        "guardrail_verdict": injection_verdict.model_dump(),
                        "prompt_version": prompt_version,
                        "cost": cost_tracker.get_run_aggregates(r_id).model_dump()
                    }

                # 3. Security Guardrail: Toxicity Check
                toxicity_verdict = toxicity_checker.check_text(combined_input)
                if toxicity_verdict.is_toxic:
                    app_logger.warning(f"Toxicity detected in run {r_id}: {toxicity_verdict.categories}")

                # 4. Caching Check (Safe bypass for live state incidents)
                cached_run = incident_cache.get_cached_run(alert_payload, on_call_notes)
                if cached_run:
                    app_logger.info("Serving incident triage from safe response cache")
                    cached_run["run_id"] = r_id
                    cached_run["correlation_id"] = c_id
                    cached_run["cache_hit"] = True
                    return cached_run

                # 5. Multi-Agent Step 1: Triage Agent
                triage_res = triage_agent.triage_sync(
                    alert_payload=alert_payload,
                    on_call_notes=on_call_notes,
                    run_id=r_id,
                    prompt_version=prompt_version
                )

                # 6. Multi-Agent Step 2: Retrieval Agent
                retrieved_docs = retrieval_agent.retrieve_context_sync(
                    alert_payload=alert_payload,
                    on_call_notes=on_call_notes,
                    preliminary_hypothesis=triage_res.get("hypothesis", ""),
                    run_id=r_id
                )

                # 7. Multi-Agent Step 3: Verification Agent
                verification_res = verification_agent.verify_sync(
                    hypothesis=triage_res.get("hypothesis", ""),
                    retrieved_docs=retrieved_docs,
                    alert_payload=alert_payload,
                    on_call_notes=on_call_notes,
                    run_id=r_id
                )

                # 8. Merge Pipeline Result
                merged_output = {
                    "run_id": r_id,
                    "correlation_id": c_id,
                    "status": "completed",
                    "cause_class": triage_res.get("cause_class", "Unknown"),
                    "severity": triage_res.get("severity", "SEV3"),
                    "hypothesis": triage_res.get("hypothesis", ""),
                    "evidence_citations": verification_res.get("evidence_citations", []),
                    "recommended_actions": triage_res.get("recommended_actions", []),
                    "routing_decision": verification_res.get("routing_decision", "escalate_sre"),
                    "confidence": verification_res.get("confidence", 0.5),
                    "evidence_sufficient": verification_res.get("evidence_sufficient", False),
                    "escalation_reason": verification_res.get("escalation_reason"),
                    "prompt_version": prompt_version
                }

                # 9. Security Guardrail: Output Filter (Enforce Human Advisory, Forbid Remediation Claims)
                corpus_texts = [d.content for d in retrieved_docs]
                filter_res = output_filter.filter_response(merged_output, retrieved_corpus_docs=corpus_texts)
                final_output = filter_res.sanitized_output

                # 10. Record Cost & Execution Steps
                steps_count = 3  # Triage, Retrieval, Verification
                AGENT_STEPS_PER_RUN.observe(steps_count)
                
                cost_summary = cost_tracker.get_run_aggregates(r_id)
                final_output["cost"] = cost_summary.model_dump()

                # Cache safe completed run
                incident_cache.set_cached_run(alert_payload, on_call_notes, final_output)

                duration = time.time() - start_time
                INCIDENT_E2E_DURATION_SECONDS.labels(
                    status="success",
                    routing_decision=final_output.get("routing_decision", "unknown")
                ).observe(duration)

                app_logger.info(
                    f"Incident triage completed for run '{r_id}' in {duration:.2f}s "
                    f"[Route: {final_output.get('routing_decision')}, Cost: ${cost_summary.total_cost_dollars:.6f}]"
                )

                return final_output

        finally:
            correlation_id_ctx.reset(correlation_id_token)
            run_id_ctx.reset(run_id_token)

    async def process_incident(
        self,
        alert_payload: str,
        on_call_notes: str,
        client_id: str = "default_client",
        correlation_id: Optional[str] = None,
        run_id: Optional[str] = None,
        prompt_version: str = "v1.1.0"
    ) -> Dict[str, Any]:
        return self.process_incident_sync(
            alert_payload, on_call_notes, client_id, correlation_id, run_id, prompt_version
        )

incident_orchestrator = IncidentOrchestrator()
