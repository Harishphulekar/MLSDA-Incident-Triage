"""OpenTelemetry Distributed Tracing with Jaeger and Context Propagation."""
import logging
from contextlib import contextmanager
from typing import Dict, Generator, Optional
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.trace import Status, StatusCode, Span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from src.agentops.logging import correlation_id_ctx, run_id_ctx

_tracer_initialized = False

def init_tracer(service_name: str = "incident-triage-assistant", endpoint: Optional[str] = None, enable_tracing: bool = True) -> trace.Tracer:
    """Initializes the OpenTelemetry TracerProvider with Jaeger OTLP or local processor."""
    global _tracer_initialized
    if _tracer_initialized:
        return trace.get_tracer(service_name)

    resource = Resource.create({
        SERVICE_NAME: service_name,
        "environment": "production",
        "team": "Team 04"
    })

    provider = TracerProvider(resource=resource)

    if enable_tracing and endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            otlp_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        except Exception:
            # Fallback to in-memory console exporter for test/offline resilience
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer_initialized = True
    return trace.get_tracer(service_name)

def get_tracer() -> trace.Tracer:
    """Returns the configured OpenTelemetry tracer."""
    return trace.get_tracer("incident-triage-assistant")

@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, str]] = None) -> Generator[Span, None, None]:
    """Context manager to create a trace span enriched with correlation and run IDs."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        # Attach correlation ID and run ID
        corr_id = correlation_id_ctx.get()
        r_id = run_id_ctx.get()
        if corr_id:
            span.set_attribute("incident.correlation_id", corr_id)
        if r_id:
            span.set_attribute("incident.run_id", r_id)

        if attributes:
            for k, v in attributes.items():
                if v is not None:
                    span.set_attribute(k, str(v))

        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, description=str(exc)))
            raise

def inject_trace_context(carrier: dict) -> dict:
    """Injects current W3C trace context into carrier dict for cross-service propagation."""
    TraceContextTextMapPropagator().inject(carrier)
    return carrier

def extract_trace_context(carrier: dict):
    """Extracts W3C trace context from carrier dict."""
    return TraceContextTextMapPropagator().extract(carrier)
