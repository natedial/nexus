"""Reusable stage-one model profiles for live comparison and tuning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .llm import ModelConfig


@dataclass(frozen=True)
class Stage1Profile:
    """A tuned stage-one request profile for one model."""

    name: str
    provider: Literal["openai", "deepinfra"]
    model: str
    max_tokens: int
    request_timeout_seconds: float
    max_retries: int = 0
    response_format: dict[str, Any] | None = None
    drop_response_format_on_retry: bool = False
    tool_choice: str | None = None
    reasoning_effort: str | None = None
    prompt_profile: Literal["full", "lean", "minimal"] = "full"
    throughline_count: int = 0
    max_key_insight_words: int = 0
    max_supporting_themes: int = 0
    max_supporting_trades: int = 0
    payload_theme_limit: int = 0
    payload_trade_limit: int = 0

    def to_model_config(self) -> ModelConfig:
        """Convert this profile into a request config."""
        return ModelConfig(
            provider=self.provider,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0,
            request_timeout_seconds=self.request_timeout_seconds,
            max_retries=self.max_retries,
            response_format=self.response_format,
            drop_response_format_on_retry=self.drop_response_format_on_retry,
            tool_choice=self.tool_choice,
            reasoning_effort=self.reasoning_effort,
        )


def _strength_score(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    return {
        "primary": 3,
        "secondary": 2,
        "tertiary": 1,
    }.get(normalized, 0)


def _confidence_score(value: Any) -> int:
    normalized = str(value or "").strip().lower()
    return {
        "high": 3,
        "medium": 2,
        "low": 1,
    }.get(normalized, 0)


def _sort_payload_items(items: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Rank payload items so caps preserve the densest evidence first."""
    if kind == "themes":
        return sorted(
            items,
            key=lambda item: (
                _strength_score(item.get("strength")),
                _confidence_score(item.get("confidence")),
                int(item.get("mention_count") or 0),
                len(str(item.get("context") or "")),
            ),
            reverse=True,
        )

    return sorted(
        items,
        key=lambda item: (
            _confidence_score(item.get("conviction")),
            len(str(item.get("text") or "")),
            len(str(item.get("rationale") or "")),
        ),
        reverse=True,
    )


def apply_payload_limits(payload: dict[str, Any], profile: Stage1Profile) -> dict[str, Any]:
    """Optionally cap theme/trade counts for a given profile."""
    limited = dict(payload)

    themes = list(payload.get("themes", []))
    trades = list(payload.get("trades", []))

    if profile.payload_theme_limit > 0 and len(themes) > profile.payload_theme_limit:
        limited["themes"] = _sort_payload_items(themes, "themes")[: profile.payload_theme_limit]
    else:
        limited["themes"] = themes

    if profile.payload_trade_limit > 0 and len(trades) > profile.payload_trade_limit:
        limited["trades"] = _sort_payload_items(trades, "trades")[: profile.payload_trade_limit]
    else:
        limited["trades"] = trades

    return limited


def build_stage1_prompt(base_prompt: str, profile: Stage1Profile) -> str:
    """Build the effective stage-one prompt for this profile."""
    if profile.prompt_profile == "full":
        overrides = []
        if profile.throughline_count > 0:
            overrides.append(
                f"- Override the default range and return exactly {profile.throughline_count} through-lines."
            )
        if profile.max_key_insight_words > 0:
            overrides.append(
                "- Override the default key_insight budget and keep each key_insight "
                f"to {profile.max_key_insight_words} words or fewer."
            )
        if profile.max_supporting_themes > 0:
            overrides.append(
                f"- Keep supporting_themes to at most {profile.max_supporting_themes} items per through-line."
            )
        if profile.max_supporting_trades > 0:
            overrides.append(
                f"- Keep supporting_trades to at most {profile.max_supporting_trades} items per through-line."
            )
        if not overrides:
            return base_prompt
        return base_prompt + "\n\nTEST OVERRIDES\n" + "\n".join(overrides)

    count = profile.throughline_count or (3 if profile.prompt_profile == "lean" else 2)
    insight_words = profile.max_key_insight_words or (85 if profile.prompt_profile == "lean" else 60)
    theme_cap = profile.max_supporting_themes or (4 if profile.prompt_profile == "lean" else 3)
    trade_cap = profile.max_supporting_trades or 1

    if profile.prompt_profile == "lean":
        return f"""You are a cross-document macro and rates synthesizer.

Task:
- Find the dominant market beliefs across the supplied themes and trades.
- Prioritize consensus first, then the fracture lines inside that consensus.
- Include at most 1 contrarian through-line, and only if it attacks a shared market assumption.
- Ignore weak or orphaned ideas.

Return EXACTLY ONE JSON object with this schema:
{{
  "title": "short synthesis title",
  "through_lines": [
    {{
      "lead": "causal one-line finding",
      "supporting_sources": ["Source A", "Source B"],
      "consensus_level": "strong_consensus|moderate_consensus|mixed_views|contrarian",
      "consensus_anchor": "dominant market belief this line supports, fractures, or challenges",
      "supporting_themes": ["theme 1", "theme 2"],
      "supporting_trades": ["trade expression"],
      "key_insight": "short narrative synthesis"
    }}
  ]
}}

Rules:
- Return exactly {count} through-lines.
- At least half of the through-lines must be consensus-anchored.
- supporting_themes: at most {theme_cap}.
- supporting_trades: at most {trade_cap}.
- key_insight: at most {insight_words} words.
- Every through-line must explain the mechanism and the flip signpost.
- Use only the provided evidence. If support is weak, omit the idea.
- No markdown. No prose outside JSON."""

    return f"""Return EXACTLY ONE JSON object with:
- "title"
- "through_lines": exactly {count} items

Each through-line must contain:
- lead
- supporting_sources
- consensus_level
- consensus_anchor
- supporting_themes (max {theme_cap})
- supporting_trades (max {trade_cap})
- key_insight (max {insight_words} words)

Ranking:
1. consensus the market is pricing
2. fractures inside that consensus
3. one contrarian risk only if it breaks a shared assumption

Rules:
- consensus first
- concise wording
- use only supplied evidence
    - include mechanism and flip signpost
    - JSON only"""


