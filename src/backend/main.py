"""FastAPI Main Application Gateway with Middleware, Observability, and Endpoints."""
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Union

from fastapi import FastAPI, Request, Response, HTTPException, status, Query, Header
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from src.config import settings
from src.agentops.logging import setup_logger, app_logger, correlation_id_ctx, run_id_ctx, sanitize_value
from src.agentops.tracing import init_tracer, trace_span
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
    IncidentAlertRequest,
    IncidentSubmissionRequest,
    IncidentSubmissionResponse,
    IncidentStatusResponse,
    IncidentResultResponse,
    IncidentStatus,
    QuarantineRecord,
    QuarantineListResponse,
    FeedbackSubmissionRequest,
    FeedbackStatsResponse
)
from src.backend.validator import incident_validator
from src.backend.quarantine import quarantine_store
from src.backend.storage import run_storage
from src.backend.queue import task_queue
from src.backend.agent_service import agent_service
from src.backend.worker import RESULTS_STORE

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    setup_logger(service_name=settings.service_name, level=settings.log_level)
    init_tracer(
        service_name=settings.otel_service_name,
        endpoint=settings.otel_exporter_otlp_endpoint,
        enable_tracing=settings.enable_tracing
    )
    await task_queue.initialize()
    await run_storage.initialize()
    app_logger.info("Incident Triage API Gateway started successfully.")
    yield
    # Shutdown sequence
    app_logger.info("Incident Triage API Gateway shutting down.")

app = FastAPI(
    title="Production Incident Triage & Runbook Assistant",
    description=(
        "Production Incident Triage & Runbook Assistant API Gateway.\n\n"
        "Provides validated incident ingestion, quarantine review, asynchronous "
        "Redis-backed task dispatching, multi-agent triage verification, and lifecycle tracking."
    ),
    version="1.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# -----------------------------------------------------------------------------
# Security & CORS Middleware
# -----------------------------------------------------------------------------
cors_origins_env = os.getenv("CORS_ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "X-Run-ID", "Retry-After"]
)

# -----------------------------------------------------------------------------
# Observability and Rate Limit Middleware
# -----------------------------------------------------------------------------
@app.middleware("http")
async def observability_and_rate_limit_middleware(request: Request, call_next):
    # 1. Correlation ID handling
    incoming_corr_id = (
        request.headers.get("X-Correlation-ID") or
        request.headers.get("Correlation-ID") or
        f"corr_{uuid.uuid4().hex[:12]}"
    )
    token = correlation_id_ctx.set(incoming_corr_id)

    # 2. Rate Limiting Check (bypass for health and metrics)
    client_id = (
        request.headers.get("X-Client-ID") or
        (request.client.host if request.client else "unknown")
    )
    if settings.rate_limit_enabled and not request.url.path.startswith(("/health", "/metrics", "/api/v1/health", "/api/v1/ready", "/api/v1/metrics")):
        allowed, remaining, retry_after = rate_limiter.is_allowed(client_id)
        if not allowed:
            correlation_id_ctx.reset(token)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded. Too many requests.",
                    "client_id": client_id,
                    "retry_after_seconds": retry_after
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-Correlation-ID": incoming_corr_id
                }
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
            content={
                "error": "Internal Server Error",
                "detail": "An unexpected error occurred. Request has been safely logged.",
                "correlation_id": incoming_corr_id
            },
            headers={"X-Correlation-ID": incoming_corr_id}
        )

    duration = time.time() - start_time
    HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=status_code).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(duration)

    response.headers["X-Correlation-ID"] = incoming_corr_id
    correlation_id_ctx.reset(token)
    return response

