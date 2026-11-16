"""Automated Tests for Corpus Ingestion, Document Processing, Embeddings, and Vector Indexing."""
import os
import tempfile
import numpy as np
import pytest

from src.rag.schema import ChunkMetadata, SearchResult, Citation
from src.rag.document_processor import DocumentProcessor
from src.rag.embeddings import EmbeddingManager
from src.rag.vector_store import FAISSVectorStore

# 1. Document Ingestion & Manifest Test
def test_corpus_manifest_integrity():
    """Verify official PostgreSQL 16 documentation manifest."""
    manifest_path = "./data/metadata/corpus_manifest.json"
    assert os.path.exists(manifest_path), "Corpus manifest must exist"
    import json
    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["postgresql_version"] == "16"
    assert data["total_documents"] >= 18
    for doc in data["documents"]:
        assert "document_id" in doc
        assert "source_url" in doc
        assert "https://www.postgresql.org/docs/16/" in doc["source_url"]
        assert doc["postgresql_version"] == "16"
        assert len(doc["sha256"]) == 64

# 2. Markdown Parsing Test
def test_markdown_and_doc_parsing():
    """Verify section extraction and frontmatter parsing on technical document."""
    processor = DocumentProcessor(chunk_size=500, chunk_overlap=50)
    sample_md = """---
document_id: test_doc_01
title: "PostgreSQL 16 Replication Overview"
source_url: "https://www.postgresql.org/docs/16/warm-standby.html"
postgresql_version: "16"
category: "replication"
---

# PostgreSQL 16 Replication Overview

## Streaming Architecture
Streaming replication operates over TCP connections.

```sql
SELECT client_addr, state FROM pg_stat_replication;
```

## Replication Slots
Replication slots retain WAL files until consumed.
"""
    fm, content = processor.parse_frontmatter_and_content(sample_md)
    assert fm["document_id"] == "test_doc_01"
    assert fm["postgresql_version"] == "16"
    assert "Streaming Architecture" in content

    sections = processor.split_into_sections(content)
    assert len(sections) >= 2
    headings = [s["heading"] for s in sections]
    assert "Streaming Architecture" in headings
    assert "Replication Slots" in headings

# 3. Chunk Generation & Bounds Test
def test_chunk_generation_and_size_bounds():
    """Verify chunks respect paragraph structure and bounds without splitting arbitrary words."""
    processor = DocumentProcessor(chunk_size=300, chunk_overlap=50, min_chunk_size=50)
    text = (
        "PostgreSQL WAL segment files are 16 megabytes in size by default. "
        "The primary retains WAL files when a replication slot is active or when an archiver fails.\n\n"
        "Replication slots provide an automated mechanism to prevent the primary from recycling "
        "WAL segments before standby replicas have consumed them.\n\n"
        "If a standby becomes disconnected, WAL files will accumulate steadily on the primary filesystem."
    )
    chunks = processor.chunk_section_text(text)
    assert len(chunks) >= 1
    for chunk in chunks:
        assert len(chunk) > 40
        assert "PostgreSQL" in chunk or "Replication" in chunk or "standby" in chunk

# 4. Metadata Preservation Test
def test_chunk_metadata_preservation():
    """Verify all 10 required metadata fields are strictly preserved in each chunk."""
    processor = DocumentProcessor(chunk_size=1000)
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as tf:
        tf.write("""---
document_id: doc_meta_test
title: "WAL Retention Test"
source_url: "https://www.postgresql.org/docs/16/wal.html"
postgresql_version: "16"
category: "storage_and_wal"
topic: "wal"
---

# WAL Retention Test

## Section 1: Overview
WAL retention ensures recovery consistency.
""")
        temp_path = tf.name

    try:
        chunks = processor.process_file(temp_path, default_category="storage_and_wal")
        assert len(chunks) >= 1
        c = chunks[0]
        assert c.chunk_id.startswith("doc_meta_test_")
        assert c.document_id == "doc_meta_test"
        assert c.source_title == "WAL Retention Test"
        assert c.source_url == "https://www.postgresql.org/docs/16/wal.html"
        assert c.postgresql_version == "16"
        assert c.section_heading == "Section 1: Overview"
        assert c.document_type == "official_docs"
        assert c.incident_category == "storage_and_wal"
        assert "WAL retention" in c.chunk_text
    finally:
        os.remove(temp_path)

