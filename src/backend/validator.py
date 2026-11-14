"""Validation and Quarantine Layer for Incident Alerts."""
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from pydantic import ValidationError

from src.agentops.logging import app_logger
from src.agentops.guardrails.injection_detector import injection_detector
from src.backend.schemas import (
    IncidentAlertRequest,
    IncidentSubmissionRequest,
    QuarantineRecord,
    QuarantineReason
)
from src.backend.quarantine import quarantine_store

# Destructive command patterns to block outright
MALICIOUS_EXEC_PATTERNS = [
    re.compile(r"\b(sudo\s+rm\s+-rf|drop\s+database|truncate\s+table|format\s+[a-z]:)\b", re.IGNORECASE),
    re.compile(r"\b(shutdown\s+-h|init\s+0|killall\s+-9|reboot)\b", re.IGNORECASE),
    re.compile(r"\b(curl|wget)\s+https?://[^\s]+\s*\|\s*(sh|bash)", re.IGNORECASE),
    re.compile(r"<\s*script\b[^>]*>", re.IGNORECASE),
    re.compile(r"(--\s*drop\s+table|;\s*drop\s+table|exec\s*\()", re.IGNORECASE),
]

class IncidentValidator:
    """Validates incoming incident alerts, performs security scanning, and handles quarantine."""

    def __init__(self, max_payload_bytes: int = 1_048_576):
        self.max_payload_bytes = max_payload_bytes

    def inspect_for_destructive_commands(self, text: str) -> Optional[str]:
        """Checks for dangerous shell or database deletion commands."""
        for pattern in MALICIOUS_EXEC_PATTERNS:
            match = pattern.search(text)
            if match:
                return f"Disallowed destructive command detected: '{match.group(0)}'"
        return None

    def normalize_incoming_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalizes both raw payloads (e.g. from Locust or legacy agents)
        and structured incident alert dictionaries into a standard format.
        """
        data = dict(raw_data)

        # Handle backward-compatible 'alert_payload' string
        if "alert_payload" in data and ("alert_id" not in data or not data.get("alert_id")):
            payload_text = str(data.get("alert_payload", ""))
            notes = str(data.get("on_call_notes", "") or data.get("on_call_note", ""))

            # Synthesize an alert_id
            data["alert_id"] = f"ALT-RAW-{hash(payload_text) & 0xFFFFFFFF:08x}"
            data["database"] = "postgresql"
            data["database_version"] = "16"

            # Infer metric and observed values from raw text if possible
            if "disk" in payload_text.lower():
                data["metric"] = "disk_usage"
                # Search for percentage in text like '88%'
                pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", payload_text)
                if pct_match:
                    data["observed_value"] = float(pct_match.group(1))
                    data["threshold"] = 80.0
                else:
                    data["observed_value"] = 85.0
                    data["threshold"] = 80.0
                data["severity"] = "warning"
            elif "connection" in payload_text.lower():
                data["metric"] = "active_connections"
                data["observed_value"] = 500.0
                data["threshold"] = 450.0
                data["severity"] = "critical"
            elif "lag" in payload_text.lower():
                data["metric"] = "replication_lag_bytes"
                data["observed_value"] = 350000000.0
                data["threshold"] = 100000000.0
                data["severity"] = "warning"
            elif "deadlock" in payload_text.lower():
                data["metric"] = "deadlock_count"
                data["observed_value"] = 16.0
                data["threshold"] = 5.0
                data["severity"] = "critical"
            else:
                data["metric"] = "database_alert"
                data["observed_value"] = 1.0
                data["threshold"] = 1.0
                data["severity"] = "warning"

            if not data.get("on_call_note"):
                data["on_call_note"] = notes or payload_text

        # Reconcile on_call_notes vs on_call_note
        if "on_call_notes" in data and not data.get("on_call_note"):
            data["on_call_note"] = data.pop("on_call_notes")

        return data

    def validate_and_classify(
        self,
        raw_payload: Dict[str, Any],
        client_id: str = "unknown",
        correlation_id: str = "unknown"
    ) -> Tuple[bool, Optional[IncidentAlertRequest], List[str], Optional[str], Optional[QuarantineRecord]]:
        """
        Validates, sanitizes, security checks, and classifies an incoming alert.
        Returns:
            (is_valid, alert_model, error_messages, rejection_reason, quarantine_record)
        """
        # 1. Payload size check
        try:
            payload_str = json.dumps(raw_payload)
            if len(payload_str.encode("utf-8")) > self.max_payload_bytes:
                rejection = QuarantineReason.SUSPICIOUS_PAYLOAD.value
                errors = [f"Payload size ({len(payload_str)} bytes) exceeds max limit of {self.max_payload_bytes} bytes"]
                rec = quarantine_store.add_quarantine(raw_payload, errors, rejection, client_id, correlation_id)
                return False, None, errors, rejection, rec
        except Exception as e:
            rejection = QuarantineReason.SUSPICIOUS_PAYLOAD.value
            errors = [f"Payload serialization error: {str(e)}"]
            rec = quarantine_store.add_quarantine(raw_payload, errors, rejection, client_id, correlation_id)
            return False, None, errors, rejection, rec

        # 2. Security Check: Prompt injection / system override
        text_content = f"{raw_payload.get('alert_payload', '')} {raw_payload.get('on_call_note', '')} {raw_payload.get('on_call_notes', '')} {raw_payload.get('alert_id', '')} {raw_payload.get('metric', '')}"
        
        # Check destructive commands first
        cmd_err = self.inspect_for_destructive_commands(text_content)
        if cmd_err:
            rejection = QuarantineReason.SUSPICIOUS_PAYLOAD.value
            errors = [cmd_err]
            rec = quarantine_store.add_quarantine(raw_payload, errors, rejection, client_id, correlation_id)
            return False, None, errors, rejection, rec

        injection_verdict = injection_detector.evaluate(text_content)
        if not injection_verdict.is_safe:
            rejection = (
                QuarantineReason.SUSPICIOUS_PAYLOAD.value
                if "command" in injection_verdict.category.lower()
                else QuarantineReason.PROMPT_INJECTION.value
            )
            errors = [f"Prompt injection guardrail triggered: {injection_verdict.category} (risk score: {injection_verdict.risk_score:.2f})"]
            rec = quarantine_store.add_quarantine(raw_payload, errors, rejection, client_id, correlation_id)
            return False, None, errors, rejection, rec

        # 4. Normalize and validate with Pydantic
        normalized = self.normalize_incoming_data(raw_payload)

        try:
            alert = IncidentAlertRequest(**normalized)
            return True, alert, [], None, None

        except ValidationError as val_err:
            errors = []
            has_missing = any(e.get("type") == "missing" for e in val_err.errors())
            rejection = QuarantineReason.INVALID_FIELDS.value

            for err in val_err.errors():
                loc = " -> ".join(str(l) for l in err["loc"])
                msg = err["msg"]
                errors.append(f"Field '{loc}': {msg}")

                if not has_missing:
                    # Specialize rejection category when not missing required fields
                    if "database" in loc or "Unsupported database" in msg:
                        rejection = QuarantineReason.UNSUPPORTED_DATABASE.value
                    elif "severity" in loc or "Invalid severity" in msg:
                        rejection = QuarantineReason.INVALID_SEVERITY.value
                    elif "observed_value" in loc or "threshold" in loc or "percentage" in msg.lower() or "range" in msg.lower():
                        rejection = QuarantineReason.METRIC_OUT_OF_RANGE.value
                    elif "timestamp" in loc:
                        rejection = QuarantineReason.INVALID_TIMESTAMP.value

            rec = quarantine_store.add_quarantine(raw_payload, errors, rejection, client_id, correlation_id)
            return False, None, errors, rejection, rec

        except Exception as exc:
            rejection = QuarantineReason.INVALID_FIELDS.value
            errors = [f"Unexpected validation error: {str(exc)}"]
            rec = quarantine_store.add_quarantine(raw_payload, errors, rejection, client_id, correlation_id)
            return False, None, errors, rejection, rec

incident_validator = IncidentValidator()