# -----------------------------------------------------------------------------
# Global Exception Handlers
# -----------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    corr_id = correlation_id_ctx.get() or "none"
    errors = [f"{' -> '.join(str(l) for l in err['loc'])}: {err['msg']}" for err in exc.errors()]
    app_logger.warning(f"Request validation failure on {request.url.path}: {errors}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation Error",
            "message": "The incoming payload failed schema or parameter validation.",
            "validation_errors": errors,
            "correlation_id": corr_id
        },
        headers={"X-Correlation-ID": corr_id}
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    corr_id = correlation_id_ctx.get() or "none"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "HTTP Error",
            "detail": exc.detail,
            "correlation_id": corr_id
        },
        headers={"X-Correlation-ID": corr_id}
    )

# -----------------------------------------------------------------------------
# Health and Readiness Endpoints
# -----------------------------------------------------------------------------
@app.get("/health", tags=["Health"])
@app.get("/api/v1/health", tags=["Health"])
async def health_check():
    """Liveness probe for orchestrators and container health monitoring."""
    return {
        "status": "healthy",
        "service": settings.service_name,
        "version": "1.1.0",
        "timestamp": time.time()
    }

@app.get("/health/ready", tags=["Health"])
@app.get("/api/v1/ready", tags=["Health"])
async def readiness_check():
    """Readiness probe checking Redis connectivity, queue depth, and active prompt."""
    queue_depth = await task_queue.get_depth()
    redis_online = task_queue.is_connected()
    return {
        "status": "ready",
        "service": settings.service_name,
        "queue_depth": queue_depth,
        "redis_connected": redis_online,
        "active_prompt": settings.active_prompt_version
    }

@app.get("/metrics", tags=["Observability"])
@app.get("/api/v1/metrics", tags=["Observability"])
async def prometheus_metrics():
    """Prometheus metrics scrape target."""
    return PlainTextResponse(get_metrics_output(), media_type=CONTENT_TYPE_LATEST)

