import json

from src.extraction.models import Excerpt, Theme
from src.extraction.themes import _merge_chunk_themes, extract_themes
from src.llm import ModelConfig


class _FakeClient:
    def __init__(self, raw: str):
        self.raw = raw
        self.user_inputs: list[str] = []

    def generate_once(self, **kwargs) -> str:
        self.user_inputs.append(kwargs["user"])
        return self.raw


def test_extract_themes_normalizes_missing_relevance_and_null_context():
    raw = json.dumps(
        {
            "coverage": {
                "total_paragraphs": 4,
                "excluded_paragraphs": 1,
                "covered_paragraphs": 3,
                "coverage_ratio": 1.0,
                "sections_with_zero_themes": 0,
                "excluded_paragraphs_notes": [],
                "failed_gates": [],
                "audit_notes": "",
            },
            "themes": [
                {
                    "label": "Fed policy outlook",
                    "scope": "Macro",
                    "section_anchor": "Market views",
                    "excerpts": [
                        {"text": "The Fed is likely to stay on hold."},
                        {"text": "Markets still price too much easing."},
                    ],
                    "primary_category": "Rates",
                    "classification": "Forecast",
                    "evidence_count": 2,
                    "strength": "Primary",
                    "directionality": None,
                    "confidence": "High",
                    "context": None,
                }
            ],
            "excluded_topics": [],
        }
    )

    themes = extract_themes(
        client=_FakeClient(raw),
        text="dummy text",
        config=ModelConfig(provider="groq", model="openai/gpt-oss-120b"),
    )

    assert len(themes) == 1
    assert themes[0].relevance == ["Rates"]
    assert themes[0].context == ""


def test_extract_themes_normalizes_string_excerpts_and_skips_string_theme_entries():
    raw = json.dumps(
        {
            "themes": [
                {
                    "label": "Treasury positioning",
                    "excerpts": [
                        "Positioning is crowded in the front end.",
                        {"text": "The market is leaning long duration."},
                    ],
                    "relevance": ["Rates"],
                    "classification": "Description",
                    "strength": "Primary",
                    "confidence": "High",
                    "context": "Desk commentary",
                },
                "stray theme string",
            ]
        }
    )

    themes = extract_themes(
        client=_FakeClient(raw),
        text="dummy text",
        config=ModelConfig(provider="deepinfra", model="MiniMaxAI/MiniMax-M2.5"),
    )

    assert len(themes) == 1
    assert themes[0].label == "Treasury positioning"
    assert [excerpt.text for excerpt in themes[0].excerpts] == [
        "Positioning is crowded in the front end.",
        "The market is leaning long duration.",
    ]


class _ChunkAwareThemesClient:
    def __init__(self):
        self.user_inputs: list[str] = []

    def generate_once(self, **kwargs) -> str:
        user = kwargs["user"]
        self.user_inputs.append(user)
        themes = []
        if "ALPHA-SECTION" in user:
            themes.append(
                {
                    "label": "Fed patience",
                    "excerpts": [{"text": "The Fed can stay patient."}],
                    "relevance": ["Rates"],
                    "classification": "Forecast",
                    "strength": "Primary",
                    "confidence": "High",
                    "context": "Front-end repricing slows.",
                }
            )
        if "BETA-SECTION" in user:
            themes.append(
                {
                    "label": "Dollar consolidation",
                    "excerpts": [{"text": "USD strength is losing momentum."}],
                    "relevance": ["FX"],
                    "classification": "Opinion",
                    "strength": "Secondary",
                    "confidence": "Medium",
                    "context": "Broad dollar rally stalls.",
                }
            )
        return json.dumps({"themes": themes})


def test_extract_themes_chunks_oversized_input_and_merges_results():
    client = _ChunkAwareThemesClient()
    alpha_block = ("ALPHA-SECTION\n" + ("Rates paragraph.\n\n" * 5_500))
    beta_block = ("BETA-SECTION\n" + ("FX paragraph.\n\n" * 5_500))
    oversized_text = alpha_block + beta_block

    themes = extract_themes(
        client=client,
        text=oversized_text,
        config=ModelConfig(provider="deepinfra", model="MiniMaxAI/MiniMax-M2.5"),
    )

    assert len(client.user_inputs) > 1
    assert all(len(user_input) <= 12_000 for user_input in client.user_inputs)
    assert any("ALPHA-SECTION" in user_input for user_input in client.user_inputs)
    assert any("BETA-SECTION" in user_input for user_input in client.user_inputs)
    assert {theme.label for theme in themes} == {"Fed patience", "Dollar consolidation"}


class _BudgetLimitedThemesClient:
    def __init__(self, max_chars: int):
        self.max_chars = max_chars
        self.user_inputs: list[str] = []

    def generate_once(self, **kwargs) -> str:
        user = kwargs["user"]
        self.user_inputs.append(user)
        if len(user) > self.max_chars:
            raise RuntimeError("Error code: 413 - Request too large for model")

        themes = []
        if "ALPHA-SPLIT" in user:
            themes.append(
                {
                    "label": "Inflation persistence",
                    "excerpts": [{"text": "Inflation remains sticky in the services basket."}],
                    "relevance": ["Rates"],
                    "classification": "Forecast",
                    "strength": "Primary",
                    "confidence": "High",
                    "context": "Sticky services inflation delays easing.",
                }
            )
        if "BETA-SPLIT" in user:
            themes.append(
                {
                    "label": "Growth deceleration",
                    "excerpts": [{"text": "Growth indicators are rolling over at the margin."}],
                    "relevance": ["Macro"],
                    "classification": "Description",
                    "strength": "Secondary",
                    "confidence": "Medium",
                    "context": "Growth momentum is slowing as demand cools.",
                }
            )
        return json.dumps({"themes": themes})


def test_extract_themes_retries_with_smaller_chunks_on_request_too_large():
    client = _BudgetLimitedThemesClient(max_chars=5_000)
    alpha_block = "ALPHA-SPLIT\n" + ("Rates paragraph.\n\n" * 1_500)
    beta_block = "BETA-SPLIT\n" + ("Macro paragraph.\n\n" * 1_500)

    themes = extract_themes(
        client=client,
        text=alpha_block + beta_block,
        config=ModelConfig(provider="groq", model="openai/gpt-oss-120b"),
    )

    assert len(client.user_inputs) > 2
    assert any(len(user_input) > 5_000 for user_input in client.user_inputs)
    assert any(len(user_input) <= 5_000 for user_input in client.user_inputs)
    assert {theme.label for theme in themes} == {"Inflation persistence", "Growth deceleration"}


def test_merge_chunk_themes_preserves_top_twelve_ranked_deterministically():
    themes = [
        Theme(
            label=f"Theme {idx:02d}",
            excerpts=[Excerpt(text=f"Evidence {idx}")],
            relevance=["Rates"],
            classification="Forecast",
            mention_count=idx,
            strength="Primary",
            confidence="High",
            context=f"Context {idx}",
        )
        for idx in range(1, 14)
    ]

    ranked = _merge_chunk_themes([themes])

    assert len(ranked) == 12
    assert [theme.label for theme in ranked] == [
        "Theme 13",
        "Theme 12",
        "Theme 11",
        "Theme 10",
        "Theme 09",
        "Theme 08",
        "Theme 07",
        "Theme 06",
        "Theme 05",
        "Theme 04",
        "Theme 03",
        "Theme 02",
    ]
