"""Human Feedback Persistence and Quality Monitoring."""
import json
import os
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from prometheus_client import Counter, Gauge
from src.agentops.logging import app_logger

# Feedback Prometheus Metrics
FEEDBACK_SUBMISSIONS_TOTAL = Counter(
    "feedback_submissions_total",
    "Total feedback submissions from engineers",
    ["satisfactory"]
)

FEEDBACK_SATISFACTION_RATE = Gauge(
    "feedback_satisfaction_rate",
    "Rolling ratio of satisfactory triage feedback"
)

class FeedbackRecord(BaseModel):
    feedback_id: str
    run_id: str
    satisfactory: bool
    reason: str
    timestamp: float

class FeedbackManager:
    """Manages engineer feedback persistence, statistics, and quality evaluation."""
    def __init__(self, storage_path: str = "./data/feedback.json"):
        self.storage_path = storage_path
        self._records: List[FeedbackRecord] = []
        self._load_from_disk()

    def _load_from_disk(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._records = [FeedbackRecord(**r) for r in data]
                self._update_metrics()
            except Exception as e:
                app_logger.warning(f"Could not load feedback storage: {e}")

    def _save_to_disk(self):
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump([r.model_dump() for r in self._records], f, indent=2)
        except Exception as e:
            app_logger.error(f"Failed to persist feedback to disk: {e}")

    def _update_metrics(self):
        if not self._records:
            return
        pos = sum(1 for r in self._records if r.satisfactory)
        rate = pos / len(self._records)
        FEEDBACK_SATISFACTION_RATE.set(rate)

    def record_feedback(self, run_id: str, satisfactory: bool, reason: str = "", timestamp: Optional[float] = None) -> FeedbackRecord:
        record = FeedbackRecord(
            feedback_id=f"fb_{int(time.time() * 1000)}_{len(self._records)}",
            run_id=run_id,
            satisfactory=satisfactory,
            reason=reason,
            timestamp=timestamp or time.time()
        )
        self._records.append(record)
        self._save_to_disk()

        # Update Prometheus metrics
        FEEDBACK_SUBMISSIONS_TOTAL.labels(satisfactory=str(satisfactory).lower()).inc()
        self._update_metrics()

        app_logger.info(
            f"Feedback recorded for run '{run_id}': satisfactory={satisfactory}",
            extra={"run_id": run_id, "satisfactory": satisfactory, "reason": reason}
        )
        return record

    def get_stats(self) -> Dict[str, Any]:
        total = len(self._records)
        if total == 0:
            return {
                "total_feedback": 0,
                "positive_count": 0,
                "negative_count": 0,
                "satisfaction_rate": 1.0,
                "recent_reasons": []
            }
        
        pos = sum(1 for r in self._records if r.satisfactory)
        neg = total - pos
        rate = round(pos / total, 3)
        recent = [r.reason for r in self._records[-5:] if r.reason]

        return {
            "total_feedback": total,
            "positive_count": pos,
            "negative_count": neg,
            "satisfaction_rate": rate,
            "recent_reasons": recent
        }

    def evaluate_sample_runs(self, completed_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Runs automated quality checks on a sample of completed runs."""
        sample_size = min(len(completed_runs), 5)
        if sample_size == 0:
            return {"sample_size": 0, "pass_rate": 1.0}

        sample = completed_runs[:sample_size]
        passed = 0
        for run in sample:
            has_cause = bool(run.get("cause_class"))
            has_confidence = run.get("confidence", 0) > 0.0
            has_actions = len(run.get("recommended_actions", [])) > 0
            if has_cause and has_confidence and has_actions:
                passed += 1

        return {
            "sample_size": sample_size,
            "passed_checks": passed,
            "pass_rate": round(passed / sample_size, 3)
        }

feedback_manager = FeedbackManager()