def stage1_profile_from_model_config(name: str, config: ModelConfig) -> Stage1Profile:
    """Build a stage-one profile from config-backed model settings."""
    return Stage1Profile(
        name=name,
        provider=config.provider,
        model=config.model,
        max_tokens=config.max_tokens,
        request_timeout_seconds=config.request_timeout_seconds or 60.0,
        max_retries=config.max_retries,
        response_format=config.response_format,
        drop_response_format_on_retry=config.drop_response_format_on_retry,
        tool_choice=config.tool_choice,
        reasoning_effort=config.reasoning_effort,
        prompt_profile=config.prompt_profile,
        throughline_count=config.throughline_count,
        max_key_insight_words=config.max_key_insight_words,
        max_supporting_themes=config.max_supporting_themes,
        max_supporting_trades=config.max_supporting_trades,
        payload_theme_limit=config.payload_theme_limit,
        payload_trade_limit=config.payload_trade_limit,
    )


DEFAULT_STAGE1_PROFILES: dict[str, Stage1Profile] = {
    "gpt_5_mini_balanced": Stage1Profile(
        name="gpt_5_mini_balanced",
        provider="openai",
        model="gpt-5-mini",
        max_tokens=16000,
        request_timeout_seconds=90,
        prompt_profile="full",
    ),
    "gpt_5_mini_compact": Stage1Profile(
        name="gpt_5_mini_compact",
        provider="openai",
        model="gpt-5-mini",
        max_tokens=16000,
        request_timeout_seconds=90,
        prompt_profile="lean",
        throughline_count=4,
        max_key_insight_words=100,
        max_supporting_themes=4,
        max_supporting_trades=1,
        payload_theme_limit=24,
        payload_trade_limit=8,
    ),
    "kimi_k2_instruct_balanced": Stage1Profile(
        name="kimi_k2_instruct_balanced",
        provider="deepinfra",
        model="moonshotai/Kimi-K2-Instruct-0905",
        max_tokens=1400,
        request_timeout_seconds=90,
        max_retries=0,
        response_format={"type": "json_object"},
        drop_response_format_on_retry=False,
        prompt_profile="lean",
        throughline_count=4,
        max_key_insight_words=100,
        max_supporting_themes=4,
        max_supporting_trades=1,
        payload_theme_limit=24,
        payload_trade_limit=8,
    ),
    "kimi_k2_5_compact": Stage1Profile(
        name="kimi_k2_5_compact",
        provider="deepinfra",
        model="moonshotai/Kimi-K2.5",
        max_tokens=900,
        request_timeout_seconds=90,
        response_format={"type": "json_object"},
        drop_response_format_on_retry=True,
        prompt_profile="lean",
        throughline_count=3,
        max_key_insight_words=70,
        max_supporting_themes=4,
        max_supporting_trades=1,
        payload_theme_limit=16,
        payload_trade_limit=6,
    ),
    "minimax_m2_5_compact": Stage1Profile(
        name="minimax_m2_5_compact",
        provider="deepinfra",
        model="MiniMaxAI/MiniMax-M2.5",
        max_tokens=2200,
        request_timeout_seconds=90,
        response_format={"type": "json_object"},
        drop_response_format_on_retry=True,
        prompt_profile="lean",
        throughline_count=3,
        max_key_insight_words=80,
        max_supporting_themes=4,
        max_supporting_trades=1,
        payload_theme_limit=18,
        payload_trade_limit=6,
    ),
}


def get_stage1_profile(name: str) -> Stage1Profile:
    """Return a named stage-one profile."""
    if name not in DEFAULT_STAGE1_PROFILES:
        available = ", ".join(sorted(DEFAULT_STAGE1_PROFILES))
        raise KeyError(f"Unknown stage-one profile {name!r}. Available: {available}")
    return DEFAULT_STAGE1_PROFILES[name]


def list_stage1_profiles() -> list[str]:
    """List available stage-one profile names."""
    return list(DEFAULT_STAGE1_PROFILES)
