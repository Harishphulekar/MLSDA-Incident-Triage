"""FastAPI Main Application Gateway with Middleware, Observability, and Endpoints."""
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse

from src.config import settings
from src.agentops.logging import setup_logger, app_logger, correlation_id_ctx
from src.agentops.tracing import init_tracer
from src.agentops.metrics import (
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    get_metrics_output,
    CONTENT_TYPE_LATEST
)
from src.agentops.rate_limiter import rate_limiter
from src.agentops.feedback import feedback_manager
from src.agentops.prompt_manager import prompt_manager
from src.backend.schemas import (
    IncidentSubmissionRequest,
    IncidentSubmissionResponse,
    FeedbackSubmissionRequest,
    FeedbackStatsResponse
)
from src.backend.queue import task_queue
from src.backend.worker import RESULTS_STORE
from src.agents.orchestrator import incident_orchestrator

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_logger(service_name=settings.service_name, level=settings.log_level)
    init_tracer(
        service_name=settings.otel_service_name,
        endpoint=settings.otel_exporter_otlp_endpoint,
        enable_tracing=settings.enable_tracing
    )
    await task_queue.initialize()
    app_logger.info("Incident Triage API Gateway started successfully.")
    yield
    # Shutdown
    app_logger.info("Incident Triage API Gateway shutting down.")

app = FastAPI(
    title="Production Incident Triage & Runbook Assistant",
    description="AgentOps, Observability, and Multi-Agent Production Incident Triage Assistant API",
    version="1.0.0",
    lifespan=lifespan
)

# -----------------------------------------------------------------------------
# Middlewares
# -----------------------------------------------------------------------------
@app.middleware("http")
async def observability_and_rate_limit_middleware(request: Request, call_next):
    # 1. Correlation ID handling
    incoming_corr_id = request.headers.get("X-Correlation-ID") or f"corr_{uuid.uuid4().hex[:12]}"
    token = correlation_id_ctx.set(incoming_corr_id)

    # 2. Rate Limiting Check
    client_id = request.headers.get("X-Client-ID") or request.client.host if request.client else "unknown"
    if settings.rate_limit_enabled and not request.url.path.startswith(("/health", "/metrics")):
        allowed, remaining, retry_after = rate_limiter.is_allowed(client_id)
        if not allowed:
            correlation_id_ctx.reset(token)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"error": "Rate limit exceeded. Too many requests.", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after), "X-Correlation-ID": incoming_corr_id}
            )

    start_time = time.time()
    endpoint = request.url.path
    method = request.method

    try:
        response: Response = await call_next(request)
        status_code = str(response.status_code)
    except Exception as exc:
        status_code = "500"
        app_logger.error(f"Unhandled exception on {method} {endpoint}: {exc}", exc_info=True)
        response = JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal Server Error", "detail": str(exc)},
            headers={"X-Correlation-ID": incoming_corr_id}
        )

    duration = time.time() - start_time
    HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=status_code).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(duration)

    response.headers["X-Correlation-ID"] = incoming_corr_id
    correlation_id_ctx.reset(token)
    return response

# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness probe."""
    return {"status": "healthy", "service": settings.service_name, "version": "1.0.0"}

@app.get("/health/ready", tags=["Health"])
async def readiness_check():
    """Readiness probe."""
    return {"status": "ready", "queue_depth": await task_queue.get_depth(), "active_prompt": settings.active_prompt_version}

@app.get("/metrics", tags=["Observability"])
async def prometheus_metrics():
    """Prometheus metrics scrape target."""
    return PlainTextResponse(get_metrics_output(), media_type=CONTENT_TYPE_LATEST)

@app.post("/api/v1/incidents", response_model=IncidentSubmissionResponse, status_code=status.HTTP_200_OK, tags=["Incidents"])
async def submit_incident(req: IncidentSubmissionRequest):
    """Submits an infrastructure alert for automated multi-agent triage."""
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    corr_id = req.correlation_id or correlation_id_ctx.get() or f"corr_{uuid.uuid4().hex[:12]}"
    p_version = req.prompt_version or settings.active_prompt_version

    if req.sync_mode:
        # Synchronous execution
        result = await incident_orchestrator.process_incident(
            alert_payload=req.alert_payload,
            on_call_notes=req.on_call_notes,
            client_id=req.client_id,
            correlation_id=corr_id,
            run_id=run_id,
            prompt_version=p_version
        )
        RESULTS_STORE[run_id] = result
        return IncidentSubmissionResponse(
            run_id=run_id,
            correlation_id=corr_id,
            status="completed",
            message="Incident triage completed successfully.",
            result=result
        )
    else:
        # Enqueue for asynchronous worker processing
        task = {
            "run_id": run_id,
            "correlation_id": corr_id,
            "alert_payload": req.alert_payload,
            "on_call_notes": req.on_call_notes,
            "client_id": req.client_id,
            "prompt_version": p_version
        }
        await task_queue.enqueue(task)
        return IncidentSubmissionResponse(
            run_id=run_id,
            correlation_id=corr_id,
            status="queued",
            message="Incident triage enqueued for asynchronous worker processing.",
            result=None
        )

@app.get("/api/v1/incidents/{run_id}", tags=["Incidents"])
async def get_incident_status(run_id: str):
    """Retrieves triage output for a given run ID."""
    if run_id in RESULTS_STORE:
        return RESULTS_STORE[run_id]
    raise HTTPException(status_code=404, detail=f"Incident run '{run_id}' not found or still processing.")

@app.post("/api/v1/feedback", tags=["Feedback"])
async def submit_feedback(req: FeedbackSubmissionRequest):
    """Submits human engineer feedback on an incident run."""
    record = feedback_manager.record_feedback(
        run_id=req.run_id,
        satisfactory=req.satisfactory,
        reason=req.reason or "",
        timestamp=req.timestamp
    )
    return {"status": "success", "message": "Feedback recorded", "feedback_id": record.feedback_id}

@app.get("/api/v1/feedback/stats", response_model=FeedbackStatsResponse, tags=["Feedback"])
async def get_feedback_statistics():
    """Retrieves aggregate feedback metrics."""
    return feedback_manager.get_stats()

@app.get("/api/v1/prompts", tags=["Prompts"])
async def list_prompts():
    """Lists available prompt template versions."""
    return {
        "active_version": settings.active_prompt_version,
        "available_versions": prompt_manager.list_versions()
    }
