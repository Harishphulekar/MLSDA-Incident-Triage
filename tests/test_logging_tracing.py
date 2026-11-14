"""Tests for Structured JSON Logging, Sanitization, Correlation IDs, and Tracing."""
import json
import logging
from src.agentops.logging import (
    JSONFormatter,
    sanitize_value,
    correlation_id_ctx,
    run_id_ctx,
    setup_logger
)
from src.agentops.tracing import init_tracer, trace_span, get_tracer

def test_json_formatter_and_correlation_ids():
    formatter = JSONFormatter(service_name="test-service")
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Processing incident alert",
        args=(),
        exc_info=None
    )
    
    correlation_id_ctx.set("corr_test_12345")
    run_id_ctx.set("run_test_67890")

    formatted = formatter.format(record)
    data = json.loads(formatted)

    assert data["service"] == "test-service"
    assert data["level"] == "INFO"
    assert data["message"] == "Processing incident alert"
    assert data["correlation_id"] == "corr_test_12345"
    assert data["run_id"] == "run_test_67890"
    assert "timestamp" in data

def test_sensitive_data_sanitization():
    raw_dict = {
        "user": "admin",
        "api_key": "sk-1234567890abcdef",
        "secret_token": "bearer xyz987",
        "database": {
            "password": "supersecretpassword123",
            "host": "localhost"
        }
    }
    sanitized = sanitize_value(raw_dict)
    assert sanitized["user"] == "admin"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["secret_token"] == "[REDACTED]"
    assert sanitized["database"]["password"] == "[REDACTED]"
    assert sanitized["database"]["host"] == "localhost"

def test_trace_span_generation():
    init_tracer(service_name="test-tracer", endpoint=None, enable_tracing=False)
    correlation_id_ctx.set("corr_span_test")
    run_id_ctx.set("run_span_test")

    with trace_span("test_operation", {"custom_attr": "value123"}) as span:
        assert span is not None
        # Span execution completes without error
    
    tracer = get_tracer()
    assert tracer is not None
