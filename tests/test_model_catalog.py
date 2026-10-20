"""Provider model lists are filtered by actual tool capability metadata."""
from syden_agent import model_catalog as catalog


def test_groq_discovers_additional_text_tool_models_and_excludes_other_roles():
    payload = {"data": [
        {"id": "openai/gpt-oss-20b", "name": "GPT OSS 20B", "active": True,
         "input_modalities": ["text"], "output_modalities": ["text"],
         "supported_features": ["tools", "structured_outputs"]},
        {"id": "qwen/new-model", "active": True,
         "input_modalities": ["text", "image"], "output_modalities": ["text"],
         "supported_features": ["tools"]},
        {"id": "whisper-large-v3", "active": True,
         "input_modalities": ["audio"], "output_modalities": ["text"]},
        {"id": "meta-llama/prompt-guard", "active": True,
         "input_modalities": ["text"], "output_modalities": ["text"],
         "supported_features": ["tools"]},
        {"id": "retired", "active": False, "input_modalities": ["text"],
         "output_modalities": ["text"], "supported_features": ["tools"]},
    ]}
    found = catalog.parse_groq_models(payload)
    assert [model.id for model in found.models] == [
        "openai/gpt-oss-20b", "qwen/new-model"]
    assert "whisper-large-v3" in found.unsupported
    assert "meta-llama/prompt-guard" in found.unsupported
    assert "retired" not in found.unsupported
    assert all(model.tool_support is True for model in found.models)


def test_ollama_uses_exact_direct_api_ids_and_capabilities():
    payload = {"models": [
        {"model": "gpt-oss:20b", "capabilities": ["completion", "tools"]},
        {"model": "gemma4:31b", "capabilities": ["completion", "tools", "vision"]},
        {"model": "beam", "capabilities": ["completion", "tools", "thinking"]},
        {"model": "embedding-only", "capabilities": ["embedding"]},
        {"model": "no-tool-chat", "capabilities": ["completion"]},
    ]}
    found = catalog.parse_ollama_models(payload)
    assert [model.id for model in found.models] == ["gpt-oss:20b", "gemma4:31b", "beam"]
    assert "embedding-only" in found.unsupported
    assert "no-tool-chat" in found.unsupported
    assert found.models[0].name == "GPT-OSS 20B"


def test_listing_failure_uses_fallback_but_valid_empty_list_does_not(monkeypatch):
    def fail(*_args):
        raise RuntimeError("sensitive provider response")

    monkeypatch.setattr(catalog, "_request_json", fail)
    fallback = catalog.discover_models("ollama_cloud", "synthetic-key")
    assert fallback.source == "fallback"
    assert "sensitive provider response" not in fallback.warning
    assert {model.id for model in fallback.models} >= {
        "gpt-oss:20b", "gpt-oss:120b", "gemma4:31b", "nemotron-3-nano:30b",
        "nemotron-3-super", "nemotron-3-ultra", "beam"}
    assert all(model.tool_support is None for model in fallback.models)
    monkeypatch.setattr(catalog, "_request_json", lambda *_args: {"models": []})
    empty = catalog.discover_models("ollama_cloud", "synthetic-key")
    assert empty.source == "live"
    assert empty.models == ()