# 5. Embedding Generation & Normalization Test
def test_embedding_generation_and_normalization():
    """Verify sentence-transformers generates 384-dim unit-normalized vectors."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        cache_path = os.path.join(tmp_dir, "test_cache.pkl")
        em = EmbeddingManager(cache_path=cache_path)

        texts = [
            "Replication slot retaining WAL logs on primary server.",
            "Connection exhaustion due to max_connections reached."
        ]
        embeddings = em.embed_texts(texts, normalize=True)

        assert embeddings.shape == (2, 384)
        # Check unit L2 normalization: norm should equal 1.0
        norms = np.linalg.norm(embeddings, axis=1)
        for n in norms:
            assert np.isclose(n, 1.0, atol=1e-4)

        # Test caching: second call should use cache
        emb_cached = em.embed_texts(texts, normalize=True)
        assert np.allclose(embeddings, emb_cached)

# 6 & 7. Vector Index Creation & Persistence Test
def test_vector_index_creation_and_persistence():
    """Verify FAISS vector index building, disk persistence, and reloading."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        vs = FAISSVectorStore(persist_dir=tmp_dir)
        assert vs.is_empty()

        # Create synthetic chunks
        chunk1 = ChunkMetadata(
            chunk_id="chunk_01",
            document_id="doc_wal",
            source_title="PostgreSQL WAL",
            source_url="https://postgresql.org/wal",
            postgresql_version="16",
            section_heading="WAL Retention",
            document_type="official_docs",
            incident_category="storage_and_wal",
            chunk_text="Replication slots ensure primary retains WAL."
        )
        chunk2 = ChunkMetadata(
            chunk_id="chunk_02",
            document_id="doc_conn",
            source_title="PostgreSQL Connections",
            source_url="https://postgresql.org/conn",
            postgresql_version="16",
            section_heading="Connection Limits",
            document_type="official_docs",
            incident_category="connections",
            chunk_text="max_connections limits concurrent database clients."
        )

        em = EmbeddingManager()
        embeddings = em.embed_texts([chunk1.chunk_text, chunk2.chunk_text])

        vs.build_index([chunk1, chunk2], embeddings)
        assert not vs.is_empty()
        assert os.path.exists(vs.index_file)
        assert os.path.exists(vs.metadata_file)

        # Reload index in fresh instance
        vs_reloaded = FAISSVectorStore(persist_dir=tmp_dir)
        assert not vs_reloaded.is_empty()
        assert len(vs_reloaded.metadata) == 2

# 8. Semantic Search Test
def test_semantic_similarity_search():
    """Verify semantic search returns relevant chunks with accurate similarity scores."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        vs = FAISSVectorStore(persist_dir=tmp_dir)
        em = EmbeddingManager()

        c1 = ChunkMetadata(
            chunk_id="c1", document_id="d1", source_title="WAL", source_url="https://pg.org",
            section_heading="WAL", document_type="official_docs", incident_category="wal",
            chunk_text="A replication slot retains Write-Ahead Log segments on the database primary."
        )
        c2 = ChunkMetadata(
            chunk_id="c2", document_id="d2", source_title="Deadlock", source_url="https://pg.org",
            section_heading="Locking", document_type="official_docs", incident_category="performance",
            chunk_text="Deadlocks occur when two concurrent transactions hold locks that each other needs."
        )
        vs.build_index([c1, c2], em.embed_texts([c1.chunk_text, c2.chunk_text]))

        q_vec = em.embed_query("retained WAL files causing storage filling")
        results = vs.search(query_vector=q_vec, top_k=1)

        assert len(results) == 1
        assert results[0].chunk_id == "c1"
        assert results[0].similarity_score > 0.2
