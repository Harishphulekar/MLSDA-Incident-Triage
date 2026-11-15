"""Semantic Embedding Generation Module using Sentence-Transformers."""
import os
import re
import pickle
import hashlib
from typing import Any, List, Optional, Union
import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384

class _DeterministicFallbackTransformer:
    """Lightweight deterministic feature-hashing embedding model when sentence-transformers is unavailable."""

    def __init__(self, dimension: int = EMBEDDING_DIMENSION):
        self.dimension = dimension

    def _stem(self, word: str) -> str:
        w = word.lower()
        for suffix in ["ing", "tion", "tions", "ed", "es", "s", "ment", "ments", "ance", "er", "ers"]:
            if len(w) > len(suffix) + 3 and w.endswith(suffix):
                return w[:-len(suffix)]
        return w

    def encode(
        self,
        sentences: Union[str, List[str]],
        batch_size: int = 32,
        show_progress_bar: bool = False,
        normalize_embeddings: bool = True,
        convert_to_numpy: bool = True
    ) -> np.ndarray:
        if isinstance(sentences, str):
            sentences = [sentences]

        stopwords = {"a", "an", "the", "and", "or", "in", "on", "at", "to", "for", "of", "with", "is", "are", "was", "were"}
        acronym_map = {
            "wal": ["write", "ahead", "log"],
            "io": ["input", "output"],
            "oom": ["out", "of", "memory"],
            "conn": ["connection"]
        }
        vectors = []
        for text in sentences:
            vec = np.zeros(self.dimension, dtype=np.float32)
            clean_text = text.lower().strip()
            raw_words = re.findall(r"[a-z0-9_]+", clean_text)
            words = []
            for w in raw_words:
                words.append(w)
                if w in acronym_map:
                    words.extend(acronym_map[w])

            for raw_w in words:
                if raw_w in stopwords:
                    continue
                stemmed = self._stem(raw_w)
                weight = 4.0 if len(stemmed) >= 4 else 2.0

                # Hash stemmed token
                h = int(hashlib.md5(stemmed.encode("utf-8")).hexdigest(), 16)
                idx = h % self.dimension
                vec[idx] += weight

                # Hash raw word
                hw = int(hashlib.md5(raw_w.encode("utf-8")).hexdigest(), 16)
                vec[hw % self.dimension] += 2.0

                # Character 3-grams
                for i in range(len(stemmed) - 2):
                    tri = stemmed[i:i+3]
                    htri = int(hashlib.md5(tri.encode("utf-8")).hexdigest(), 16)
                    vec[htri % self.dimension] += 1.0

            if normalize_embeddings:
                norm = np.linalg.norm(vec)
                if norm > 1e-9:
                    vec = vec / norm
                else:
                    vec[0] = 1.0
            vectors.append(vec)

        arr = np.array(vectors, dtype=np.float32)
        return arr

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
        self._model: Any = None
        self._cache: dict = {}
        self.dimension = EMBEDDING_DIMENSION
        self._load_cache()

    @property
    def model(self) -> Any:
        """Lazy-loads the SentenceTransformer model on first usage, with fallback adapter if unavailable."""
        if self._model is None:
            if SentenceTransformer is not None:
                self._model = SentenceTransformer(self.model_name, device=self.device)
            else:
                self._model = _DeterministicFallbackTransformer(self.dimension)
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
