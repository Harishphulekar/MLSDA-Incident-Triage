"""PostgreSQL 16 Official Documentation Corpus Ingestor.

Downloads, normalizes, and packages official PostgreSQL 16 documentation
across 9 incident-response topics into structured markdown with rich metadata.
"""
import os
import re
import json
import hashlib
import time
import urllib.request
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

POSTGRES_VERSION = "16"
BASE_URL = f"https://www.postgresql.org/docs/{POSTGRES_VERSION}/"

DOC_SOURCES = [
    # 1. Monitoring and Statistics
    {
        "topic": "monitoring",
        "doc_id": "pg16_monitoring_stats",
        "title": "PostgreSQL 16: The Statistics Collector & Activity Views",
        "url": f"{BASE_URL}monitoring-stats.html",
        "filename": "monitoring_stats.md",
        "category": "monitoring"
    },
    {
        "topic": "monitoring",
        "doc_id": "pg16_monitoring_locks",
        "title": "PostgreSQL 16: Viewing Locks and Concurrency",
        "url": f"{BASE_URL}monitoring-locks.html",
        "filename": "monitoring_locks.md",
        "category": "monitoring"
    },
    # 2. WAL (Write-Ahead Logging)
    {
        "topic": "wal",
        "doc_id": "pg16_wal_intro",
        "title": "PostgreSQL 16: Write-Ahead Logging (WAL) Architecture",
        "url": f"{BASE_URL}wal-intro.html",
        "filename": "wal_intro.md",
        "category": "wal"
    },
    {
        "topic": "wal",
        "doc_id": "pg16_wal_config",
        "title": "PostgreSQL 16: WAL Configuration and Checkpoints",
        "url": f"{BASE_URL}wal-configuration.html",
        "filename": "wal_configuration.md",
        "category": "wal"
    },
    {
        "topic": "wal",
        "doc_id": "pg16_continuous_archiving",
        "title": "PostgreSQL 16: Continuous Archiving & WAL Retention",
        "url": f"{BASE_URL}continuous-archiving.html",
        "filename": "continuous_archiving.md",
        "category": "wal"
    },
    # 3. Replication
    {
        "topic": "replication",
        "doc_id": "pg16_warm_standby",
        "title": "PostgreSQL 16: High Availability, Load Balancing, and Replication",
        "url": f"{BASE_URL}warm-standby.html",
        "filename": "warm_standby_replication.md",
        "category": "replication"
    },
    {
        "topic": "replication",
        "doc_id": "pg16_runtime_config_replication",
        "title": "PostgreSQL 16: Replication Configuration & Timeouts",
        "url": f"{BASE_URL}runtime-config-replication.html",
        "filename": "runtime_config_replication.md",
        "category": "replication"
    },
    # 4. Replication Slots
    {
        "topic": "replication",
        "doc_id": "pg16_view_pg_replication_slots",
        "title": "PostgreSQL 16: pg_replication_slots View and Slot Management",
        "url": f"{BASE_URL}view-pg-replication-slots.html",
        "filename": "view_pg_replication_slots.md",
        "category": "replication_slots"
    },
    # 5. Disk Space and Storage
    {
        "topic": "storage",
        "doc_id": "pg16_diskusage",
        "title": "PostgreSQL 16: Monitoring Disk Usage & Relation Sizing",
        "url": f"{BASE_URL}diskusage.html",
        "filename": "disk_usage.md",
        "category": "storage"
    },
    {
        "topic": "storage",
        "doc_id": "pg16_storage_file_layout",
        "title": "PostgreSQL 16: Database File Layout and WAL Storage",
        "url": f"{BASE_URL}storage-file-layout.html",
        "filename": "storage_file_layout.md",
        "category": "storage"
    },
    {
        "topic": "storage",
        "doc_id": "pg16_routine_vacuuming",
        "title": "PostgreSQL 16: Routine Vacuuming and Freezing (TXID Wraparound)",
        "url": f"{BASE_URL}routine-vacuuming.html",
        "filename": "routine_vacuuming.md",
        "category": "storage"
    },
    # 6. Connections and Connection Limits
    {
        "topic": "connections",
        "doc_id": "pg16_runtime_config_connection",
        "title": "PostgreSQL 16: Connection Settings and Limits",
        "url": f"{BASE_URL}runtime-config-connection.html",
        "filename": "runtime_config_connection.md",
        "category": "connections"
    },
    {
        "topic": "connections",
        "doc_id": "pg16_client_authentication",
        "title": "PostgreSQL 16: Client Authentication and Connection Management",
        "url": f"{BASE_URL}client-authentication.html",
        "filename": "client_authentication.md",
        "category": "connections"
    },
    # 7. Database Performance
    {
        "topic": "performance",
        "doc_id": "pg16_explicit_locking",
        "title": "PostgreSQL 16: Explicit Locking and Deadlock Detection",
        "url": f"{BASE_URL}explicit-locking.html",
        "filename": "explicit_locking.md",
        "category": "performance"
    },
    {
        "topic": "performance",
        "doc_id": "pg16_using_explain",
        "title": "PostgreSQL 16: Using EXPLAIN for Query Execution Analysis",
        "url": f"{BASE_URL}using-explain.html",
        "filename": "using_explain.md",
        "category": "performance"
    },
    # 8. Configuration Parameters
    {
        "topic": "configuration",
        "doc_id": "pg16_runtime_config_resource",
        "title": "PostgreSQL 16: Resource Consumption (Memory & Buffer Pools)",
        "url": f"{BASE_URL}runtime-config-resource.html",
        "filename": "runtime_config_resource.md",
        "category": "configuration"
    },
    {
        "topic": "configuration",
        "doc_id": "pg16_config_setting",
        "title": "PostgreSQL 16: Parameter Interaction and Configuration Reload",
        "url": f"{BASE_URL}config-setting.html",
        "filename": "config_setting.md",
        "category": "configuration"
    },
    # 9. Backup and Recovery
    {
        "topic": "backup_recovery",
        "doc_id": "pg16_app_pgbasebackup",
        "title": "PostgreSQL 16: pg_basebackup Reference",
        "url": f"{BASE_URL}app-pgbasebackup.html",
        "filename": "app_pgbasebackup.md",
        "category": "backup_recovery"
    },
    {
        "topic": "backup_recovery",
        "doc_id": "pg16_backup_dump",
        "title": "PostgreSQL 16: SQL Dump (pg_dump / pg_dumpall)",
        "url": f"{BASE_URL}backup-dump.html",
        "filename": "backup_dump.md",
        "category": "backup_recovery"
    }
]

