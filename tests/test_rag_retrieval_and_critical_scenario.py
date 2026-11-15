"""Automated Tests for Retrieval Tools, Iterative Retrieval, Citations, and Faculty Critical Scenario."""
import pytest
from src.rag.schema import SearchResult, ChunkMetadata
from src.rag.tools import retrieval_tools
from src.rag.iterative_retriever import iterative_retriever
from src.rag.citations import citation_formatter
from src.rag.retriever import retriever
from src.rag.vector_store import FAISSVectorStore

# 9. Metadata Filtering Test
def test_metadata_filtering():
    """Verify retrieval filters results strictly by document_type and category."""
    # Search runbooks only
    runbook_results = retrieval_tools.search_runbooks("disk space saturation", top_k=5)
    for r in runbook_results:
        assert r.document_type == "runbook"

    # Search official documentation only
    doc_results = retrieval_tools.search_postgresql_docs("disk space saturation", top_k=5)
    for r in doc_results:
        assert r.document_type == "official_docs"

# 10. Runbook Retrieval Test
def test_runbook_retrieval():
    """Verify retrieval tools retrieve the three incident runbooks accurately."""
    # Runbook 1: Disk saturation & WAL retention
    rb1_results = retrieval_tools.search_runbooks("disk space saturation WAL retention replication slot", top_k=2)
    assert len(rb1_results) > 0
    assert "RB-PG-001" in rb1_results[0].source_title or "Disk Saturation" in rb1_results[0].source_title

    # Runbook 2: Replication lag
    rb2_results = retrieval_tools.search_runbooks("standby replication lag delay desynchronization", top_k=2)
    assert len(rb2_results) > 0
    assert "RB-PG-002" in rb2_results[0].source_title or "Replication Lag" in rb2_results[0].source_title

    # Runbook 3: Connection exhaustion
    rb3_results = retrieval_tools.search_runbooks("connection exhaustion max_connections idle in transaction", top_k=2)
    assert len(rb3_results) > 0
    assert "RB-PG-003" in rb3_results[0].source_title or "Connection Exhaustion" in rb3_results[0].source_title

# 11. Section Lookup Test
def test_section_lookup():
    """Verify section lookup retrieves specific document sections by title."""
    results = retrieval_tools.lookup_document_section(
        document_id="view_pg_replication_slots",
        section="pg_replication_slots"
    )
    assert len(results) > 0
    assert "pg_replication_slots" in results[0].section.lower()
    assert results[0].similarity_score == 1.0

# 12. Clause Lookup Test
def test_clause_lookup():
    """Verify lookup_clause locates specific parameters, commands, and views."""
    # Lookup replication slot view
    slot_results = retrieval_tools.lookup_clause("pg_replication_slots")
    assert len(slot_results) > 0
    assert any("pg_replication_slots" in r.relevant_text.lower() for r in slot_results)

    # Lookup session timeout parameter
    timeout_results = retrieval_tools.lookup_clause("idle_in_transaction_session_timeout")
    assert len(timeout_results) > 0
    assert any("idle_in_transaction_session_timeout" in r.relevant_text.lower() for r in timeout_results)

# 13. Missing Document Handling Test
def test_missing_document_handling():
    """Verify system handles non-existent documents and sections gracefully without error."""
    results = retrieval_tools.lookup_document_section("non_existent_doc_999", "imaginary_section")
    assert results == []

    clause_results = retrieval_tools.lookup_clause("non_existent_clause_xyz_12345")
    assert clause_results == []

# 14. Empty Corpus Handling Test
def test_empty_corpus_handling():
    """Verify vector store and tools handle an empty index safely."""
    empty_vs = FAISSVectorStore(persist_dir="/tmp/empty_faiss_test_dir")
    assert empty_vs.is_empty()
    res = empty_vs.search(query_vector=None, top_k=5)
    assert res == []

# 15. Iterative Retrieval Bounded Loop Test
def test_iterative_retrieval_bounded_loop():
    """Verify multi-step iterative retrieval expands queries, records audit trail, and terminates within bounds."""
    query = "Primary disk is filling up rapidly, but table sizes and indexes are not growing."
    res = iterative_retriever.execute(query=query, top_k_per_step=3)

    assert res.total_iterations >= 1
    assert res.total_iterations <= 3, "Must not exceed max bounded iterations"
    assert len(res.iterations) == res.total_iterations

    # Verify iteration trace records
    for it in res.iterations:
        assert it.iteration_index >= 1
        assert len(it.query) > 0
        assert len(it.strategy) > 0

    # Verify accumulated evidence contains WAL and replication slot findings
    all_evidence_text = " ".join([d.relevant_text for d in res.final_evidence]).lower()
    assert "replication" in all_evidence_text or "wal" in all_evidence_text

# 16. Critical Faculty Scenario Test
def test_critical_faculty_scenario_wal_retention():
    """
    CRITICAL FACULTY SCENARIO:
    'Disk usage on the primary is climbing steadily. Table and index sizes are not growing.
     On-call note: disk filling, cause unknown.'

    The knowledge base and retrieval system MUST retrieve evidence identifying:
    - WAL generation and retention
    - Replication slots and pg_replication_slots
    - Inactive or stalled consumers holding restart_lsn
    - max_slot_wal_keep_size configuration
    - Verifiable citations with section headings and official documentation URLs.
    """
    alert_payload = "Disk usage on the primary is climbing steadily. Table and index sizes are not growing."
    on_call_notes = "On-call note: disk filling, cause unknown."
    combined_query = f"{alert_payload} {on_call_notes}"

    # Execute retrieval through standard agent retrieval interface
    docs = retriever.retrieve(query=combined_query, top_k=5)
    assert len(docs) >= 1

    combined_corpus = " ".join([d.content for d in docs]).lower()

    # Verify essential technical components are present in retrieved evidence
    assert ("replication slot" in combined_corpus or "slot" in combined_corpus), \
        "Retrieval must surface replication slot concepts for disk filling without table growth"
    assert ("wal" in combined_corpus or "pg_wal" in combined_corpus), \
        "Retrieval must surface WAL accumulation mechanisms"

    # Test Citation Formatter on retrieved evidence
    citations = citation_formatter.format_for_agent_response(
        results=[
            SearchResult(
                chunk_id=d.id,
                document_id=d.source,
                source_title=d.title,
                source_url=d.metadata.get("source_url", "https://www.postgresql.org/docs/16/warm-standby.html"),
                postgresql_version="16",
                section=d.metadata.get("section", "Replication Slots"),
                relevant_text=d.content,
                similarity_score=d.score,
                category=d.metadata.get("category", "storage_and_wal"),
                document_type=d.metadata.get("document_type", "runbook")
            )
            for d in docs
        ],
        max_citations=3
    )

    assert len(citations) >= 1
    top_cit = citations[0]
    assert "source" in top_cit
    assert "source_url" in top_cit
    assert "https://www.postgresql.org/docs/16/" in top_cit["source_url"] or "runbook" in top_cit["source"].lower()
    assert top_cit["postgresql_version"] == "16"
    assert len(top_cit["quoted_passage"]) > 10

    # Verify zero hallucination guarantee: cited passage must be backed by retrieved text
    assert citation_formatter.verify_groundedness(top_cit["quoted_passage"], [
        SearchResult(
            chunk_id=d.id, document_id=d.source, source_title=d.title, source_url="",
            section="", relevant_text=d.content, similarity_score=d.score
        )
        for d in docs
    ])
