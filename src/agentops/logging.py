"""Structured JSON Logging with Correlation IDs and Sanitization."""
import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Context variables for distributed request and run tracking
correlation_id_ctx: ContextVar[str] = ContextVar("correlation_id", default="")
run_id_ctx: ContextVar[str] = ContextVar("run_id", default="")

# Sensitive patterns to sanitize
SENSITIVE_KEYS = {"password", "secret", "token", "api_key", "authorization", "bearer", "access_key", "credential"}
SENSITIVE_REGEX = re.compile(r"(api[_-]?key|bearer\s+[a-zA-Z0-9_\-\.]+|password\s*[:=]\s*[^\s]+)", re.IGNORECASE)

def sanitize_value(val: Any) -> Any:
    """Recursively sanitize dictionary or string values to prevent leaking secrets."""
    if isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            if any(s in k.lower() for s in SENSITIVE_KEYS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = sanitize_value(v)
        return sanitized
    elif isinstance(val, list):
        return [sanitize_value(item) for item in val]
    elif isinstance(val, str):
        if SENSITIVE_REGEX.search(val):
            return SENSITIVE_REGEX.sub("[REDACTED]", val)
        return val
    return val

class JSONFormatter(logging.Formatter):
    """Formats log records as structured single-line JSON."""
    def __init__(self, service_name: str = "incident-triage-api"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": sanitize_value(record.getMessage()),
            "correlation_id": correlation_id_ctx.get() or getattr(record, "correlation_id", None) or "none",
            "run_id": run_id_ctx.get() or getattr(record, "run_id", None) or "none",
        }

        # Include custom extra attributes
        for key, value in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "message", "correlation_id", "run_id"
            }:
                log_entry[key] = sanitize_value(value)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)

def setup_logger(service_name: str = "incident-triage-api", level: str = "INFO") -> logging.Logger:
    """Configures and returns the root application logger with JSON formatting."""
    logger = logging.getLogger("incident_triage")
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(numeric_level)

    # Avoid duplicate handlers on re-initialization
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter(service_name=service_name))
        logger.addHandler(handler)
        logger.propagate = False

    return logger

app_logger = setup_logger()

# Helper logging functions for agent lifecycle
def log_agent_event(agent_name: str, step: str, event_type: str, details: Optional[Dict[str, Any]] = None):
    app_logger.info(
        f"Agent Event: {agent_name} [{step}] - {event_type}",
        extra={
            "event_category": "agent_execution",
            "agent": agent_name,
            "step": step,
            "event_type": event_type,
            "details": details or {}
        }
    )

def log_retrieval_event(query: str, hits_count: int, sources: list):
    app_logger.info(
        f"Retrieval Event: '{query}' -> {hits_count} documents",
        extra={
            "event_category": "retrieval",
            "query": query,
            "hits_count": hits_count,
            "sources": sources
        }
    )

def log_verification_event(hypothesis: str, verified: bool, confidence: float, evidence_count: int):
    app_logger.info(
        f"Verification Event: verified={verified}, confidence={confidence:.2f}",
        extra={
            "event_category": "verification",
            "hypothesis": hypothesis,
            "verified": verified,
            "confidence": confidence,
            "evidence_count": evidence_count
        }
    )

def log_retry_event(agent_name: str, attempt: int, max_attempts: int, reason: str):
    app_logger.warning(
        f"Retry Event: {agent_name} attempt {attempt}/{max_attempts} - {reason}",
        extra={
            "event_category": "retry",
            "agent": agent_name,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "reason": reason
        }
    )

def log_escalation_event(reason: str, severity: str, routing_target: str):
    app_logger.warning(
        f"Escalation Event: routing to {routing_target} (Severity: {severity}) - {reason}",
        extra={
            "event_category": "escalation",
            "severity": severity,
            "routing_target": routing_target,
            "reason": reason
        }
    )
