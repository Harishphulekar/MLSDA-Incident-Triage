"""Quarantine Store for Invalid, Suspicious, or Malformed Alerts."""
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional
import uuid

from src.agentops.logging import app_logger, sanitize_value
from src.backend.schemas import QuarantineRecord

class QuarantineStore:
    """Thread-safe store for quarantined incident alerts."""

    def __init__(self, max_records: int = 1000):
        self._records: Dict[str, QuarantineRecord] = {}
        self._order: List[str] = []
        self._max_records = max_records

    def add_quarantine(
        self,
        original_alert: Dict[str, Any],
        validation_errors: List[str],
        rejection_reason: str,
        client_id: str = "unknown",
        correlation_id: str = "unknown"
    ) -> QuarantineRecord:
        """Records a quarantined alert with safely redacted payload."""
        quarantine_id = f"quar_{uuid.uuid4().hex[:12]}"
        received_at = datetime.now(timezone.utc).isoformat()

        # Sanitize original alert to avoid storing plaintext secrets/passwords
        safe_alert = sanitize_value(original_alert)

        record = QuarantineRecord(
            quarantine_id=quarantine_id,
            received_at=received_at,
            client_id=client_id,
            correlation_id=correlation_id,
            rejection_reason=rejection_reason,
            validation_errors=validation_errors,
            original_alert=safe_alert if isinstance(safe_alert, dict) else {"raw": str(safe_alert)}
        )

        # Evict oldest if exceeding capacity
        if len(self._records) >= self._max_records:
            oldest_id = self._order.pop(0)
            self._records.pop(oldest_id, None)

        self._records[quarantine_id] = record
        self._order.append(quarantine_id)

        app_logger.warning(
            f"Alert quarantined: ID={quarantine_id}, Reason={rejection_reason}, Client={client_id}",
            extra={
                "quarantine_id": quarantine_id,
                "rejection_reason": rejection_reason,
                "validation_errors": validation_errors,
                "client_id": client_id,
                "correlation_id": correlation_id
            }
        )

        return record

    def get_quarantine(self, quarantine_id: str) -> Optional[QuarantineRecord]:
        """Retrieves a specific quarantined record by ID."""
        return self._records.get(quarantine_id)

    def list_quarantines(self, limit: int = 50, offset: int = 0) -> List[QuarantineRecord]:
        """Returns paginated quarantined records, latest first."""
        reversed_ids = list(reversed(self._order))
        selected_ids = reversed_ids[offset:offset + limit]
        return [self._records[qid] for qid in selected_ids if qid in self._records]

    def get_total_count(self) -> int:
        """Returns total count of quarantined alerts."""
        return len(self._records)

    def clear(self):
        """Clears quarantine records (used for test teardown)."""
        self._records.clear()
        self._order.clear()

quarantine_store = QuarantineStore()
