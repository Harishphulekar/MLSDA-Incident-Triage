"""Tests for Feedback Persistence and Sample Automated Evaluation."""
from src.agentops.feedback import FeedbackManager

def test_feedback_persistence_and_stats(tmp_path):
    storage = str(tmp_path / "feedback_test.json")
    manager = FeedbackManager(storage_path=storage)

    manager.record_feedback("run_001", satisfactory=True, reason="Accurate WAL diagnosis")
    manager.record_feedback("run_002", satisfactory=True, reason="Good citation")
    manager.record_feedback("run_003", satisfactory=False, reason="Too slow")

    stats = manager.get_stats()
    assert stats["total_feedback"] == 3
    assert stats["positive_count"] == 2
    assert stats["negative_count"] == 1
    assert stats["satisfaction_rate"] == round(2 / 3, 3)

def test_automated_sample_evaluation():
    manager = FeedbackManager()
    sample_runs = [
        {"cause_class": "WAL Leak", "confidence": 0.9, "recommended_actions": ["inspect slots"]},
        {"cause_class": "Deadlock", "confidence": 0.85, "recommended_actions": ["reorder locks"]},
    ]
    eval_res = manager.evaluate_sample_runs(sample_runs)
    assert eval_res["sample_size"] == 2
    assert eval_res["pass_rate"] == 1.0