# -----------------------------------------------------------------------------
# Incident Alert Ingestion & Triage Endpoints
# -----------------------------------------------------------------------------
@app.post(
    "/api/v1/incidents",
    response_model=IncidentSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Incidents"],
    summary="Submit production incident alert for triage"
)
async def submit_incident(
    req: Union[IncidentAlertRequest, IncidentSubmissionRequest, Dict[str, Any]],
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
):
    """
    Ingests an infrastructure alert, validates schema and safety,
    checks idempotency, and dispatches for asynchronous multi-agent triage.
    """
    corr_id = correlation_id_ctx.get() or f"corr_{uuid.uuid4().hex[:12]}"
    client_id = request.headers.get("X-Client-ID") or "sre-console"

    # Convert request payload to raw dict
    if isinstance(req, (IncidentAlertRequest, IncidentSubmissionRequest)):
        raw_dict = req.model_dump(exclude_none=True)
    elif isinstance(req, dict):
        raw_dict = req
    else:
        raw_dict = dict(req)

    # 1. Idempotency Check
    idem_key = idempotency_key or request.headers.get("X-Idempotency-Key")
    if idem_key:
        existing_run_id = await run_storage.get_run_by_idempotency_key(idem_key)
        if existing_run_id:
            existing_status = await run_storage.get_status(existing_run_id)
            if existing_status:
                app_logger.info(f"Idempotent hit for key '{idem_key}' -> run '{existing_run_id}'")
                existing_result = await run_storage.get_result(existing_run_id)
                return IncidentSubmissionResponse(
                    run_id=existing_run_id,
                    alert_id=existing_status.alert_id,
                    correlation_id=corr_id,
                    status=existing_status.status,
                    message="Idempotent request. Existing incident run retrieved.",
                    created_at=existing_status.created_at,
                    result=existing_result
                )

    # 2. Validation and Quarantine Check
    is_valid, alert_model, errors, rejection_reason, quar_rec = incident_validator.validate_and_classify(
        raw_payload=raw_dict,
        client_id=client_id,
        correlation_id=corr_id
    )

    if not is_valid:
        # Request is invalid, malformed, or suspicious -> Return 422 with quarantine metadata
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "Incident Alert Rejected",
                "rejection_reason": rejection_reason,
                "validation_errors": errors,
                "quarantined": True,
                "quarantine_id": quar_rec.quarantine_id if quar_rec else None,
                "correlation_id": corr_id,
                "message": (
                    "The alert payload failed strict schema, metric range, or security validation. "
                    "It has been quarantined and isolated from the agent queue."
                )
            },
            headers={"X-Correlation-ID": corr_id}
        )

    # 3. Create run tracking metadata
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    token_run = run_id_ctx.set(run_id)

    p_version = alert_model.prompt_version or settings.active_prompt_version
    status_record = await run_storage.create_run(
        run_id=run_id,
        alert_id=alert_model.alert_id,
        correlation_id=corr_id,
        idempotency_key=idem_key
    )

    # 4. Processing Mode: Synchronous vs Asynchronous
    if alert_model.sync_mode:
        # Synchronous execution
        task_data = {
            "run_id": run_id,
            "alert_id": alert_model.alert_id,
            "database": alert_model.database,
            "database_version": alert_model.database_version,
            "metric": alert_model.metric,
            "observed_value": alert_model.observed_value,
            "threshold": alert_model.threshold,
            "severity": alert_model.severity,
            "on_call_note": alert_model.on_call_note,
            "client_id": alert_model.client_id or client_id,
            "correlation_id": corr_id,
            "prompt_version": p_version,
            "created_at": status_record.created_at
        }
        await run_storage.update_status(run_id, IncidentStatus.PROCESSING.value)

        try:
            result = await agent_service.execute_triage(task_data)
            await run_storage.save_result(run_id, result)
            await run_storage.update_status(run_id, result.status)
            RESULTS_STORE[run_id] = result.model_dump()

            run_id_ctx.reset(token_run)
            return IncidentSubmissionResponse(
                run_id=run_id,
                alert_id=alert_model.alert_id,
                correlation_id=corr_id,
                status=result.status,
                message="Incident triage completed synchronously.",
                created_at=status_record.created_at,
                result=result.model_dump()
            )
        except Exception as exc:
            app_logger.error(f"Sync triage failed for run '{run_id}': {exc}", exc_info=True)
            await run_storage.update_status(run_id, IncidentStatus.FAILED.value, error=str(exc))
            run_id_ctx.reset(token_run)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Triage execution failed: {str(exc)}"
            )

    # Asynchronous queuing
    task = {
        "run_id": run_id,
        "alert_id": alert_model.alert_id,
        "database": alert_model.database,
        "database_version": alert_model.database_version,
        "metric": alert_model.metric,
        "observed_value": alert_model.observed_value,
        "threshold": alert_model.threshold,
        "severity": alert_model.severity,
        "on_call_note": alert_model.on_call_note,
        "metadata": alert_model.metadata,
        "client_id": alert_model.client_id or client_id,
        "correlation_id": corr_id,
        "prompt_version": p_version,
        "created_at": status_record.created_at
    }

    await task_queue.enqueue(task)
    run_id_ctx.reset(token_run)

    return IncidentSubmissionResponse(
        run_id=run_id,
        alert_id=alert_model.alert_id,
        correlation_id=corr_id,
        status=IncidentStatus.QUEUED.value,
        message="Incident triage request validated and queued for asynchronous agent processing.",
        created_at=status_record.created_at,
        result=None
    )

# -----------------------------------------------------------------------------
# Quarantine Review Endpoints (Declared before {run_id} to prevent path shadowing)
# -----------------------------------------------------------------------------
@app.get(
    "/api/v1/incidents/quarantine",
    response_model=QuarantineListResponse,
    tags=["Quarantine"],
    summary="List quarantined alerts for engineer review"
)
async def list_quarantined_alerts(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0)
):
    """Returns quarantined incident alerts that were blocked or failed validation."""
    items = quarantine_store.list_quarantines(limit=limit, offset=offset)
    total = quarantine_store.get_total_count()
    return QuarantineListResponse(
        total_quarantined=total,
        items=items
    )

