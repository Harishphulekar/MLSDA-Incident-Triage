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
