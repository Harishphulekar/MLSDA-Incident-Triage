"""Data models and schemas for Corpus, Chunks, Search Results, and Citations."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class ChunkMetadata(BaseModel):
    """Rich metadata preserved for every chunk in the knowledge base."""
    chunk_id: str
    document_id: str
    source_title: str
    source_url: str
    postgresql_version: str = "16"
    section_heading: str
    page_number: Optional[int] = None
    document_type: str = "official_docs"  # "official_docs" or "runbook"
    incident_category: str = "general"
    chunk_text: str
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

class SearchResult(BaseModel):
    """Structured search result returned by retrieval tools."""
    chunk_id: str
    document_id: str
    source_title: str
    source_url: str
    postgresql_version: str = "16"
    section: str
    relevant_text: str
    similarity_score: float = 0.0
    page_number: Optional[int] = None
    category: str = "general"
    document_type: str = "official_docs"

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

class Document(BaseModel):
    """Backward-compatible Document model for Member 3's existing agents."""
    id: str
    title: str
    content: str
    source: str
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

class Citation(BaseModel):
    """Traceable, verifiable citation reference."""
    citation_id: str
    document_id: str
    source_title: str
    source_url: str
    postgresql_version: str = "16"
    section: str
    quoted_passage: str
    page_number: Optional[int] = None
    chunk_id: Optional[str] = None
    confidence_score: float = 1.0

    def format_inline_markdown(self) -> str:
        """Formats citation as a standard Markdown link with section."""
        return f"[{self.source_title}]({self.source_url}) ({self.section})"
