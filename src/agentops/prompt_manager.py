"""Versioned Prompt Management and Artifact Loader."""
import hashlib
import os
import yaml
from typing import Any, Dict, Optional
from src.agentops.logging import app_logger

class PromptTemplate:
    """Represents a specific immutable prompt version."""
    def __init__(self, version: str, name: str, description: str, system_prompt: str, user_template: str, raw_content: str):
        self.version = version
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.user_template = user_template
        self.raw_content = raw_content
        self.template_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()[:12]

    def format_user_prompt(self, **kwargs: Any) -> str:
        """Render user template with provided variables."""
        return self.user_template.format(**kwargs)

    def to_metadata(self) -> Dict[str, Any]:
        """Return execution metadata associated with this prompt."""
        return {
            "prompt_version": self.version,
            "prompt_name": self.name,
            "template_hash": self.template_hash,
            "description": self.description
        }

class PromptManager:
    """Manages loading, retrieval, and version switching of prompt templates."""
    def __init__(self, prompts_dir: str = "./prompts", default_version: str = "v1.1.0"):
        self.prompts_dir = prompts_dir
        self.default_version = default_version
        self._prompts: Dict[str, PromptTemplate] = {}
        self.load_all_prompts()

    def load_all_prompts(self):
        """Discovers and parses all YAML prompt definitions in the prompts directory."""
        if not os.path.exists(self.prompts_dir):
            app_logger.warning(f"Prompts directory '{self.prompts_dir}' does not exist.")
            return

        for filename in os.listdir(self.prompts_dir):
            if filename.endswith(".yaml") or filename.endswith(".yml"):
                filepath = os.path.join(self.prompts_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        raw = f.read()
                        data = yaml.safe_load(raw)

                    version = data.get("version")
                    if version:
                        self._prompts[version] = PromptTemplate(
                            version=version,
                            name=data.get("name", filename),
                            description=data.get("description", ""),
                            system_prompt=data.get("system_prompt", ""),
                            user_template=data.get("user_template", "{input}"),
                            raw_content=raw
                        )
                        app_logger.info(f"Loaded prompt version '{version}' ({data.get('name')})")
                except Exception as e:
                    app_logger.error(f"Failed to load prompt file {filepath}: {e}")

    def get_prompt(self, version: Optional[str] = None) -> PromptTemplate:
        """Retrieves a specific prompt version or falls back to default."""
        ver = version or self.default_version
        if ver in self._prompts:
            return self._prompts[ver]
        
        # If requested version not found, fallback to any available
        if self._prompts:
            fallback_ver = next(iter(self._prompts.keys()))
            app_logger.warning(f"Prompt version '{ver}' not found. Falling back to '{fallback_ver}'.")
            return self._prompts[fallback_ver]

        raise ValueError(f"No prompt templates loaded from '{self.prompts_dir}'.")

    def list_versions(self) -> Dict[str, str]:
        """Returns mapping of loaded versions to their descriptive names."""
        return {v: p.name for v, p in self._prompts.items()}

prompt_manager = PromptManager()