def html_to_clean_markdown(html_content: str, source_url: str, title: str) -> str:
    """Parses official PostgreSQL HTML and converts it into structured Markdown."""
    soup = BeautifulSoup(html_content, "html.parser")
    doc_content = soup.find(id="docContent")
    if not doc_content:
        doc_content = soup.body if soup.body else soup

    # Strip navigation headers, footers, scripts, and search widgets
    for el in doc_content.find_all(class_=["navheader", "navfooter", "toc"]):
        el.decompose()
    for el in doc_content.find_all(["script", "style", "nav", "svg"]):
        el.decompose()

    lines = []
    
    # Process elements recursively
    def process_node(node):
        if isinstance(node, str):
            text = node.strip()
            if text:
                return text
            return ""
        
        name = node.name.lower() if node.name else ""

        if name in ["h1", "h2", "h3", "h4", "h5"]:
            heading_level = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5}.get(name, 2)
            prefix = "#" * heading_level
            heading_text = node.get_text(separator=" ").strip()
            # Remove trailing anchor symbol #
            heading_text = re.sub(r"\s*#$", "", heading_text).strip()
            return f"\n\n{prefix} {heading_text}\n\n"

        elif name == "pre" or "programlisting" in node.get("class", []):
            code_text = node.get_text()
            return f"\n```sql\n{code_text.strip()}\n```\n"

        elif name == "table":
            rows = []
            for tr in node.find_all("tr"):
                cols = [td.get_text(separator=" ").strip().replace("\n", " ") for td in tr.find_all(["th", "td"])]
                if cols:
                    rows.append(" | ".join(cols))
            if rows:
                header = rows[0]
                col_count = len(rows[0].split(" | "))
                sep = " | ".join(["---"] * col_count)
                table_md = f"\n| {header} |\n| {sep} |\n"
                for r in rows[1:]:
                    table_md += f"| {r} |\n"
                return table_md
            return ""

        elif name == "p":
            p_text = node.get_text(separator=" ").strip()
            if p_text:
                return f"\n\n{p_text}\n\n"
            return ""

        elif name in ["ul", "ol"]:
            items = []
            for li in node.find_all("li", recursive=False):
                li_text = li.get_text(separator=" ").strip()
                if li_text:
                    items.append(f"- {li_text}")
            if items:
                return "\n" + "\n".join(items) + "\n"
            return ""

        else:
            # Process children
            out = []
            for child in node.children:
                res = process_node(child)
                if res:
                    out.append(res)
            return "".join(out)

    markdown_body = process_node(doc_content)
    # Clean up excessive newlines
    markdown_body = re.sub(r"\n{3,}", "\n\n", markdown_body).strip()

    return markdown_body

