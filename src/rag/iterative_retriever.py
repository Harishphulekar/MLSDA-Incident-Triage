"""Iterative Retrieval Engine: Multi-hop Query Expansion, Gap Analysis, and Bounded Retrieval Loops."""
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field
from src.rag.schema import SearchResult
from src.rag.tools import retrieval_tools
from src.rag.embeddings import embedding_manager
from src.rag.vector_store import vector_store

class IterationRecord(BaseModel):
    """Audit log record for an individual retrieval iteration."""
    iteration_index: int
    query: str
    strategy: str
    retrieved_chunk_ids: List[str]
    identified_gaps: List[str] = Field(default_factory=list)
    reasoning: str

class IterativeRetrievalResult(BaseModel):
    """Accumulated evidence and execution trace produced by iterative retrieval."""
    final_evidence: List[SearchResult]
    iterations: List[IterationRecord]
    total_iterations: int
    evidence_sufficient: bool = True
    gap_summary: List[str] = Field(default_factory=list)

class IterativeRetriever:
    """Orchestrates multi-hop retrieval to uncover non-obvious root causes (e.g. WAL retention for disk growth)."""

    def __init__(self, max_iterations: int = 3, tools=None):
        self.max_iterations = max_iterations
        self.tools = tools or retrieval_tools

    def analyze_evidence_gaps(self, query: str, accumulated_docs: List[SearchResult]) -> Dict[str, Any]:
        """Inspects current evidence against known incident diagnostic patterns to uncover missing facets."""
        q_lower = query.lower()
        combined_text = " ".join([f"{d.section} {d.relevant_text}" for d in accumulated_docs]).lower()
        
        gaps = []
        refined_queries = []

        # Faculty Reference Scenario & Pattern: Disk climbing while tables/indexes not growing
        is_disk_issue = any(k in q_lower for k in ["disk", "space", "filling", "filesystem", "saturation", "full"])
        tables_not_growing = any(k in q_lower for k in ["not growing", "table size", "index size", "constant", "stable", "unknown"])
        
        if is_disk_issue:
            has_slot = ("replication slot" in combined_text or "pg_replication_slots" in combined_text)
            has_archiver = ("archive_command" in combined_text or "pg_stat_archiver" in combined_text)

            if not has_slot:
                gaps.append("Missing evidence on replication slot WAL retention and pg_replication_slots")
                refined_queries.append("PostgreSQL 16 replication slot WAL retention pg_replication_slots restart_lsn max_slot_wal_keep_size pg_drop_replication_slot")
            if not has_archiver:
                gaps.append("Missing evidence on WAL archiver failure accumulating pg_wal segments")
                refined_queries.append("PostgreSQL WAL archiving continuous archiving archive_command failure pg_stat_archiver")

        # Connection Exhaustion Pattern
        if any(k in q_lower for k in ["connection", "max_connections", "pool", "exhaustion", "slots are reserved"]):
            has_idle_in_tx = "idle in transaction" in combined_text
            has_locks = "lock" in combined_text or "pg_blocking_pids" in combined_text
            if not has_idle_in_tx:
                gaps.append("Missing evidence on idle in transaction sessions holding connection slots")
                refined_queries.append("PostgreSQL idle in transaction pg_stat_activity session timeout idle_in_transaction_session_timeout")
            if not has_locks:
                gaps.append("Missing evidence on lock contention and blocking processes")
                refined_queries.append("PostgreSQL lock contention pg_locks pg_blocking_pids exclusive lock")

        # Replication Lag Pattern
        if any(k in q_lower for k in ["replication lag", "standby lag", "replica lag", "desynchronization", "stale data"]):
            has_conflicts = "conflict" in combined_text or "max_standby_streaming_delay" in combined_text
            if not has_conflicts:
                gaps.append("Missing evidence on standby query conflicts delaying WAL replay")
                refined_queries.append("PostgreSQL standby query conflicts max_standby_streaming_delay pg_stat_database_conflicts")

        return {
            "has_gaps": len(gaps) > 0,
            "gaps": gaps,
            "refined_queries": refined_queries
        }

    def execute(
        self,
        query: str,
        initial_hypothesis: str = "",
        top_k_per_step: int = 3
    ) -> IterativeRetrievalResult:
        """Executes bounded multi-step retrieval to accumulate complete, multi-faceted evidence."""
        accumulated_chunks: Dict[str, SearchResult] = {}
        iterations: List[IterationRecord] = []
        seen_queries: Set[str] = set()

        current_query = query
        if initial_hypothesis:
            current_query = f"{query} {initial_hypothesis}"

        for step in range(1, self.max_iterations + 1):
            if current_query in seen_queries:
                break
            seen_queries.add(current_query)

            # 1. Perform retrieval for current query
            strategy = "initial_retrieval" if step == 1 else f"gap_refinement_hop_{step}"
            step_results = self.tools.search_postgresql_docs(current_query, top_k=top_k_per_step)
            runbook_results = self.tools.search_runbooks(current_query, top_k=2)

            combined_step = step_results + runbook_results
            retrieved_ids = []

            for doc in combined_step:
                if doc.chunk_id not in accumulated_chunks:
                    accumulated_chunks[doc.chunk_id] = doc
                    retrieved_ids.append(doc.chunk_id)

            # 2. Inspect evidence gaps
            current_evidence_list = list(accumulated_chunks.values())
            gap_analysis = self.analyze_evidence_gaps(query, current_evidence_list)

            # Record iteration log
            rec = IterationRecord(
                iteration_index=step,
                query=current_query,
                strategy=strategy,
                retrieved_chunk_ids=retrieved_ids,
                identified_gaps=gap_analysis["gaps"],
                reasoning=(
                    f"Iteration {step}: Retrieved {len(retrieved_ids)} new chunks. "
                    f"Identified {len(gap_analysis['gaps'])} diagnostic evidence gaps."
                )
            )
            iterations.append(rec)

            # 3. Check termination conditions
            if not gap_analysis["has_gaps"] or not gap_analysis["refined_queries"]:
                # Evidence is complete; early exit
                break

            # 4. Formulate next refined query
            current_query = gap_analysis["refined_queries"][0]

        # Rank final list prioritizing chunks addressing identified gaps
        q_lower = query.lower()
        tables_not_growing = any(k in q_lower for k in ["not growing", "table size", "index size", "constant", "stable", "unknown"])

        def rank_score(item: SearchResult) -> float:
            score = item.similarity_score
            item_text = f"{item.source_title} {item.section} {item.relevant_text}".lower()
            if tables_not_growing and ("replication slot" in item_text or "pg_replication_slots" in item_text):
                score += 0.25
            if "pg_drop_replication_slot" in item_text or "restart_lsn" in item_text:
                score += 0.15
            return score

        final_list = sorted(list(accumulated_chunks.values()), key=rank_score, reverse=True)
        evidence_sufficient = len(final_list) > 0 and final_list[0].similarity_score >= 0.35

        return IterativeRetrievalResult(
            final_evidence=final_list,
            iterations=iterations,
            total_iterations=len(iterations),
            evidence_sufficient=evidence_sufficient,
            gap_summary=iterations[-1].identified_gaps if iterations else []
        )

# Central iterative retriever instance
iterative_retriever = IterativeRetriever()
