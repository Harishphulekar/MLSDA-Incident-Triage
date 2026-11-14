"""Tests for Embedding/Retrieval Caching and Per-Client Rate Limiting."""
from src.agentops.caching import IncidentCache
from src.agentops.rate_limiter import RateLimiter

def test_retrieval_and_embedding_caching():
    cache = IncidentCache(default_ttl=3600)
    
    # Embedding caching
    cache.set_embedding("query text", [0.1, 0.2, 0.3])
    cached_emb = cache.get_embedding("query text")
    assert cached_emb == [0.1, 0.2, 0.3]

    # Retrieval caching
    dummy_docs = [{"id": "doc1", "title": "Doc 1", "content": "Text", "source": "s1"}]
    cache.set_retrieval("search query", dummy_docs)
    cached_docs = cache.get_retrieval("search query")
    assert cached_docs == dummy_docs

def test_whole_run_caching_volatile_state_safety_guard():
    cache = IncidentCache(default_ttl=3600)
    
    # Live volatile alert (climbing disk) MUST bypass whole-run cache
    volatile_alert = "Host postgres-primary-01 disk usage at 87% and climbing steadily"
    note = "disk filling, cause unknown"
    result = {"cause_class": "WAL Retention", "confidence": 0.95, "evidence_sufficient": True}

    cache.set_cached_run(volatile_alert, note, result)
    cached = cache.get_cached_run(volatile_alert, note)
    # Verification safety rule: volatile state never returns cached run!
    assert cached is None

def test_per_client_rate_limiter():
    limiter = RateLimiter(requests_per_minute=5, burst_limit=0)
    client_id = "test_client_alpha"

    for i in range(5):
        allowed, remaining, _ = limiter.is_allowed(client_id)
        assert allowed, f"Request {i+1} should be allowed"

    # 6th request exceeds 5 req/min
    allowed, remaining, retry_after = limiter.is_allowed(client_id)
    assert not allowed
    assert retry_after > 0
    assert remaining == 0
