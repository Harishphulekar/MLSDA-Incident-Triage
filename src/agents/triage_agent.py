"""Triage Agent: Alert classification, initial hypothesis, and severity scoring."""
import time
from typing import Any, Dict
from src.agentops.logging import log_agent_event
from src.agentops.tracing import trace_span
from src.agentops.metrics import AGENT_STEP_DURATION_SECONDS, AGENT_EXECUTION_TOTAL
from src.agentops.stub_llm import stub_llm
from src.agentops.prompt_manager import prompt_manager

class TriageAgent:
    """Performs initial triage and formulates preliminary failure hypothesis."""
    def __init__(self, prompt_version: str = "v1.1.0"):
        self.prompt_version = prompt_version

    def triage_sync(self, alert_payload: str, on_call_notes: str, run_id: str, prompt_version: str = "v1.1.0") -> Dict[str, Any]:
        start = time.time()
        with trace_span("TriageAgent.execute", {"incident.agent": "TriageAgent", "incident.run_id": run_id}):
            log_agent_event("TriageAgent", "triage_initial", "start", {"alert": alert_payload[:50]})
            
            prompt_tpl = prompt_manager.get_prompt(prompt_version)
            user_prompt = prompt_tpl.format_user_prompt(
                alert_payload=alert_payload,
                on_call_notes=on_call_notes,
                retrieved_context="Pending knowledge retrieval..."
            )

            response = stub_llm.generate_response_sync(
                system_prompt=prompt_tpl.system_prompt,
                user_prompt=user_prompt,
                run_id=run_id,
                agent_name="TriageAgent",
                step="triage_classification",
                prompt_version=prompt_version
            )

            duration = time.time() - start
            AGENT_STEP_DURATION_SECONDS.labels(agent="TriageAgent", step="triage_classification").observe(duration)
            AGENT_EXECUTION_TOTAL.labels(agent="TriageAgent", status="success").inc()

            log_agent_event("TriageAgent", "triage_initial", "completed", {
                "cause_class": response.get("cause_class"),
                "severity": response.get("severity")
            })

            return response

    async def triage(self, alert_payload: str, on_call_notes: str, run_id: str, prompt_version: str = "v1.1.0") -> Dict[str, Any]:
        return self.triage_sync(alert_payload, on_call_notes, run_id, prompt_version)

triage_agent = TriageAgent()