class CorpusIngestor:
    """Manages downloading and structuring the official PostgreSQL 16 knowledge base."""
    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir
        self.corpus_dir = os.path.join(base_dir, "data", "corpus")
        self.metadata_dir = os.path.join(base_dir, "data", "metadata")
        self.manifest_file = os.path.join(self.metadata_dir, "corpus_manifest.json")

    def ensure_directories(self):
        for source in DOC_SOURCES:
            topic_dir = os.path.join(self.corpus_dir, source["topic"])
            os.makedirs(topic_dir, exist_ok=True)
        os.makedirs(self.metadata_dir, exist_ok=True)

    def fetch_document(self, source: Dict[str, Any]) -> Dict[str, Any]:
        """Downloads document HTML, converts to markdown, and writes to disk."""
        url = source["url"]
        topic = source["topic"]
        filename = source["filename"]
        target_path = os.path.join(self.corpus_dir, topic, filename)

        headers = {
            "User-Agent": "PostgreSQL-Runbook-Assistant-RAG/1.0 (ML System Design Project; Academic Ingestion)"
        }
        req = urllib.request.Request(url, headers=headers)
        
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html_bytes = resp.read()
                html_text = html_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            raise RuntimeError(f"Failed to fetch {url}: {e}")

        # Convert to clean markdown
        cleaned_markdown = html_to_clean_markdown(html_text, url, source["title"])

        # Format header with traceable metadata
        header = f"""---
document_id: {source["doc_id"]}
title: "{source["title"]}"
source_url: {source["url"]}
postgresql_version: "{POSTGRES_VERSION}"
topic: {source["topic"]}
category: {source["category"]}
retrieved_date: "{time.strftime('%Y-%m-%d')}"
---

# {source["title"]}

Source: [{source["url"]}]({source["url"]})  
PostgreSQL Version: {POSTGRES_VERSION}  
Incident Category: {source["category"]}

"""
        full_content = header + cleaned_markdown

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(full_content)

        file_hash = hashlib.sha256(full_content.encode("utf-8")).hexdigest()
        byte_size = len(full_content.encode("utf-8"))

        return {
            "document_id": source["doc_id"],
            "title": source["title"],
            "topic": source["topic"],
            "category": source["category"],
            "filename": filename,
            "relative_path": os.path.join("data", "corpus", topic, filename),
            "source_url": source["url"],
            "postgresql_version": POSTGRES_VERSION,
            "sha256": file_hash,
            "size_bytes": byte_size,
            "line_count": full_content.count("\n")
        }

    def ingest_all(self, delay: float = 0.5) -> List[Dict[str, Any]]:
        """Ingests all configured official PostgreSQL 16 documentation."""
        self.ensure_directories()
        manifest_entries = []

        print(f"Starting ingestion of {len(DOC_SOURCES)} official PostgreSQL {POSTGRES_VERSION} documents...")
        for idx, source in enumerate(DOC_SOURCES, 1):
            print(f"[{idx}/{len(DOC_SOURCES)}] Fetching: {source['title']} ({source['url']})")
            entry = self.fetch_document(source)
            manifest_entries.append(entry)
            time.sleep(delay)

        manifest = {
            "postgresql_version": POSTGRES_VERSION,
            "ingested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_documents": len(manifest_entries),
            "documents": manifest_entries
        }

        with open(self.manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        print(f"Ingestion complete. Manifest saved to {self.manifest_file}")
        return manifest_entries

if __name__ == "__main__":
    ingestor = CorpusIngestor(base_dir=".")
    ingestor.ingest_all()
