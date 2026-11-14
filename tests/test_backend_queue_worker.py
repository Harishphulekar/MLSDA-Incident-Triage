"""Automated Tests for TaskQueue, Background Worker, and RunStorage."""
import asyncio
import pytest

from src.backend.queue import TaskQueue
from src.backend.storage import RunStorage
from src.backend.worker import AgentWorker
from src.backend.agent_service import MockAgentAdapter, agent_service
from src.backend.schemas import IncidentStatus, IncidentResultResponse

@pytest.fixture(autouse=True)
def clean_environment():
    agent_service.set_adapter(MockAgentAdapter())
    yield
    agent_service.set_adapter(MockAgentAdapter())

@pytest.mark.asyncio
async def test_queue_enqueue_and_dequeue_with_trace_context():
    """Test task queue enqueuing, trace context carrier injection, and dequeuing."""
    q = TaskQueue()
    await q.initialize()

    task = {
        "run_id": "run_test_q_01",
        "alert_id": "ALT-Q-01",
        "metric": "disk_usage",
        "observed_value": 85
    }

    enqueued_id = await q.enqueue(task)
    assert enqueued_id == "run_test_q_01"
    assert "_trace_carrier" in task

    depth = await q.get_depth()
    assert depth >= 1

    dequeued = await q.dequeue(timeout_seconds=0.5)
    assert dequeued is not None
    assert dequeued["run_id"] == "run_test_q_01"
    assert "_trace_carrier" in dequeued

@pytest.mark.asyncio
async def test_storage_lifecycle_transitions():
    """Test run status state machine transitions: QUEUED -> PROCESSING -> COMPLETED."""
    storage = RunStorage()
    await storage.initialize()

    # 1. Create run (QUEUED)
    status_rec = await storage.create_run(
        run_id="run_storage_01",
        alert_id="ALT-ST-01",
        correlation_id="corr-st-01",
        idempotency_key="idemp-st-01"
    )
    assert status_rec.status == IncidentStatus.QUEUED.value
    assert status_rec.retry_count == 0

    # Verify idempotency lookup
    found_run = await storage.get_run_by_idempotency_key("idemp-st-01")
    assert found_run == "run_storage_01"

    # 2. Update to PROCESSING
    updated = await storage.update_status("run_storage_01", IncidentStatus.PROCESSING.value)
    assert updated.status == IncidentStatus.PROCESSING.value
    assert updated.queue_duration_seconds is not None

    # 3. Save result and mark COMPLETED
    dummy_res = {
        "run_id": "run_storage_01",
        "alert_id": "ALT-ST-01",
        "status": "completed",
        "symptom_class": "Disk Saturation",
        "probable_root_cause": "WAL Retention",
        "severity": "warning",
        "confidence": 0.95,
        "created_at": status_rec.created_at,
        "completed_at": status_rec.created_at
    }
    await storage.save_result("run_storage_01", dummy_res)
    completed = await storage.update_status("run_storage_01", IncidentStatus.COMPLETED.value)
    assert completed.status == IncidentStatus.COMPLETED.value
    assert completed.completed_at is not None

    # Retrieve stored result
    fetched_res = await storage.get_result("run_storage_01")
    assert fetched_res["symptom_class"] == "Disk Saturation"

@pytest.mark.asyncio
async def test_worker_processing_success():
    """Test worker processing a single task successfully."""
    from src.backend.storage import run_storage
    from src.backend.queue import task_queue

    storage = run_storage
    await storage.initialize()
    await task_queue.initialize()

    task = {
        "run_id": "run_worker_success_01",
        "alert_id": "ALT-WS-01",
        "database": "postgresql",
        "metric": "disk_usage",
        "observed_value": 88,
        "threshold": 80,
        "severity": "warning",
        "correlation_id": "corr_ws_01",
        "client_id": "worker_test"
    }

    await storage.create_run(task["run_id"], task["alert_id"], task["correlation_id"])
    await task_queue.enqueue(task)

    worker = AgentWorker(worker_id="test_worker_01", max_retries=2)
    result = await worker.process_task_with_retries(task)

    assert result is not None
    assert result.status == "completed"
    assert result.run_id == "run_worker_success_01"

@pytest.mark.asyncio
async def test_worker_bounded_retries_and_failure():
    """Test worker retry loop on transient errors and eventual failure status."""
    from src.backend.storage import run_storage

    storage = run_storage
    await storage.initialize()

    class FailingAdapter:
        def __init__(self):
            self.calls = 0
        async def triage_incident(self, task_payload):
            self.calls += 1
            raise RuntimeError(f"Simulated network timeout (call {self.calls})")

    failing_adapter = FailingAdapter()
    agent_service.set_adapter(failing_adapter)

    task = {
        "run_id": "run_worker_fail_01",
        "alert_id": "ALT-WF-01",
        "metric": "replication_lag",
        "observed_value": 999,
        "correlation_id": "corr_wf_01"
    }

    await storage.create_run(task["run_id"], task["alert_id"], task["correlation_id"])

    # Worker with max 2 retries (total 3 attempts) and very low backoff for fast test
    worker = AgentWorker(worker_id="test_failing_worker", max_retries=2, retry_backoff_base=0.01)
    result = await worker.process_task_with_retries(task)

    assert result is None  # Failed
    assert failing_adapter.calls == 3  # Initial + 2 retries

    final_status = await storage.get_status(task["run_id"])
    assert final_status.status == IncidentStatus.FAILED.value
    assert "Exceeded max retries" in final_status.error or "failed after" in final_status.error
