"""Pydantic Request and Response Schemas."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class IncidentSubmissionRequest(BaseModel):
    alert_payload: str = Field(..., description="Raw infrastructure alert text or JSON payload")
    on_call_notes: str = Field(default="", description="Observations and context from the on-call engineer")
    client_id: str = Field(default="sre-console", description="Identifier of calling system or engineer")
    correlation_id: Optional[str] = Field(default=None, description="Distributed correlation ID")
    prompt_version: Optional[str] = Field(default=None, description="Optional override for prompt version")
    sync_mode: bool = Field(default=True, description="Execute synchronously or queue in background")

class IncidentSubmissionResponse(BaseModel):
    run_id: str
    correlation_id: str
    status: str
    message: str
    result: Optional[Dict[str, Any]] = None

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
