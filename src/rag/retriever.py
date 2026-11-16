"""RAG Retriever Module: Hybrid Semantic Vector, Iterative, and Keyword Document Retrieval."""
import os
import glob
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.agentops.logging import log_retrieval_event, app_logger
from src.agentops.tracing import trace_span
from src.agentops.metrics import AGENT_TOOL_CALLS_TOTAL
from src.agentops.caching import incident_cache

from src.rag.schema import Document, SearchResult
from src.rag.vector_store import vector_store
from src.rag.tools import retrieval_tools
from src.rag.iterative_retriever import iterative_retriever
from src.rag.citations import citation_formatter

class KnowledgeRetriever:
    """Manages knowledge base retrieval across runbooks and official PostgreSQL 16 documentation."""

    def __init__(self, corpus_dir: str = "./src/rag/corpus"):
        self.corpus_dir = corpus_dir
        self.documents: List[Document] = []
        self.vector_store = vector_store
        self.tools = retrieval_tools
        self.iterative_retriever = iterative_retriever
        self._load_local_corpus()

    def _load_local_corpus(self):
        """Loads fallback markdown documents from local corpus directory."""
        if not os.path.exists(self.corpus_dir):
            return

        self.documents.clear()
        for filepath in glob.glob(os.path.join(self.corpus_dir, "*.md")):
            filename = os.path.basename(filepath)
            try:
                with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                title = content.split("\n")[0].replace("#", "").strip() if content else filename
                self.documents.append(Document(
                    id=filename,
                    title=title,
                    content=content,
                    source=filename,
                    score=1.0,
                    metadata={"filepath": filepath, "filename": filename}
                ))
            except Exception as e:
                app_logger.error(f"Failed to read corpus file {filepath}: {e}")

    def retrieve(self, query: str, top_k: int = 3) -> List[Document]:
        """Retrieves top-k relevant documents combining semantic search, iterative expansion, and domain boosting."""
        with trace_span("RetrievalAgent.search_runbooks", {"rag.query": query, "rag.top_k": top_k}):
            # 1. Check retrieval cache
            cached = incident_cache.get_retrieval(query)
            if cached:
                docs = [Document(**d) for d in cached]
                AGENT_TOOL_CALLS_TOTAL.labels(agent="RetrievalAgent", tool_name="vector_search", status="cache_hit").inc()
                log_retrieval_event(query, len(docs), [d.source for d in docs])
                return docs

            # 2. Check if FAISS vector store is available
            if not self.vector_store.is_empty():
                try:
                    iter_res = self.iterative_retriever.execute(query=query, top_k_per_step=top_k)
                    results: List[Document] = []
                    for sr in iter_res.final_evidence[:top_k]:
                        # Use source filename / doc_id for backwards compatibility with verification agent checks
                        source_id = sr.document_id
                        if not source_id.endswith(".md"):
                            source_id = f"{source_id}.md"

                        results.append(Document(
                            id=sr.chunk_id,
                            title=sr.source_title,
                            content=f"## {sr.section}\n\n{sr.relevant_text}",
                            source=source_id,
                            score=sr.similarity_score,
                            metadata={
                                "chunk_id": sr.chunk_id,
                                "document_id": sr.document_id,
                                "source_url": sr.source_url,
                                "postgresql_version": sr.postgresql_version,
                                "section": sr.section,
                                "category": sr.category,
                                "document_type": sr.document_type
                            }
                        ))

                    if results:
                        incident_cache.set_retrieval(query, [d.model_dump() for d in results])
                        AGENT_TOOL_CALLS_TOTAL.labels(agent="RetrievalAgent", tool_name="vector_search", status="success").inc()
                        log_retrieval_event(query, len(results), [d.source for d in results])
                        return results
                except Exception as e:
                    app_logger.warning(f"Vector search failed, falling back to keyword retrieval: {e}")

            # 3. Fallback: Keyword-boosted local corpus search
            domain_boosts = {
                "replication": 3.0, "slot": 3.0, "wal": 3.0, "deadlock": 3.5, "lock": 2.5,
                "oom": 3.5, "memory": 2.5, "wraparound": 4.0, "freeze": 3.0, "vacuum": 2.5,
                "checkpoint": 3.5, "connection": 2.5, "pool": 2.5, "disk": 2.0
            }

            query_terms = set(query.lower().split())
            scored_docs: List[Document] = []

            for doc in self.documents:
                doc_text = f"{doc.title} {doc.content}".lower()
                score = 0.0
                matches = 0

                for term in query_terms:
                    clean_term = term.strip(",.()[]{}'\"")
                    if len(clean_term) > 3 and clean_term in doc_text:
                        weight = domain_boosts.get(clean_term, 1.0)
                        score += (0.15 * weight)
                        matches += 1

                if matches > 0:
                    normalized_score = min(1.0, 0.25 + score)
                    scored_docs.append(Document(
                        id=doc.id,
                        title=doc.title,
                        content=doc.content,
                        source=doc.source,
                        score=round(normalized_score, 4),
                        metadata=doc.metadata
                    ))

            scored_docs.sort(key=lambda d: d.score, reverse=True)
            results = scored_docs[:top_k]

            incident_cache.set_retrieval(query, [d.model_dump() for d in results])
            AGENT_TOOL_CALLS_TOTAL.labels(agent="RetrievalAgent", tool_name="vector_search", status="success").inc()
            log_retrieval_event(query, len(results), [d.source for d in results])
            return results

    # Reusable Agent Tools (Phase 8)
    def search_postgresql_docs(self, query: str, top_k: int = 3) -> List[SearchResult]:
        return self.tools.search_postgresql_docs(query, top_k)

    def search_runbooks(self, query: str, top_k: int = 3) -> List[SearchResult]:
        return self.tools.search_runbooks(query, top_k)

    def lookup_document_section(self, document_id: str, section: str) -> List[SearchResult]:
        return self.tools.lookup_document_section(document_id, section)

    def lookup_clause(self, clause_reference: str) -> List[SearchResult]:
        return self.tools.lookup_clause(clause_reference)

    def lookup_incident_category(self, category: str) -> List[SearchResult]:
        return self.tools.lookup_incident_category(category)

    def retrieve_by_metadata(self, filters: Dict[str, Any], top_k: int = 5) -> List[SearchResult]:
        return self.tools.retrieve_by_metadata(filters, top_k)

    def retrieve_iterative(self, query: str, initial_hypothesis: str = "", max_iterations: int = 3):
        return self.iterative_retriever.execute(query, initial_hypothesis)

    def format_citations(self, results: List[SearchResult], max_citations: int = 3):
        return citation_formatter.format_for_agent_response(results, max_citations)

retriever = KnowledgeRetriever()
