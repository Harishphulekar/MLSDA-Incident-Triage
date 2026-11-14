"""RAG Retriever Module: Vector and Keyword Document Retrieval."""
import os
import glob
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from src.agentops.logging import log_retrieval_event, app_logger
from src.agentops.tracing import trace_span
from src.agentops.metrics import AGENT_TOOL_CALLS_TOTAL
from src.agentops.caching import incident_cache

class Document(BaseModel):
    id: str
    title: str
    content: str
    source: str
    score: float = 0.0

class KnowledgeRetriever:
    """Manages knowledge base retrieval across runbooks and PostgreSQL documentation."""
    def __init__(self, corpus_dir: str = "./src/rag/corpus"):
        self.corpus_dir = corpus_dir
        self.documents: List[Document] = []
        self._load_local_corpus()

    def _load_local_corpus(self):
        """Loads markdown documents from corpus directory."""
        if not os.path.exists(self.corpus_dir):
            return

        self.documents.clear()
        for filepath in glob.glob(os.path.join(self.corpus_dir, "*.md")):
            filename = os.path.basename(filepath)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                title = content.split("\n")[0].replace("#", "").strip() if content else filename
                self.documents.append(Document(
                    id=filename,
                    title=title,
                    content=content,
                    source=filename,
                    score=1.0
                ))
            except Exception as e:
                app_logger.error(f"Failed to read corpus file {filepath}: {e}")

    def retrieve(self, query: str, top_k: int = 3) -> List[Document]:
        """Retrieves top-k relevant documents with domain-boosted keyword scoring, caching, and tracing."""
        with trace_span("RetrievalAgent.search_runbooks", {"rag.query": query, "rag.top_k": top_k}):
            # Check retrieval cache
            cached = incident_cache.get_retrieval(query)
            if cached:
                docs = [Document(**d) for d in cached]
                AGENT_TOOL_CALLS_TOTAL.labels(agent="RetrievalAgent", tool_name="vector_search", status="cache_hit").inc()
                log_retrieval_event(query, len(docs), [d.source for d in docs])
                return docs

            # High-value domain keywords to boost
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
                        score=round(normalized_score, 4)
                    ))

            scored_docs.sort(key=lambda d: d.score, reverse=True)
            results = scored_docs[:top_k]

            # Cache retrieval results
            incident_cache.set_retrieval(query, [d.model_dump() for d in results])

            AGENT_TOOL_CALLS_TOTAL.labels(agent="RetrievalAgent", tool_name="vector_search", status="success").inc()
            log_retrieval_event(query, len(results), [d.source for d in results])
            return results

retriever = KnowledgeRetriever()
