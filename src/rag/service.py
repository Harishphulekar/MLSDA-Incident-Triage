"""RAG Service Interface: High-level Python contract for Member 3 Multi-Agent Architecture."""
import json
import os
from typing import Any, Dict, List, Optional
from src.rag.schema import SearchResult, ChunkMetadata, Citation, Document
from src.rag.tools import retrieval_tools, RetrievalTools
from src.rag.iterative_retriever import iterative_retriever, IterativeRetriever, IterativeRetrievalResult
from src.rag.citations import citation_formatter, CitationFormatter
from src.rag.vector_store import vector_store

class RAGService:
    """Unified service exposing all Corpus, RAG, and Citation capabilities to agents."""

    def __init__(
        self,
        tools: Optional[RetrievalTools] = None,
        iter_retriever: Optional[IterativeRetriever] = None,
        policy_path: str = "./data/metadata/severity_escalation_policy.json"
    ):
        self.tools = tools or retrieval_tools
        self.iterative_retriever = iter_retriever or iterative_retriever
        self.policy_path = policy_path
        self._policy: Optional[Dict[str, Any]] = None

    def search_documentation(self, query: str, top_k: int = 3) -> List[SearchResult]:
        """Searches authoritative PostgreSQL 16 documentation."""
        return self.tools.search_postgresql_docs(query=query, top_k=top_k)

    def search_runbooks(self, query: str, top_k: int = 3) -> List[SearchResult]:
        """Searches production incident runbooks."""
        return self.tools.search_runbooks(query=query, top_k=top_k)

    def lookup_document_section(self, document_id: str, section: str) -> List[SearchResult]:
        """Looks up a specific section in a document."""
        return self.tools.lookup_document_section(document_id=document_id, section=section)

    def lookup_clause(self, clause: str) -> List[SearchResult]:
        """Looks up specific parameters, SQL views, or clauses."""
        return self.tools.lookup_clause(clause_reference=clause)

    def lookup_incident_category(self, category: str) -> List[SearchResult]:
        """Retrieves chunks by incident category."""
        return self.tools.lookup_incident_category(category=category)

    def retrieve_iterative(
        self,
        query: str,
        initial_hypothesis: str = "",
        max_iterations: int = 3
    ) -> IterativeRetrievalResult:
        """Executes multi-hop iterative retrieval to uncover non-obvious root causes."""
        return self.iterative_retriever.execute(
            query=query,
            initial_hypothesis=initial_hypothesis
        )

    def format_citations(self, results: List[SearchResult], max_citations: int = 3) -> List[Dict[str, Any]]:
        """Formats verifiable citations from search results."""
        return citation_formatter.format_for_agent_response(results, max_citations=max_citations)

    def get_severity_policy(self) -> Dict[str, Any]:
        """Loads and returns the machine-readable severity and escalation policy."""
        if self._policy is None:
            if os.path.exists(self.policy_path):
                with open(self.policy_path, "r", encoding="utf-8") as f:
                    self._policy = json.load(f)
            else:
                self._policy = {}
        return self._policy

# Singleton service instance
rag_service = RAGService()
