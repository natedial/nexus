"""Map a served model name to its family, for independence checks."""

from __future__ import annotations

_FAMILY_PREFIXES = (
    (("gpt", "o1", "o3", "o4", "codex", "chatgpt"), "openai-gpt"),
    (("claude",), "anthropic-claude"),
    (("gemini",), "google-gemini"),
    (("llama", "meta-llama"), "meta-llama"),
    (("mistral", "mixtral"), "mistral"),
    (("qwen",), "qwen"),
    (("deepseek",), "deepseek"),
    (("grok",), "xai-grok"),
)


def model_family(model: str | None) -> str | None:
    """Return a known family, or None. Unknown models never count as independent."""
    name = (model or "").strip().lower()
    for prefixes, family in _FAMILY_PREFIXES:
        if name.startswith(prefixes):
            return family
    return None
