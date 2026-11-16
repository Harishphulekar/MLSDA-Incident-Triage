"""Evidence Tracking and Verifiable Citation Formatting Module."""
import re
from typing import Any, Dict, List, Optional
from src.rag.schema import Citation, SearchResult

class CitationFormatter:
    """Formats and validates citations against retrieved corpus passages with zero hallucination."""

    @staticmethod
    def extract_salient_passage(text: str, max_words: int = 40) -> str:
        """Extracts an authoritative, representative passage from text."""
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        for s in sentences:
            s_clean = s.strip()
            # Prefer sentences with technical substance
            if any(term in s_clean.lower() for term in ["slot", "wal", "retention", "connection", "replica", "lock", "max_"]):
                words = s_clean.split()
                if len(words) > max_words:
                    return " ".join(words[:max_words]) + "..."
                return s_clean
        
        words = text.strip().split()
        if len(words) > max_words:
            return " ".join(words[:max_words]) + "..."
        return text.strip()

    @classmethod
    def create_citation(
        cls,
        doc: SearchResult,
        quoted_passage: Optional[str] = None
    ) -> Citation:
        """Constructs a strictly grounded citation from a SearchResult."""
        actual_text = doc.relevant_text

        # Validate that quoted_passage actually exists in retrieved chunk
        if quoted_passage:
            clean_quote = quoted_passage.strip()
            if clean_quote.lower() not in actual_text.lower():
                # If exact quote is missing, extract the true grounded passage from chunk
                passage = cls.extract_salient_passage(actual_text)
            else:
                passage = clean_quote
        else:
            passage = cls.extract_salient_passage(actual_text)

        # Build citation ID
        citation_id = f"CIT-{doc.chunk_id}"

        return Citation(
            citation_id=citation_id,
            document_id=doc.document_id,
            source_title=doc.source_title,
            source_url=doc.source_url,
            postgresql_version=doc.postgresql_version,
            section=doc.section,
            quoted_passage=passage,
            page_number=doc.page_number,
            chunk_id=doc.chunk_id,
            confidence_score=doc.similarity_score
        )

    @classmethod
    def format_for_agent_response(cls, results: List[SearchResult], max_citations: int = 3) -> List[Dict[str, Any]]:
        """Formats citations to match the schema consumed by VerificationAgent and Orchestrator."""
        citations = []
        for doc in results[:max_citations]:
            cit = cls.create_citation(doc)
            citations.append({
                "source": doc.source_title,
                "source_url": doc.source_url,
                "postgresql_version": doc.postgresql_version,
                "section": doc.section,
                "chunk_id": doc.chunk_id,
                "quoted_passage": cit.quoted_passage,
                "confidence_score": doc.similarity_score
            })
        return citations

    @classmethod
    def format_markdown_bibliography(cls, citations: List[Citation]) -> str:
        """Formats citations as a clean Markdown bibliography section."""
        if not citations:
            return "_No authoritative documentation citations available for this incident._"

        lines = ["### Evidence & Authoritative Citations\n"]
        for idx, c in enumerate(citations, 1):
            lines.append(
                f"{idx}. **[{c.source_title}]({c.source_url})**  \n"
                f"   - **Section:** {c.section} (PostgreSQL {c.postgresql_version})  \n"
                f"   - **Reference Chunk:** `{c.chunk_id}`  \n"
                f"   - **Evidence Passage:** *\"{c.quoted_passage}\"*\n"
            )
        return "\n".join(lines)

    @classmethod
    def verify_groundedness(cls, claimed_passage: str, retrieved_docs: List[SearchResult]) -> bool:
        """Strictly checks whether a claimed statement or citation is supported by retrieved docs."""
        if not retrieved_docs or not claimed_passage:
            return False

        passage_clean = claimed_passage.strip().lower()
        combined_evidence = " ".join([d.relevant_text for d in retrieved_docs]).lower()

        # Check for phrase match or substantial token overlap
        if passage_clean in combined_evidence:
            return True

        passage_tokens = set(re.findall(r"\w+", passage_clean))
        if not passage_tokens:
            return False

        evidence_tokens = set(re.findall(r"\w+", combined_evidence))
        overlap = len(passage_tokens.intersection(evidence_tokens))
        return (overlap / len(passage_tokens)) >= 0.70

citation_formatter = CitationFormatter()