@app.get(
    "/api/v1/incidents/quarantine/{quarantine_id}",
    response_model=QuarantineRecord,
    tags=["Quarantine"],
    summary="Get specific quarantined alert record"
)
async def get_quarantined_alert(quarantine_id: str):
    """Retrieves full details and redaction summary for a quarantined alert."""
    record = quarantine_store.get_quarantine(quarantine_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Quarantined record '{quarantine_id}' not found."
        )
    return record

@app.get(
    "/api/v1/incidents/{run_id}",
    response_model=IncidentStatusResponse,
    tags=["Incidents"],
    summary="Get incident run processing status"
)
async def get_incident_status(run_id: str):
    """Retrieves lifecycle status metadata for an incident run."""
    status_rec = await run_storage.get_status(run_id)
    if status_rec:
        return status_rec

    # Fallback to RESULTS_STORE if completed earlier
    if run_id in RESULTS_STORE:
        res = RESULTS_STORE[run_id]
        return IncidentStatusResponse(
            run_id=run_id,
            alert_id=res.get("alert_id", "unknown"),
            status=res.get("status", "completed"),
            created_at=res.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            updated_at=res.get("completed_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            completed_at=res.get("completed_at")
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Incident run '{run_id}' not found."
    )

@app.get(
    "/api/v1/incidents/{run_id}/result",
    tags=["Incidents"],
    summary="Get completed multi-agent triage result"
)
async def get_incident_result(run_id: str):
    """
    Retrieves the structured triage result for a completed incident run.
    Returns HTTP 202 if still queued or processing, or HTTP 404 if not found.
    """
    # 1. Check persistent result store
    result = await run_storage.get_result(run_id)
    if result:
        return result

    # 2. Check in-memory global store
    if run_id in RESULTS_STORE:
        return RESULTS_STORE[run_id]

    # 3. Check status if in-flight or failed
    status_rec = await run_storage.get_status(run_id)
    if not status_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident run '{run_id}' not found."
        )

    if status_rec.status in (IncidentStatus.QUEUED.value, IncidentStatus.PROCESSING.value):
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "run_id": run_id,
                "status": status_rec.status,
                "message": f"Incident triage is currently {status_rec.status}. Please poll shortly.",
                "created_at": status_rec.created_at,
                "queue_duration_seconds": status_rec.queue_duration_seconds
            }
        )

    if status_rec.status == IncidentStatus.FAILED.value:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "run_id": run_id,
                "status": "failed",
                "error": status_rec.error or "Incident triage failed during agent execution.",
                "retry_count": status_rec.retry_count
            }
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Result for run '{run_id}' is not yet available."
    )

# -----------------------------------------------------------------------------
# Feedback and Evaluation Endpoints (Preserved from Member 4)
# -----------------------------------------------------------------------------
@app.post("/api/v1/feedback", tags=["Feedback"], summary="Submit engineer feedback")
async def submit_feedback(req: FeedbackSubmissionRequest):
    """Submits human engineer feedback on an incident run."""
    record = feedback_manager.record_feedback(
        run_id=req.run_id,
        satisfactory=req.satisfactory,
        reason=req.reason or "",
        timestamp=req.timestamp
    )
    return {
        "status": "success",
        "message": "Feedback recorded",
        "feedback_id": record.feedback_id
    }

@app.get("/api/v1/feedback/stats", response_model=FeedbackStatsResponse, tags=["Feedback"], summary="Get feedback statistics")
async def get_feedback_statistics():
    """Retrieves aggregate feedback metrics."""
    return feedback_manager.get_stats()

@app.get("/api/v1/prompts", tags=["Prompts"], summary="List prompt versions")
async def list_prompts():
    """Lists available prompt template versions."""
    return {
        "active_version": settings.active_prompt_version,
        "available_versions": prompt_manager.list_versions()
    }
