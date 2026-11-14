"""Asynchronous Agent Worker Process."""
import asyncio
import os
import signal
import sys
import time
from typing import Optional
from src.agentops.logging import app_logger, setup_logger
from src.agentops.metrics import WORKER_ACTIVE_COUNT
from src.backend.queue import task_queue
from src.agents.orchestrator import incident_orchestrator
from src.config import settings

# Global storage for completed run results
RESULTS_STORE = {}

class AgentWorker:
    """Consumes incident triage jobs from queue and executes multi-agent pipeline."""
    def __init__(self, worker_id: Optional[str] = None):
        self.worker_id = worker_id or f"worker_{os.getpid()}"
        self.running = False
        self.heartbeat_file = "/tmp/worker_heartbeat"

    def update_heartbeat(self):
        try:
            with open(self.heartbeat_file, "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass

    async def start(self):
        self.running = True
        setup_logger(service_name=f"incident-worker-{self.worker_id}")
        app_logger.info(f"Agent Worker '{self.worker_id}' started. Listening on queue '{settings.queue_name}'...")
        await task_queue.initialize()
        WORKER_ACTIVE_COUNT.inc()

        try:
            while self.running:
                self.update_heartbeat()
                task = await task_queue.dequeue(timeout_seconds=2.0)
                if not task:
                    await asyncio.sleep(0.1)
                    continue

                run_id = task.get("run_id")
                app_logger.info(f"Worker '{self.worker_id}' processing run '{run_id}'")

                try:
                    result = await incident_orchestrator.process_incident(
                        alert_payload=task.get("alert_payload", ""),
                        on_call_notes=task.get("on_call_notes", ""),
                        client_id=task.get("client_id", "worker"),
                        correlation_id=task.get("correlation_id"),
                        run_id=run_id,
                        prompt_version=task.get("prompt_version") or settings.active_prompt_version
                    )
                    RESULTS_STORE[run_id] = result
                except Exception as exc:
                    app_logger.error(f"Worker '{self.worker_id}' failed processing run '{run_id}': {exc}", exc_info=True)
                    RESULTS_STORE[run_id] = {"run_id": run_id, "status": "failed", "error": str(exc)}

        finally:
            WORKER_ACTIVE_COUNT.dec()
            app_logger.info(f"Agent Worker '{self.worker_id}' shutdown cleanly.")

    def stop(self):
        self.running = False

async def main():
    worker = AgentWorker()
    
    def handle_sig(sig, frame):
        worker.stop()

    signal.signal(signal.SIGINT, handle_sig)
    signal.signal(signal.SIGTERM, handle_sig)

    await worker.start()

if __name__ == "__main__":
    asyncio.run(main())
