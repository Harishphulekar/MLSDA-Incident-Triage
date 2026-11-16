"""Modular Retrieval Tools for Multi-Agent Incident Triage and Verification."""
import re
from typing import Any, Dict, List, Optional
from src.rag.schema import SearchResult
from src.rag.embeddings import embedding_manager
from src.rag.vector_store import vector_store

class RetrievalTools:
    """Provides modular, structured retrieval functions for agents."""

    def __init__(self, vs=None, em=None):
        self.vector_store = vs or vector_store
        self.embedding_manager = em or embedding_manager

    def search_postgresql_docs(self, query: str, top_k: int = 3) -> List[SearchResult]:
        """Searches authoritative PostgreSQL official documentation."""
        q_vec = self.embedding_manager.embed_query(query)
        return self.vector_store.search(
            query_vector=q_vec,
            top_k=top_k,
            filters={"document_type": "official_docs"}
        )

    def search_runbooks(self, query: str, top_k: int = 3) -> List[SearchResult]:
        """Searches incident response runbooks."""
        q_vec = self.embedding_manager.embed_query(query)
        return self.vector_store.search(
            query_vector=q_vec,
            top_k=top_k,
            filters={"document_type": "runbook"}
        )

    def lookup_document_section(self, document_id: str, section: str) -> List[SearchResult]:
        """Looks up specific section or chapter within a document by ID and section title."""
        results: List[SearchResult] = []
        sec_lower = section.lower()
        doc_lower = document_id.lower()

        for meta in self.vector_store.metadata:
            if doc_lower in meta["document_id"].lower():
                sec_head = meta.get("section_heading", "").lower()
                if sec_lower in sec_head or any(w in sec_head for w in sec_lower.split() if len(w) > 3):
                    results.append(SearchResult(
                        chunk_id=meta["chunk_id"],
                        document_id=meta["document_id"],
                        source_title=meta["source_title"],
                        source_url=meta["source_url"],
                        postgresql_version=meta.get("postgresql_version", "16"),
                        section=meta.get("section_heading", "General"),
                        relevant_text=meta.get("chunk_text", ""),
                        similarity_score=1.0,
                        page_number=meta.get("page_number"),
                        category=meta.get("incident_category", "general"),
                        document_type=meta.get("document_type", "official_docs")
                    ))
        return results

    def lookup_clause(self, clause_reference: str) -> List[SearchResult]:
        """Finds chunks containing a specific parameter, SQL function, view, or error phrase."""
        results: List[SearchResult] = []
        clause_clean = clause_reference.strip().lower()

        for meta in self.vector_store.metadata:
            text_lower = meta.get("chunk_text", "").lower()
            head_lower = meta.get("section_heading", "").lower()
            if clause_clean in text_lower or clause_clean in head_lower:
                results.append(SearchResult(
                    chunk_id=meta["chunk_id"],
                    document_id=meta["document_id"],
                    source_title=meta["source_title"],
                    source_url=meta["source_url"],
                    postgresql_version=meta.get("postgresql_version", "16"),
                    section=meta.get("section_heading", "General"),
                    relevant_text=meta.get("chunk_text", ""),
                    similarity_score=0.98,
                    page_number=meta.get("page_number"),
                    category=meta.get("incident_category", "general"),
                    document_type=meta.get("document_type", "official_docs")
                ))

        # Sort by exactness/relevance
        results.sort(key=lambda r: len(r.relevant_text))
        return results[:5]

    def lookup_incident_category(self, category: str) -> List[SearchResult]:
        """Retrieves chunks mapped to a designated incident category."""
        results: List[SearchResult] = []
        cat_lower = category.lower()

        for meta in self.vector_store.metadata:
            m_cat = meta.get("incident_category", "").lower()
            m_topic = meta.get("extra_metadata", {}).get("topic", "").lower()
            if cat_lower in m_cat or cat_lower in m_topic:
                results.append(SearchResult(
                    chunk_id=meta["chunk_id"],
                    document_id=meta["document_id"],
                    source_title=meta["source_title"],
                    source_url=meta["source_url"],
                    postgresql_version=meta.get("postgresql_version", "16"),
                    section=meta.get("section_heading", "General"),
                    relevant_text=meta.get("chunk_text", ""),
                    similarity_score=0.90,
                    page_number=meta.get("page_number"),
                    category=meta.get("incident_category", "general"),
                    document_type=meta.get("document_type", "official_docs")
                ))
        return results[:10]

    def retrieve_by_metadata(self, filters: Dict[str, Any], top_k: int = 5) -> List[SearchResult]:
        """Generic structured retrieval filtered strictly by metadata attributes."""
        results: List[SearchResult] = []
        for meta in self.vector_store.metadata:
            match = True
            for k, v in filters.items():
                m_val = meta.get(k) or meta.get("extra_metadata", {}).get(k)
                if isinstance(v, list):
                    if m_val not in v:
                        match = False
                        break
                elif m_val != v:
                    match = False
                    break
            if match:
                results.append(SearchResult(
                    chunk_id=meta["chunk_id"],
                    document_id=meta["document_id"],
                    source_title=meta["source_title"],
                    source_url=meta["source_url"],
                    postgresql_version=meta.get("postgresql_version", "16"),
                    section=meta.get("section_heading", "General"),
                    relevant_text=meta.get("chunk_text", ""),
                    similarity_score=0.85,
                    page_number=meta.get("page_number"),
                    category=meta.get("incident_category", "general"),
                    document_type=meta.get("document_type", "official_docs")
                ))
                if len(results) >= top_k:
                    break
        return results

retrieval_tools = RetrievalTools()
