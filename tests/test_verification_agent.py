"""Unit and Boundary Tests for Verification Agent, Confidence Scoring, and Routing."""
import pytest
from src.agents.verification_agent import VerificationAgent
from src.rag.retriever import Document

@pytest.fixture
def agent():
    return VerificationAgent(min_similarity_threshold=0.30)

def test_verification_confidence_strong_evidence(agent):
    """Test confidence scoring when strong retrieval similarity and corpus groundedness exist."""
    docs = [
        Document(
            id="doc1",
            source="runbook_disk_saturation_wal_retention.md",
            title="WAL Retention Runbook",
            content="A physical replication slot retains WAL files in pg_wal when the standby is disconnected.",
            metadata={"section": "Replication Slots"},
            score=0.88
        )
    ]
    res = agent.verify_sync(
        hypothesis="WAL retention caused by stalled replication slot.",
        retrieved_docs=docs,
        alert_payload="Host postgres-primary-01 disk usage at 87% and climbing steadily. Table and index sizes are not growing.",
        on_call_notes="disk filling, replication slot lagging.",
        run_id="test_strong_evidence"
    )
    assert res["verified"] is True
    assert res["evidence_sufficient"] is True
    assert res["confidence"] >= 0.85
    assert res["routing_decision"] == "escalate_dba"
    assert len(res["evidence_citations"]) > 0

def test_verification_confidence_weak_evidence(agent):
    """Test that confidence drops below 0.40 and verified is False when evidence is weak."""
    docs = [
        Document(
            id="doc_weak",
            source="unrelated_doc.md",
            title="Unrelated Telemetry",
            content="General system logging configuration and log rotation intervals.",
            metadata={"section": "Logging"},
            score=0.18
        )
    ]
    res = agent.verify_sync(
        hypothesis="Unknown disk growth anomaly.",
        retrieved_docs=docs,
        alert_payload="Generic warning on disk partition without clear indicators.",
        on_call_notes="Telemetry inconclusive.",
        run_id="test_weak_evidence"
    )
    assert res["verified"] is False
    assert res["evidence_sufficient"] is False
    assert res["confidence"] <= 0.40
    assert res["routing_decision"] == "escalate_human_expert"
    assert "threshold" in res["escalation_reason"].lower() or "insufficient" in res["escalation_reason"].lower()

def test_verification_confidence_missing_evidence(agent):
    """Test safe handling when retrieved documents list is empty or scores are zero."""
    # 1. Empty document list
    res_empty = agent.verify_sync(
        hypothesis="Hypothesis without documents.",
        retrieved_docs=[],
        alert_payload="Disk warning alert.",
        on_call_notes="No notes.",
        run_id="test_missing_evidence_empty"
    )
    assert res_empty["verified"] is False
    assert res_empty["evidence_sufficient"] is False
    assert res_empty["confidence"] <= 0.30
    assert res_empty["routing_decision"] == "escalate_human_expert"

    # 2. Document with 0.0 similarity score
    doc_zero_score = [
        Document(
            id="doc_zero",
            source="doc.md",
            title="Doc",
            content="Some text without match",
            metadata={},
            score=0.0
        )
    ]
    res_zero = agent.verify_sync(
        hypothesis="Hypothesis with zero score document.",
        retrieved_docs=doc_zero_score,
        alert_payload="Disk warning alert.",
        on_call_notes="No notes.",
        run_id="test_missing_evidence_zero_score"
    )
    assert isinstance(res_zero["confidence"], float)
    assert 0.10 <= res_zero["confidence"] <= 0.40
    assert res_zero["verified"] is False

def test_verification_confidence_ambiguous_evidence(agent):
    """Test that ambiguous telemetry signals force safe human escalation."""
    docs = [
        Document(
            id="doc_telemetry",
            source="telemetry.md",
            title="Telemetry",
            content="PostgreSQL background writer and buffer allocation statistics.",
            metadata={},
            score=0.60
        )
    ]
    res = agent.verify_sync(
        hypothesis="Indeterminate metric anomaly.",
        retrieved_docs=docs,
        alert_payload="Metrics report host cpu at 100% while hypervisor reports 10%. Alerts flapping. cause unknown.",
        on_call_notes="Ambiguous telemetry signals, telemetry daemon corrupted.",
        run_id="test_ambiguous"
    )
    assert res["verified"] is False
    assert res["evidence_sufficient"] is False
    assert res["confidence"] <= 0.40
    assert res["routing_decision"] == "escalate_human_expert"
    assert res["escalation_reason"] is not None

def test_verification_threshold_behavior():
    """Verify behavior above and below configurable min_similarity_threshold."""
    strict_agent = VerificationAgent(min_similarity_threshold=0.50)
    lenient_agent = VerificationAgent(min_similarity_threshold=0.25)

    doc = [
        Document(
            id="doc_mid",
            source="pg16_monitoring_stats.md",
            title="Monitoring Stats",
            content="Database query latency elevated during peak load. Investigating performance telemetry.",
            metadata={"section": "Stats"},
            score=0.35
        )
    ]
    alert = "Database query latency elevated during peak load."
    notes = "Investigating performance telemetry."
    hyp = "Database query latency elevated during peak load."

    # Strict agent (threshold 0.50) rejects score 0.35
    res_strict = strict_agent.verify_sync(hyp, doc, alert, notes, "test_strict")
    assert res_strict["verified"] is False
    assert res_strict["routing_decision"] == "escalate_human_expert"

    # Lenient agent (threshold 0.25) accepts score 0.35
    res_lenient = lenient_agent.verify_sync(hyp, doc, alert, notes, "test_lenient")
    assert res_lenient["verified"] is True
    assert res_lenient["routing_decision"] in ["escalate_sre", "escalate_dba"]

def test_verification_malformed_and_unsupported_inputs(agent):
    """Verify that malformed alerts, hardware traps, and novel protocols escalate to human expert."""
    # Malformed alert payload
    res_malformed = agent.verify_sync(
        hypothesis="Corrupted data",
        retrieved_docs=[],
        alert_payload="{ 'status': 'ERR', 'host': '???', 'msg': 'fail...' }",
        on_call_notes="",
        run_id="test_malformed"
    )
    assert res_malformed["verified"] is False
    assert res_malformed["routing_decision"] == "escalate_human_expert"
    assert res_malformed["confidence"] <= 0.20

    # Hardware parity bus glitch
    res_hardware = agent.verify_sync(
        hypothesis="Hardware trap",
        retrieved_docs=[],
        alert_payload="Unrecognized kernel trap: ECC multi-bit parity failure on bus PCI-03.",
        on_call_notes="Hardware error code 0xDEADBEEF.",
        run_id="test_hardware"
    )
    assert res_hardware["verified"] is False
    assert res_hardware["routing_decision"] == "escalate_human_expert"
    assert res_hardware["confidence"] <= 0.30

    # Novel undocumented protocol error
    res_novel = agent.verify_sync(
        hypothesis="Novel error",
        retrieved_docs=[],
        alert_payload="Service QuantumBilling reporting error code QNTM_40492_ZETA_DESYNC.",
        on_call_notes="Brand new internal protocol deployed 10 minutes ago. No runbooks exist yet.",
        run_id="test_novel"
    )
    assert res_novel["verified"] is False
    assert res_novel["routing_decision"] == "escalate_human_expert"
    assert res_novel["confidence"] <= 0.20
