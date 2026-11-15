"""Vector Database Module: Persistent FAISS Indexing and Metadata Filtering."""
import os
import json
from typing import Any, Callable, Dict, List, Optional
import numpy as np
import faiss
from src.rag.schema import ChunkMetadata, SearchResult

class FAISSVectorStore:
    """Manages persistent FAISS vector indexing with metadata storage and filtering."""

    def __init__(self, persist_dir: str = "./data/faiss"):
        self.persist_dir = persist_dir
        self.index_file = os.path.join(persist_dir, "index.faiss")
        self.metadata_file = os.path.join(persist_dir, "metadata.json")
        self.dimension = 384
        self.index: Optional[faiss.Index] = None
        self.metadata: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        """Loads index and metadata from disk if available."""
        if os.path.exists(self.index_file) and os.path.exists(self.metadata_file):
            try:
                self.index = faiss.read_index(self.index_file)
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    self.metadata = json.load(f)
            except Exception:
                self.index = None
                self.metadata = []

    def save(self):
        """Persists FAISS index and metadata to disk."""
        os.makedirs(self.persist_dir, exist_ok=True)
        if self.index is not None:
            faiss.write_index(self.index, self.index_file)
        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2)

    def is_empty(self) -> bool:
        """Returns True if the index is missing or contains no vectors."""
        return self.index is None or self.index.ntotal == 0 or len(self.metadata) == 0

    def build_index(self, chunks: List[ChunkMetadata], embeddings: np.ndarray):
        """Constructs a new FAISS IndexFlatIP (Inner Product = Cosine Similarity for normalized vectors)."""
        if len(chunks) == 0 or len(embeddings) == 0:
            self.index = faiss.IndexFlatIP(self.dimension)
            self.metadata = []
            self.save()
            return

        dim = embeddings.shape[1]
        self.dimension = dim
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(embeddings.astype(np.float32))
        self.metadata = [c.to_dict() for c in chunks]
        self.save()

    def add_chunks(self, chunks: List[ChunkMetadata], embeddings: np.ndarray):
        """Incrementally adds new chunks to existing index."""
        if self.index is None:
            self.build_index(chunks, embeddings)
            return

        self.index.add(embeddings.astype(np.float32))
        self.metadata.extend([c.to_dict() for c in chunks])
        self.save()

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        min_score: float = 0.0
    ) -> List[SearchResult]:
        """Performs semantic similarity search with metadata filtering."""
        if self.is_empty():
            return []

        if len(query_vector.shape) == 1:
            query_vector = np.expand_dims(query_vector, axis=0)

        # Retrieve a broader pool of candidates to allow metadata filtering
        candidate_k = min(self.index.ntotal, max(top_k * 4, 30))
        scores, indices = self.index.search(query_vector.astype(np.float32), candidate_k)

        results: List[SearchResult] = []
        scores_row = scores[0]
        indices_row = indices[0]

        for score, idx in zip(scores_row, indices_row):
            if idx < 0 or idx >= len(self.metadata):
                continue
            if score < min_score:
                continue

            meta = self.metadata[idx]

            # Apply metadata filters
            if filters:
                match = True
                for fk, fv in filters.items():
                    val = meta.get(fk) or meta.get("extra_metadata", {}).get(fk)
                    if isinstance(fv, list):
                        if val not in fv:
                            match = False
                            break
                    elif val != fv:
                        match = False
                        break
                if not match:
                    continue

            result = SearchResult(
                chunk_id=meta["chunk_id"],
                document_id=meta["document_id"],
                source_title=meta["source_title"],
                source_url=meta["source_url"],
                postgresql_version=meta.get("postgresql_version", "16"),
                section=meta.get("section_heading", "General"),
                relevant_text=meta.get("chunk_text", ""),
                similarity_score=round(float(score), 4),
                page_number=meta.get("page_number"),
                category=meta.get("incident_category", "general"),
                document_type=meta.get("document_type", "official_docs")
            )
            results.append(result)

            if len(results) >= top_k:
                break

        return results

# Default vector store instance
vector_store = FAISSVectorStore()
