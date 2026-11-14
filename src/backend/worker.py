"""Asynchronous Agent Worker Process with Bounded Retries and Observability."""
import asyncio
from datetime import datetime, timezone
import os
import signal
import sys
import tempfile
import time
from typing import Any, Dict, Optional

from opentelemetry import trace

from src.agentops.logging import (
    app_logger,
    setup_logger,
    correlation_id_ctx,
    run_id_ctx,
    log_retry_event
)
from src.agentops.metrics import (
    WORKER_ACTIVE_COUNT,
    AGENT_RETRIES_TOTAL,
    INCIDENT_E2E_DURATION_SECONDS
)
from src.agentops.tracing import (
    extract_trace_context,
    trace_span,
    init_tracer
)
from src.config import settings
from src.backend.queue import task_queue
from src.backend.storage import run_storage
from src.backend.agent_service import agent_service
from src.backend.schemas import IncidentStatus, IncidentResultResponse

# Global storage for completed run results (backward compatibility for direct imports)
RESULTS_STORE: Dict[str, Any] = {}

class AgentWorker:
    """Consumes incident triage jobs from queue and executes multi-agent pipeline."""

    def __init__(self, worker_id: Optional[str] = None, max_retries: int = 3, retry_backoff_base: float = 0.5):
        self.worker_id = worker_id or f"worker_{os.getpid()}"
        self.max_retries = max_retries
        self.retry_backoff_base = retry_backoff_base
        self.running = False

        # Cross-platform heartbeat location
        if os.name == "nt":
            self.heartbeat_file = os.path.join(tempfile.gettempdir(), "worker_heartbeat")
        else:
            self.heartbeat_file = "/tmp/worker_heartbeat"

    def update_heartbeat(self):
        """Touches heartbeat file for container liveness probe."""
        try:
            with open(self.heartbeat_file, "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass

    async def process_task_with_retries(self, task: Dict[str, Any]) -> Optional[IncidentResultResponse]:
        """
        Executes agent triage for a single task with bounded retries and exponential backoff.
        """
        run_id = task.get("run_id", "unknown_run")
        alert_id = task.get("alert_id", "unknown_alert")
        correlation_id = task.get("correlation_id", "unknown_corr")

        attempt = 0
        last_error = None

        while attempt <= self.max_retries:
            try:
                attempt += 1
                app_logger.info(
                    f"Worker '{self.worker_id}' triage execution (attempt {attempt}/{self.max_retries + 1}) "
                    f"for run '{run_id}'"
                )

                # Execute triage via agent service adapter
                result: IncidentResultResponse = await agent_service.execute_triage(task)
                return result

            except Exception as exc:
                last_error = str(exc)
                AGENT_RETRIES_TOTAL.labels(agent="Worker", reason="execution_failure").inc()

                if attempt <= self.max_retries:
                    backoff = self.retry_backoff_base * (2 ** (attempt - 1))
                    log_retry_event("Worker", attempt, self.max_retries, last_error)
                    app_logger.warning(
                        f"Transient failure on run '{run_id}' (attempt {attempt}/{self.max_retries + 1}): {exc}. "
                        f"Retrying in {backoff:.2f}s..."
                    )
                    await run_storage.update_status(run_id, IncidentStatus.PROCESSING.value, retry_count=attempt)
                    await asyncio.sleep(backoff)
                else:
                    app_logger.error(
                        f"Exceeded max retries ({self.max_retries}) for run '{run_id}': {exc}",
                        exc_info=True
                    )
                    break

        # If retries exhausted, record permanent failure
        await run_storage.update_status(
            run_id=run_id,
            status=IncidentStatus.FAILED.value,
            error=f"Execution failed after {self.max_retries + 1} attempts: {last_error}",
            retry_count=attempt - 1
        )
        return None

    async def start(self):
        """Starts the worker processing loop."""
        self.running = True
        setup_logger(service_name=f"incident-worker-{self.worker_id}")
        init_tracer(
            service_name=settings.otel_service_name,
            endpoint=settings.otel_exporter_otlp_endpoint,
            enable_tracing=settings.enable_tracing
        )
        app_logger.info(f"Agent Worker '{self.worker_id}' started. Listening on queue '{settings.queue_name}'...")
        await task_queue.initialize()
        await run_storage.initialize()
        WORKER_ACTIVE_COUNT.inc()

        try:
            while self.running:
                self.update_heartbeat()
                task = await task_queue.dequeue(timeout_seconds=1.5)
                if not task:
                    await asyncio.sleep(0.05)
                    continue

                run_id = task.get("run_id", "unknown_run")
                alert_id = task.get("alert_id", "unknown_alert")
                corr_id = task.get("correlation_id", "unknown_corr")

                # Establish distributed context
                corr_token = correlation_id_ctx.set(corr_id)
                run_token = run_id_ctx.set(run_id)

                # Extract OpenTelemetry trace context
                carrier = task.get("_trace_carrier") or {}
                extracted_ctx = extract_trace_context(carrier)

                start_time = time.time()
                tracer = trace.get_tracer(settings.otel_service_name)

                with tracer.start_as_current_span("Worker.process_incident", context=extracted_ctx):
                    try:
                        # Update status: QUEUED -> PROCESSING
                        await run_storage.update_status(run_id, IncidentStatus.PROCESSING.value)

                        # Process with bounded retries
                        result = await self.process_task_with_retries(task)

                        if result:
                            # Save completed result to storage
                            await run_storage.save_result(run_id, result)
                            await run_storage.update_status(run_id, result.status)

                            # Populate global store for backward compatibility
                            RESULTS_STORE[run_id] = result.model_dump()

                            duration = time.time() - start_time
                            INCIDENT_E2E_DURATION_SECONDS.labels(
                                status=result.status,
                                routing_decision=result.routing_decision or "unknown"
                            ).observe(duration)

                            app_logger.info(
                                f"Worker '{self.worker_id}' successfully completed run '{run_id}' in {duration:.2f}s "
                                f"[Status: {result.status}, Confidence: {result.confidence:.2f}]"
                            )
                        else:
                            # Failure already recorded in storage by process_task_with_retries
                            RESULTS_STORE[run_id] = {
                                "run_id": run_id,
                                "alert_id": alert_id,
                                "status": IncidentStatus.FAILED.value,
                                "error": "Execution failed after max retries."
                            }

                    except Exception as fatal_exc:
                        app_logger.error(f"Fatal worker exception on run '{run_id}': {fatal_exc}", exc_info=True)
                        await run_storage.update_status(
                            run_id,
                            IncidentStatus.FAILED.value,
                            error=f"Worker exception: {str(fatal_exc)}"
                        )
                        RESULTS_STORE[run_id] = {
                            "run_id": run_id,
                            "alert_id": alert_id,
                            "status": IncidentStatus.FAILED.value,
                            "error": str(fatal_exc)
                        }

                    finally:
                        correlation_id_ctx.reset(corr_token)
                        run_id_ctx.reset(run_token)

        finally:
            WORKER_ACTIVE_COUNT.dec()
            app_logger.info(f"Agent Worker '{self.worker_id}' shutdown cleanly.")

    def stop(self):
        """Stops the worker processing loop."""
        self.running = False

async def run_worker():
    worker = AgentWorker()

    def handle_sig(sig, frame):
        worker.stop()

    if os.name != "nt":
        signal.signal(signal.SIGINT, handle_sig)
        signal.signal(signal.SIGTERM, handle_sig)

    await worker.start()

if __name__ == "__main__":
    asyncio.run(run_worker())
