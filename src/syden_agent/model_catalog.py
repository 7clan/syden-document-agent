"""Small, read-only model catalogs for the two providers with model-list APIs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ModelOption:
    id: str
    name: str
    tool_support: bool | None  # None means the fallback ID was not checked for this account.


@dataclass(frozen=True)
class ModelCatalog:
    models: tuple[ModelOption, ...]
    unsupported: tuple[str, ...] = ()
    source: str = "live"
    warning: str = ""


FALLBACKS = {
    "groq": (
        ("openai/gpt-oss-20b", "GPT-OSS 20B"),
        ("openai/gpt-oss-120b", "GPT-OSS 120B"),
        ("qwen/qwen3.8-27b", "Qwen 3.8 27B"),
    ),
    "ollama_cloud": (
        ("gpt-oss:20b", "GPT-OSS 20B"),
        ("gpt-oss:120b", "GPT-OSS 120B"),
        ("gemma4:31b", "Gemma 4 31B"),
        ("nemotron-3-nano:30b", "Nemotron 3 Nano 30B"),
        ("nemotron-3-super", "Nemotron 3 Super"),
        ("nemotron-3-ultra", "Nemotron 3 Ultra"),
        ("beam", "Beam"),
    ),
}


def fallback_catalog(provider: str, warning: str = "") -> ModelCatalog:
    return ModelCatalog(tuple(ModelOption(model_id, name, None)
                              for model_id, name in FALLBACKS.get(provider, ())),
                        source="fallback", warning=warning)


def _request_json(url: str, api_key: str) -> dict:
    request = Request(url, headers={"Authorization": f"Bearer {api_key}",
                                    "User-Agent": "SYDEN-Document-Agent"})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def _friendly_name(model_id: str, supplied: str = "") -> str:
    if supplied and supplied != model_id:
        return supplied
    names = dict(FALLBACKS["groq"] + FALLBACKS["ollama_cloud"])
    return names.get(model_id, model_id)


def _ordered(provider: str, models: list[ModelOption]) -> tuple[ModelOption, ...]:
    preferred = {model_id: index for index, (model_id, _) in
                 enumerate(FALLBACKS[provider])}
    return tuple(sorted(models, key=lambda item: (preferred.get(item.id, 999), item.id)))


def parse_groq_models(payload: dict) -> ModelCatalog:
    """Groq supplies `supported_features`, so require explicit local tool support."""
    compatible: list[ModelOption] = []
    unsupported: list[str] = []
    for item in payload.get("data", []):
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id or item.get("active") is False:
            continue
        features = item.get("supported_features") or []
        input_modes = item.get("input_modalities") or []
        output_modes = item.get("output_modalities") or []
        if ("tools" in features and "text" in input_modes and "text" in output_modes
                and not model_id.startswith("groq/compound")
                and not any(term in model_id.lower() for term in
                            ("safeguard", "guard", "moderation"))):
            compatible.append(ModelOption(model_id, _friendly_name(
                model_id, item.get("name") or ""), True))
        else:
            unsupported.append(model_id)
    return ModelCatalog(_ordered("groq", compatible),
                        tuple(sorted(unsupported)))


def parse_ollama_models(payload: dict) -> ModelCatalog:
    """Direct cloud tags expose exact API IDs and a `tools` capability list."""
    compatible: list[ModelOption] = []
    unsupported: list[str] = []
    for item in payload.get("models", []):
        model_id = item.get("model") or item.get("name")
        if not isinstance(model_id, str) or not model_id:
            continue
        capabilities = item.get("capabilities") or []
        if "tools" in capabilities and "completion" in capabilities:
            compatible.append(ModelOption(model_id, _friendly_name(model_id), True))
        else:
            unsupported.append(model_id)
    return ModelCatalog(_ordered("ollama_cloud", compatible),
                        tuple(sorted(unsupported)))


def discover_models(provider: str, api_key: str) -> ModelCatalog:
    """Use official listing endpoints; never surface response bodies or keys on failure."""
    if not api_key:
        return fallback_catalog(provider, "Add the provider API key to discover models.")
    urls = {"groq": "https://api.groq.com/openai/v1/models",
            "ollama_cloud": "https://ollama.com/api/tags"}
    if provider not in urls:
        raise ValueError("Model discovery is only available for Groq and Ollama Cloud")
    try:
        payload = _request_json(urls[provider], api_key)
        if not isinstance(payload, dict):
            raise TypeError("Model listing was not a JSON object")
        return (parse_groq_models(payload) if provider == "groq" else
                parse_ollama_models(payload))
    except Exception:  # noqa: BLE001 - never display provider response data or credentials
        return fallback_catalog(provider, "Model listing unavailable. Showing fallback IDs; "
                                "availability and tool calling need a live smoke test.")
