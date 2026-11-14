"""Pydantic Request and Response Schemas for Incident Triage Assistant."""
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------
class DatabaseType(str, Enum):
    POSTGRESQL = "postgresql"
    POSTGRES = "postgres"

class SeverityLevel(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"
    SEV4 = "sev4"
    BLOCKER = "blocker"

class IncidentStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    BLOCKED = "blocked"

class QuarantineReason(str, Enum):
    INVALID_FIELDS = "invalid_fields"
    UNSUPPORTED_DATABASE = "unsupported_database"
    INVALID_SEVERITY = "invalid_severity"
    METRIC_OUT_OF_RANGE = "metric_out_of_range"
    INVALID_TIMESTAMP = "invalid_timestamp"
    PROMPT_INJECTION = "prompt_injection"
    SUSPICIOUS_PAYLOAD = "suspicious_payload"
    THRESHOLD_INCONSISTENT = "threshold_inconsistent"

# -----------------------------------------------------------------------------
# Request Schemas
# -----------------------------------------------------------------------------
class IncidentAlertRequest(BaseModel):
    """
    Standard production incident alert payload.
    Supports both formal alert format and raw payloads.
    """
    alert_id: str = Field(
        ...,
        description="Unique alert identifier (e.g., 'ALT-001', 'ALERT_PG_DISK_88')",
        min_length=2,
        max_length=128
    )
    database: str = Field(
        default="postgresql",
        description="Target database engine (currently supports postgresql/postgres)"
    )
    database_version: Optional[str] = Field(
        default="16",
        description="Database engine version (e.g. '14', '15', '16')"
    )
    metric: str = Field(
        ...,
        description="Telemetry metric name (e.g., 'disk_usage', 'replication_lag_bytes', 'active_connections')",
        min_length=2,
        max_length=128
    )
    observed_value: float = Field(
        ...,
        description="Current observed value of the metric"
    )
    threshold: float = Field(
        ...,
        description="Threshold value that triggered the alert"
    )
    severity: str = Field(
        ...,
        description="Alert severity level (critical, warning, info, sev1, sev2, sev3, sev4)"
    )
    on_call_note: Optional[str] = Field(
        default="",
        description="Observations and context provided by the on-call engineer",
        max_length=4096
    )
    timestamp: Optional[Union[str, float, int]] = Field(
        default=None,
        description="Incident occurrence timestamp (ISO 8601 string or Unix epoch)"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional auxiliary alert metadata or environment tags"
    )
    client_id: Optional[str] = Field(
        default="sre-console",
        description="Identifier of calling system, service or engineer",
        max_length=128
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Distributed correlation ID for end-to-end tracing"
    )
    prompt_version: Optional[str] = Field(
        default=None,
        description="Optional override for triage prompt version (e.g. 'v1.0.0', 'v1.1.0')"
    )
    sync_mode: bool = Field(
        default=False,
        description="Execute synchronously (True) or enqueue for background worker (False)"
    )

    @field_validator("database")
    @classmethod
    def validate_database(cls, v: str) -> str:
        clean_v = v.strip().lower()
        allowed = {d.value for d in DatabaseType}
        if clean_v not in allowed:
            raise ValueError(f"Unsupported database '{v}'. Allowed: {', '.join(allowed)}")
        return clean_v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        clean_v = v.strip().lower()
        allowed = {s.value for s in SeverityLevel}
        if clean_v not in allowed:
            raise ValueError(f"Invalid severity '{v}'. Allowed: {', '.join(allowed)}")
        return clean_v

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, v: str) -> str:
        clean_v = v.strip().lower()
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", clean_v):
            raise ValueError(f"Metric name '{v}' contains invalid characters. Use alphanumeric, _, -, or .")
        return clean_v

    @field_validator("threshold")
    @classmethod
    def validate_threshold(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"Threshold must be non-negative, got {v}")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: Optional[Union[str, float, int]]) -> Optional[str]:
        if v is None:
            return datetime.now(timezone.utc).isoformat()
        if isinstance(v, (int, float)):
            if v < 0 or v > 253402300799:
                raise ValueError(f"Invalid Unix timestamp {v}")
            return datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
        if isinstance(v, str):
            clean_ts = v.strip()
            # Try parsing ISO 8601
            try:
                # Replace trailing 'Z' for fromisoformat compatibility
                parsed = datetime.fromisoformat(clean_ts.replace("Z", "+00:00"))
                return parsed.isoformat()
            except Exception:
                raise ValueError(f"Invalid ISO 8601 timestamp string: '{v}'")
        return datetime.now(timezone.utc).isoformat()

    @model_validator(mode="after")
    def validate_metric_ranges_and_consistency(self) -> "IncidentAlertRequest":
        # 1. Percentage metric range validation
        percentage_keywords = ("percent", "pct", "usage", "ratio", "saturation")
        if any(kw in self.metric for kw in percentage_keywords):
            if "byte" not in self.metric and "lag" not in self.metric and "count" not in self.metric:
                if self.observed_value < 0 or self.observed_value > 100:
                    raise ValueError(
                        f"Metric '{self.metric}' appears to be a percentage but observed_value is {self.observed_value}. "
                        "Expected range: 0.0 to 100.0"
                    )
                if self.threshold < 0 or self.threshold > 100:
                    raise ValueError(
                        f"Threshold for percentage metric '{self.metric}' is {self.threshold}. Expected range: 0.0 to 100.0"
                    )

        # 2. Cross-field consistency: Non-negative observed values for count/byte metrics
        if any(kw in self.metric for kw in ("bytes", "count", "lag", "connections", "deadlocks")):
            if self.observed_value < 0:
                raise ValueError(f"Observed value for metric '{self.metric}' cannot be negative: {self.observed_value}")

        return self

