"""Tests for Prompt Version Management and Artifact Discovery."""
from src.agentops.prompt_manager import prompt_manager

def test_prompt_manager_loads_versions():
    versions = prompt_manager.list_versions()
    assert "v1.0.0" in versions
    assert "v1.1.0" in versions

def test_prompt_template_formatting():
    p1 = prompt_manager.get_prompt("v1.0.0")
    formatted = p1.format_user_prompt(
        alert_payload="DISK ALERT",
        on_call_notes="INVESTIGATING",
        retrieved_context="DOCS"
    )
    assert "DISK ALERT" in formatted
    assert "INVESTIGATING" in formatted
    assert "DOCS" in formatted

    metadata = p1.to_metadata()
    assert metadata["prompt_version"] == "v1.0.0"
    assert "template_hash" in metadata
    assert len(metadata["template_hash"]) > 0

def test_prompt_manager_version_fallback():
    # Non-existent version falls back gracefully
    p_fallback = prompt_manager.get_prompt("v9.9.9")
    assert p_fallback is not None
    assert p_fallback.version in ["v1.0.0", "v1.1.0"]
