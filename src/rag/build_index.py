"""CLI script to build and persist the FAISS Vector Index for PostgreSQL documentation and runbooks."""
import os
import sys
import time
from typing import List
from src.rag.document_processor import DocumentProcessor
from src.rag.embeddings import embedding_manager
from src.rag.vector_store import vector_store
from src.rag.schema import ChunkMetadata

def build_complete_index(
    corpus_dir: str = "./data/corpus",
    runbooks_dir: str = "./data/runbooks",
    persist_dir: str = "./data/faiss"
):
    """Processes all official docs and runbooks, computes embeddings, and builds the FAISS index."""
    start_time = time.time()
    processor = DocumentProcessor(chunk_size=1800, chunk_overlap=250)
    all_chunks: List[ChunkMetadata] = []

    print("=" * 60)
    print("Building Production PostgreSQL 16 Knowledge Base & Vector Index")
    print("=" * 60)

    # 1. Ingest official PostgreSQL documentation
    if os.path.exists(corpus_dir):
        print(f"Ingesting official PostgreSQL documentation from: {corpus_dir}")
        doc_chunks = processor.process_directory(
            dir_path=corpus_dir,
            document_type="official_docs"
        )
        print(f"Extracted {len(doc_chunks)} chunks from official documentation.")
        all_chunks.extend(doc_chunks)
    else:
        print(f"Warning: Corpus directory '{corpus_dir}' does not exist.")

    # 2. Ingest incident runbooks
    if os.path.exists(runbooks_dir):
        print(f"Ingesting incident runbooks from: {runbooks_dir}")
        runbook_chunks = processor.process_directory(
            dir_path=runbooks_dir,
            document_type="runbook"
        )
        print(f"Extracted {len(runbook_chunks)} chunks from incident runbooks.")
        all_chunks.extend(runbook_chunks)
    else:
        print(f"Warning: Runbooks directory '{runbooks_dir}' does not exist.")

    if not all_chunks:
        print("Error: No documents or runbooks found to index!")
        return

    print(f"\nTotal corpus chunks to index: {len(all_chunks)}")

    # 3. Compute semantic embeddings
    print("Generating semantic embeddings with sentence-transformers (all-MiniLM-L6-v2)...")
    texts = [f"{c.source_title} - {c.section_heading}\n{c.chunk_text}" for c in all_chunks]
    embeddings = embedding_manager.embed_texts(texts, batch_size=32, normalize=True)
    print(f"Computed embeddings matrix shape: {embeddings.shape}")

    # 4. Build and persist FAISS index
    print(f"Building persistent FAISS vector index in: {persist_dir}")
    vector_store.persist_dir = persist_dir
    vector_store.index_file = os.path.join(persist_dir, "index.faiss")
    vector_store.metadata_file = os.path.join(persist_dir, "metadata.json")
    vector_store.build_index(all_chunks, embeddings)

    duration = time.time() - start_time
    print("=" * 60)
    print(f"Vector Index Successfully Built in {duration:.2f}s!")
    print(f"- Total indexed chunks: {len(all_chunks)}")
    print(f"- Embedding dimensions: {embeddings.shape[1]}")
    print(f"- Index file: {vector_store.index_file}")
    print(f"- Metadata file: {vector_store.metadata_file}")
    print("=" * 60)

if __name__ == "__main__":
    build_complete_index()
