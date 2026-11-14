"""Caching Layer for Embeddings and Retrieval with Evidence Verification Safety."""
import hashlib
import time
from typing import Any, Dict, List, Optional
from src.agentops.logging import app_logger

class CacheEntry:
    def __init__(self, value: Any, ttl_seconds: int):
        self.value = value
        self.created_at = time.time()
        self.ttl = ttl_seconds

    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl

class IncidentCache:
    """Multi-tier cache with explicit safety guards preventing verification bypass."""
    def __init__(self, default_ttl: int = 3600):
        self.default_ttl = default_ttl
        self._embedding_cache: Dict[str, CacheEntry] = {}
        self._retrieval_cache: Dict[str, CacheEntry] = {}
        self._run_cache: Dict[str, CacheEntry] = {}
        self.hits = 0
        self.misses = 0

    def _hash_key(self, text: str) -> str:
        return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()

    # 1. Embedding Caching
    def get_embedding(self, text: str) -> Optional[List[float]]:
        key = self._hash_key(text)
        entry = self._embedding_cache.get(key)
        if entry and not entry.is_expired():
            self.hits += 1
            return entry.value
        self.misses += 1
        return None

    def set_embedding(self, text: str, embedding: List[float], ttl: Optional[int] = None):
        key = self._hash_key(text)
        self._embedding_cache[key] = CacheEntry(embedding, ttl or self.default_ttl)

    # 2. Retrieval Caching
    def get_retrieval(self, query: str) -> Optional[List[Dict[str, Any]]]:
        key = self._hash_key(query)
        entry = self._retrieval_cache.get(key)
        if entry and not entry.is_expired():
            self.hits += 1
            app_logger.info(f"Retrieval Cache HIT for query '{query[:30]}...'")
            return entry.value
        self.misses += 1
        return None

    def set_retrieval(self, query: str, results: List[Dict[str, Any]], ttl: Optional[int] = None):
        key = self._hash_key(query)
        self._retrieval_cache[key] = CacheEntry(results, ttl or self.default_ttl)

    # 3. Safe Whole-Run Caching Guard
    def get_cached_run(self, alert_text: str, on_call_note: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves whole-run result ONLY if safe.
        Incidents concerning live state (e.g. disk climbing, replication lag) MUST NOT return stale diagnosis.
        """
        combined = f"{alert_text}::{on_call_note}".lower()
        
        # Unsafe keywords that require live verification
        volatile_keywords = ["climbing", "increasing", "lag", "filling", "spiking", "exhaustion", "growing"]
        if any(w in combined for w in volatile_keywords):
            # Bypass whole-run cache for safety
            return None

        key = self._hash_key(combined)
        entry = self._run_cache.get(key)
        if entry and not entry.is_expired():
            self.hits += 1
            app_logger.info("Whole-run cache HIT (Safe non-volatile alert)")
            return entry.value

        self.misses += 1
        return None

    def set_cached_run(self, alert_text: str, on_call_note: str, result: Dict[str, Any], ttl: int = 300):
        # Only cache runs that were confidently verified and non-volatile
        if result.get("evidence_sufficient") and result.get("confidence", 0) > 0.8:
            key = self._hash_key(f"{alert_text}::{on_call_note}")
            self._run_cache[key] = CacheEntry(result, ttl)

    def clear(self):
        self._embedding_cache.clear()
        self._retrieval_cache.clear()
        self._run_cache.clear()

incident_cache = IncidentCache()