class IncidentSubmissionRequest(BaseModel):
    """
    Flexible ingestion request schema supporting both structured fields and raw alert payloads.
    Provides backward compatibility with existing Locust scripts and test payloads.
    """
    alert_payload: Optional[str] = Field(
        default=None,
        description="Raw infrastructure alert text or JSON string payload"
    )
    on_call_notes: Optional[str] = Field(
        default="",
        description="Observations and context from the on-call engineer"
    )
    client_id: Optional[str] = Field(
        default="sre-console",
        description="Identifier of calling system or engineer"
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Distributed correlation ID"
    )
    prompt_version: Optional[str] = Field(
        default=None,
        description="Optional override for prompt version"
    )
    sync_mode: bool = Field(
        default=False,
        description="Execute synchronously (True) or enqueue in background (False)"
    )

    # Optional structured fields
    alert_id: Optional[str] = None
    database: Optional[str] = None
    database_version: Optional[str] = None
    metric: Optional[str] = None
    observed_value: Optional[float] = None
    threshold: Optional[float] = None
    severity: Optional[str] = None
    on_call_note: Optional[str] = None
    timestamp: Optional[Union[str, float, int]] = None
    metadata: Optional[Dict[str, Any]] = None

# -----------------------------------------------------------------------------
# Response Schemas
# -----------------------------------------------------------------------------
class IncidentSubmissionResponse(BaseModel):
    """Immediate response returned after incident submission and queuing."""
    run_id: str = Field(..., description="Unique lifecycle execution run ID")
    alert_id: str = Field(..., description="Alert identifier")
    correlation_id: str = Field(..., description="Distributed tracing correlation ID")
    status: str = Field(..., description="Current processing status (e.g. 'queued', 'completed')")
    message: str = Field(..., description="Human-readable status summary")
    created_at: str = Field(..., description="UTC ISO timestamp of submission")
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Synchronous triage result if sync_mode was requested"
    )

class IncidentStatusResponse(BaseModel):
    """Status metadata for an in-flight or completed incident run."""
    run_id: str
    alert_id: str
    status: str
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    queue_duration_seconds: Optional[float] = None
    execution_duration_seconds: Optional[float] = None
    retry_count: int = 0
    error: Optional[str] = None

class CitationDetail(BaseModel):
    source: str = Field(..., description="Source runbook or official doc file")
    section: Optional[str] = Field(default="", description="Relevant document section or chapter")
    quoted_passage: Optional[str] = Field(default="", description="Quoted technical passage")

class IncidentResultResponse(BaseModel):
    """Complete structured triage and verification result produced by agents."""
    run_id: str
    alert_id: str
    status: str = Field(default="completed", description="Final run status (completed, escalated, blocked)")
    symptom_class: str = Field(..., description="Classified root symptom category")
    probable_root_cause: str = Field(..., description="Formulated technical diagnosis")
    severity: str = Field(..., description="Assessed incident severity")
    evidence: List[str] = Field(default_factory=list, description="Verified factual findings")
    documentation_citations: List[Dict[str, Any]] = Field(default_factory=list, description="Authoritative documentation citations")
    recommended_actions: List[str] = Field(default_factory=list, description="Advisory remediation recommendations for human engineers")
    escalation_required: bool = Field(default=False, description="Whether incident requires human expert escalation")
    escalation_reason: Optional[str] = Field(default=None, description="Reason human escalation is mandated")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Verification confidence score (0.0 - 1.0)")
    routing_decision: Optional[str] = Field(default=None, description="Recommended engineering team or on-call routing")
    created_at: str
    completed_at: str
    cost: Optional[Dict[str, Any]] = Field(default=None, description="LLM token and cost tracking summary")

# -----------------------------------------------------------------------------
# Quarantine Schemas
# -----------------------------------------------------------------------------
class QuarantineRecord(BaseModel):
    """Quarantined incident alert rejected due to validation failure or suspicious input."""
    quarantine_id: str
    received_at: str
    client_id: str
    correlation_id: str
    rejection_reason: str
    validation_errors: List[str]
    original_alert: Dict[str, Any]

class QuarantineListResponse(BaseModel):
    """List of all currently quarantined requests for SRE review."""
    total_quarantined: int
    items: List[QuarantineRecord]

# -----------------------------------------------------------------------------
# Feedback Schemas (Preserved from Member 4)
# -----------------------------------------------------------------------------
class FeedbackSubmissionRequest(BaseModel):
    run_id: str = Field(..., description="Unique incident run identifier")
    satisfactory: bool = Field(..., description="Whether the triage and recommendation were satisfactory")
    reason: Optional[str] = Field(default="", description="Feedback rationale from engineer")
    timestamp: Optional[float] = Field(default=None, description="Epoch timestamp of feedback submission")

class FeedbackStatsResponse(BaseModel):
    total_feedback: int
    positive_count: int
    negative_count: int
    satisfaction_rate: float
    recent_reasons: List[str]
