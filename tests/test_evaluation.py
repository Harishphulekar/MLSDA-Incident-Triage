"""Tests for Evaluation Metrics: Groundedness, Relevance, Faithfulness, Hallucination."""
from src.agentops.evaluation.metrics import (
    compute_context_relevance,
    compute_groundedness,
    compute_faithfulness
)

def test_evaluation_metric_computations():
    alert = "Disk space high on primary postgres"
    note = "investigating wal replication"
    docs = [
        "PostgreSQL replication slots retain WAL files on primary",
        "Runbook for disk saturation triage"
    ]
    
    # Context Relevance
    rel = compute_context_relevance(alert, note, docs)
    assert 0.0 <= rel <= 1.0
    assert rel > 0.3

    # Groundedness with cited passage in corpus
    citations = [{
        "source": "postgresql_wal_replication.md",
        "section": "Replication Slots",
        "quoted_passage": "PostgreSQL replication slots retain WAL files on primary"
    }]
    grounded = compute_groundedness(
        hypothesis="Replication slot retains WAL on primary",
        actions=["Check replication slots"],
        citations=citations,
        retrieved_docs=docs
    )
    assert 0.0 <= grounded <= 1.0
    assert grounded >= 0.8  # Well grounded in context

    # Faithfulness
    scenario = {
        "expected_cause_class": "PostgreSQL Replication Slot WAL Retention"
    }
    result = {
        "cause_class": "PostgreSQL Replication Slot WAL Retention",
        "confidence": 0.95,
        "evidence_sufficient": True
    }
    faith = compute_faithfulness(result, scenario)
    assert 0.0 <= faith <= 1.0
    assert faith >= 0.8

def test_human_escalation_precision_and_recall_bounds():
    from src.agentops.evaluation.metrics import EvaluationSummary

    summary = EvaluationSummary(
        prompt_version="v1.1.0",
        scenarios_evaluated=20,
        mean_groundedness=0.85,
        mean_context_relevance=0.80,
        mean_faithfulness=0.90,
        mean_hallucination_rate=0.15,
        routing_accuracy=0.85,
        human_escalation_precision=0.60,
        human_escalation_recall=1.00,
        total_cost_dollars=0.001
    )
    assert 0.0 <= summary.human_escalation_precision <= 1.0
    assert 0.0 <= summary.human_escalation_recall <= 1.0
    assert 0.0 <= summary.human_escalation_f1 <= 1.0
    assert summary.human_escalation_precision == 0.60
    assert summary.human_escalation_recall == 1.00
