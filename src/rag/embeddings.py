"""Semantic Embedding Generation Module using Sentence-Transformers."""
import os
import pickle
import hashlib
from typing import List, Optional, Union
import numpy as np
from sentence_transformers import SentenceTransformer

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384

class EmbeddingManager:
    """Manages sentence embedding generation, caching, and unit normalization."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        cache_path: str = "./data/cache/embeddings_cache.pkl",
        device: str = "cpu"
    ):
        self.model_name = model_name
        self.cache_path = cache_path
        self.device = device
        self._model: Optional[SentenceTransformer] = None
        self._cache: dict = {}
        self.dimension = EMBEDDING_DIMENSION
        self._load_cache()

    @property
    def model(self) -> SentenceTransformer:
        """Lazy-loads the SentenceTransformer model on first usage."""
        if self._model is None:
            self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    def _load_cache(self):
        """Loads cached embeddings from disk."""
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "rb") as f:
                    self._cache = pickle.load(f)
            except Exception:
                self._cache = {}

    def _save_cache(self):
        """Persists cached embeddings to disk."""
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        try:
            with open(self.cache_path, "wb") as f:
                pickle.dump(self._cache, f)
        except Exception:
            pass

    def _hash_text(self, text: str) -> str:
        """Returns SHA-256 hash of text for caching."""
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

    def embed_texts(
        self,
        texts: List[str],
        batch_size: int = 32,
        normalize: bool = True
    ) -> np.ndarray:
        """Generates unit-normalized semantic embeddings for a batch of texts with disk caching."""
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)

        results = [None] * len(texts)
        missing_indices = []
        missing_texts = []

        # Check in-memory / disk cache
        for idx, text in enumerate(texts):
            h = self._hash_text(text)
            if h in self._cache:
                results[idx] = self._cache[h]
            else:
                missing_indices.append(idx)
                missing_texts.append(text)

        # Compute embeddings for missing items
        if missing_texts:
            computed = self.model.encode(
                missing_texts,
                batch_size=batch_size,
                show_progress_bar=False,
                normalize_embeddings=normalize,
                convert_to_numpy=True
            ).astype(np.float32)

            for idx, emb in zip(missing_indices, computed):
                h = self._hash_text(texts[idx])
                self._cache[h] = emb
                results[idx] = emb

            self._save_cache()

        return np.vstack(results).astype(np.float32)

    def embed_query(self, query: str, normalize: bool = True) -> np.ndarray:
        """Generates unit-normalized embedding for a single search query."""
        vec = self.embed_texts([query], normalize=normalize)
        return vec[0]

# Central embedding manager instance
embedding_manager = EmbeddingManager()
