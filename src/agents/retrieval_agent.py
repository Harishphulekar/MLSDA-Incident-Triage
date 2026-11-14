"""Retrieval Agent: Resolves incident context against runbooks and official docs."""
import time
from typing import Any, Dict, List
from src.agentops.logging import log_agent_event
from src.agentops.tracing import trace_span
from src.agentops.metrics import AGENT_STEP_DURATION_SECONDS, AGENT_EXECUTION_TOTAL
from src.rag.retriever import retriever, Document

class RetrievalAgent:
    """Retrieves authoritative runbooks and technical documentation matching incident symptoms."""
    
    def retrieve_context_sync(self, alert_payload: str, on_call_notes: str, preliminary_hypothesis: str, run_id: str) -> List[Document]:
        start = time.time()
        with trace_span("RetrievalAgent.execute", {"incident.agent": "RetrievalAgent", "incident.run_id": run_id}):
            log_agent_event("RetrievalAgent", "retrieve_runbooks", "start")

            query = f"{alert_payload} {on_call_notes} {preliminary_hypothesis}"
            docs = retriever.retrieve(query=query, top_k=3)

            duration = time.time() - start
            AGENT_STEP_DURATION_SECONDS.labels(agent="RetrievalAgent", step="retrieve_runbooks").observe(duration)
            AGENT_EXECUTION_TOTAL.labels(agent="RetrievalAgent", status="success").inc()

            log_agent_event("RetrievalAgent", "retrieve_runbooks", "completed", {
                "matched_documents": [d.source for d in docs]
            })

            return docs

    async def retrieve_context(self, alert_payload: str, on_call_notes: str, preliminary_hypothesis: str, run_id: str) -> List[Document]:
        return self.retrieve_context_sync(alert_payload, on_call_notes, preliminary_hypothesis, run_id)

retrieval_agent = RetrievalAgent()
