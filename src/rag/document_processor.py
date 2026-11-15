"""Document Processing Pipeline: Hierarchical, Section-Aware Markdown & HTML Ingestion and Chunking."""
import os
import re
import glob
from typing import Any, Dict, List, Optional, Tuple
from src.rag.schema import ChunkMetadata

class DocumentProcessor:
    """Processes technical documentation and runbooks into semantically coherent, metadata-rich chunks."""

    def __init__(
        self,
        chunk_size: int = 1800,       # Approximate characters (~350-450 words)
        chunk_overlap: int = 250,     # Approximate characters (~40-60 words)
        min_chunk_size: int = 200     # Minimum characters to avoid micro-chunks
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def parse_frontmatter_and_content(self, text: str) -> Tuple[Dict[str, Any], str]:
        """Extracts YAML frontmatter if present and returns clean body text."""
        frontmatter = {}
        content = text

        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                raw_fm = parts[1].strip()
                content = parts[2].strip()
                for line in raw_fm.split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        frontmatter[k.strip()] = v.strip().strip('"').strip("'")

        return frontmatter, content

    def split_into_sections(self, content: str) -> List[Dict[str, Any]]:
        """Splits markdown document into hierarchical sections based on headings (#, ##, ###)."""
        lines = content.split("\n")
        sections = []
        current_heading = "Introduction"
        current_lines = []

        heading_regex = re.compile(r"^(#{1,4})\s+(.+)$")

        for line in lines:
            match = heading_regex.match(line.strip())
            if match:
                # Save previous section if it has content
                if current_lines:
                    sec_text = "\n".join(current_lines).strip()
                    if sec_text:
                        sections.append({
                            "heading": current_heading,
                            "text": sec_text
                        })
                    current_lines = []
                current_heading = match.group(2).strip()
            else:
                current_lines.append(line)

        # Append final section
        if current_lines:
            sec_text = "\n".join(current_lines).strip()
            if sec_text:
                sections.append({
                    "heading": current_heading,
                    "text": sec_text
                })

        return sections

    def chunk_section_text(self, section_text: str) -> List[str]:
        """Splits section text into chunks respecting paragraphs, lists, and code blocks."""
        if len(section_text) <= self.chunk_size:
            return [section_text]

        chunks = []
        paragraphs = re.split(r"\n\s*\n", section_text)
        current_chunk = []
        current_len = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_len = len(para)

            # If adding this paragraph exceeds chunk size and we already have content
            if current_len + para_len > self.chunk_size and current_chunk:
                chunk_str = "\n\n".join(current_chunk).strip()
                if len(chunk_str) >= self.min_chunk_size:
                    chunks.append(chunk_str)

                # Implement overlap by retaining the last paragraph if appropriate
                if len(current_chunk[-1]) <= self.chunk_overlap:
                    current_chunk = [current_chunk[-1], para]
                    current_len = len(current_chunk[0]) + para_len + 2
                else:
                    current_chunk = [para]
                    current_len = para_len
            else:
                current_chunk.append(para)
                current_len += para_len + 2

        if current_chunk:
            final_str = "\n\n".join(current_chunk).strip()
            if len(final_str) >= self.min_chunk_size or not chunks:
                chunks.append(final_str)

        return chunks

    def process_file(
        self,
        filepath: str,
        document_id: Optional[str] = None,
        default_category: str = "general",
        document_type: str = "official_docs"
    ) -> List[ChunkMetadata]:
        """Processes a single file and extracts a list of rich ChunkMetadata objects."""
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            raw_text = f.read()

        filename = os.path.basename(filepath)
        frontmatter, content = self.parse_frontmatter_and_content(raw_text)

        doc_id = frontmatter.get("document_id", document_id or os.path.splitext(filename)[0])
        title = frontmatter.get("title", "")
        if not title:
            first_line = content.split("\n")[0].strip()
            if first_line.startswith("#"):
                title = first_line.replace("#", "").strip()
            else:
                title = filename

        source_url = frontmatter.get("source_url", f"https://www.postgresql.org/docs/16/{filename}")
        version = frontmatter.get("postgresql_version", "16")
        category = frontmatter.get("category", default_category)
        topic = frontmatter.get("topic", default_category)

        sections = self.split_into_sections(content)
        all_chunks: List[ChunkMetadata] = []

        chunk_counter = 0
        for sec in sections:
            heading = sec["heading"]
            text_blocks = self.chunk_section_text(sec["text"])

            for block in text_blocks:
                chunk_id = f"{doc_id}_{chunk_counter:04d}"
                chunk_counter += 1

                chunk_obj = ChunkMetadata(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    source_title=title,
                    source_url=source_url,
                    postgresql_version=version,
                    section_heading=heading,
                    page_number=None,
                    document_type=document_type,
                    incident_category=category,
                    chunk_text=block,
                    extra_metadata={
                        "topic": topic,
                        "filename": filename,
                        "filepath": filepath,
                        "char_count": len(block),
                        "word_count": len(block.split())
                    }
                )
                all_chunks.append(chunk_obj)

        return all_chunks

    def process_directory(
        self,
        dir_path: str,
        document_type: str = "official_docs",
        default_category: str = "general"
    ) -> List[ChunkMetadata]:
        """Recursively scans a directory for markdown files and processes all into chunks."""
        chunks: List[ChunkMetadata] = []
        for root, _, files in os.walk(dir_path):
            category = os.path.basename(root) if root != dir_path else default_category
            for file in sorted(files):
                if file.endswith((".md", ".markdown", ".txt")):
                    full_path = os.path.join(root, file)
                    doc_chunks = self.process_file(
                        filepath=full_path,
                        default_category=category,
                        document_type=document_type
                    )
                    chunks.extend(doc_chunks)
        return chunks
