import json

from src.extraction.trades import extract_trades
from src.llm import ModelConfig


class _FakeLLMClient:
    def __init__(self, raw: str):
        self.raw = raw
        self.response_formats: list[dict | None] = []
        self.user_inputs: list[str] = []

    def generate_once(self, **kwargs) -> str:
        self.response_formats.append(kwargs.get("response_format"))
        self.user_inputs.append(kwargs["user"])
        return self.raw


def test_extract_trades_passes_response_format_and_accepts_wrapped_payload():
    raw = json.dumps(
        {
            "trades": [
                {
                    "text": "Maintain long 3Y USTs",
                    "exposure": "Medium",
                    "timeframe": "weeks",
                    "conviction": "High",
                    "rationale": "Labor data weakens the case for higher front-end yields.",
                    "trigger_levels": None,
                }
            ]
        }
    )
    client = _FakeLLMClient(raw)

    trades = extract_trades(
        client=client,
        text="dummy text",
        config=ModelConfig(
            provider="deepinfra",
            model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        ),
    )

    assert len(trades) == 1
    assert trades[0].text == "Maintain long 3Y USTs"
    assert trades[0].conviction == "High"
    assert client.response_formats == [
        {
            "type": "json_schema",
            "json_schema": {
                "name": "trades_response",
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "trades": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": True,
                                "properties": {
                                    "text": {"type": "string"},
                                    "exposure": {"type": "string"},
                                    "timeframe": {"type": "string"},
                                    "conviction": {"type": "string"},
                                    "rationale": {"type": "string"},
                                    "trigger_levels": {"type": ["string", "null"]},
                                },
                                "required": [
                                    "text",
                                    "exposure",
                                    "timeframe",
                                    "conviction",
                                    "rationale",
                                    "trigger_levels",
                                ],
                            },
                        }
                    },
                    "required": ["trades"],
                },
            },
        }
    ]


class _ChunkAwareTradesClient:
    def __init__(self):
        self.user_inputs: list[str] = []
        self.response_formats: list[dict | None] = []

    def generate_once(self, **kwargs) -> str:
        user = kwargs["user"]
        self.user_inputs.append(user)
        self.response_formats.append(kwargs.get("response_format"))
        trades = []
        if "ALPHA-TRADE" in user:
            trades.append(
                {
                    "text": "Receive front-end USD swaps",
                    "exposure": "Medium",
                    "timeframe": "weeks",
                    "conviction": "High",
                    "rationale": "Front-end rates should drift lower as data softens.",
                    "trigger_levels": None,
                }
            )
        if "BETA-TRADE" in user:
            trades.append(
                {
                    "text": "Fade broad USD rallies",
                    "exposure": "Small",
                    "timeframe": "days",
                    "conviction": "Medium",
                    "rationale": "Momentum is stretched and positioning is cleaner.",
                    "trigger_levels": "DXY 108",
                }
            )
        return json.dumps({"trades": trades})


def test_extract_trades_chunks_oversized_input_and_merges_results():
    client = _ChunkAwareTradesClient()
    alpha_block = ("ALPHA-TRADE\n" + ("Rates trade paragraph.\n\n" * 5_500))
    beta_block = ("BETA-TRADE\n" + ("FX trade paragraph.\n\n" * 5_500))
    oversized_text = alpha_block + beta_block

    trades = extract_trades(
        client=client,
        text=oversized_text,
        config=ModelConfig(
            provider="deepinfra",
            model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        ),
    )

    assert len(client.user_inputs) > 1
    assert all(len(user_input) <= 90_000 for user_input in client.user_inputs)
    assert any("ALPHA-TRADE" in user_input for user_input in client.user_inputs)
    assert any("BETA-TRADE" in user_input for user_input in client.user_inputs)
    assert {trade.text for trade in trades} == {
        "Receive front-end USD swaps",
        "Fade broad USD rallies",
    }


def test_extract_trades_filters_forecasts_and_fuzzy_dedupes_recommendations():
    raw = json.dumps(
        {
            "trades": [
                {
                    "text": "Delay Fed rate cut expectations to December 2026",
                    "exposure": "Medium",
                    "timeframe": "months",
                    "conviction": "High",
                    "rationale": "Inflation remains too high for near-term easing.",
                    "trigger_levels": None,
                },
                {
                    "text": "Hold long 30Y EU vs. swap",
                    "exposure": "Medium",
                    "timeframe": "months",
                    "conviction": "High",
                    "rationale": "Long-end EU debt remains attractive versus swaps.",
                    "trigger_levels": None,
                },
                {
                    "text": "Keep overweight 30Y EU vs. swap",
                    "exposure": "Large",
                    "timeframe": "months",
                    "conviction": "High",
                    "rationale": (
                        "Strategic overweight EU position driven by low near-term issuance risk "
                        "and attractive relative value in long-end EU debt versus swaps."
                    ),
                    "trigger_levels": None,
                },
            ]
        }
    )
    client = _FakeLLMClient(raw)

    trades = extract_trades(
        client=client,
        text="dummy text",
        config=ModelConfig(
            provider="deepinfra",
            model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        ),
    )

    assert len(trades) == 1
    assert trades[0].text == "Keep overweight 30Y EU vs. swap"
    assert trades[0].exposure == "Large"
    assert "Strategic overweight" in trades[0].rationale


def test_extract_trades_caps_ranked_results_at_ten():
    raw = json.dumps(
        {
            "trades": [
                {
                    "text": f"Maintain long {idx}Y UST swap",
                    "exposure": "Medium",
                    "timeframe": "weeks",
                    "conviction": "High",
                    "rationale": f"Trade {idx} has explicit support.",
                    "trigger_levels": None,
                }
                for idx in range(12)
            ]
        }
    )
    client = _FakeLLMClient(raw)

    trades = extract_trades(
        client=client,
        text="dummy text",
        config=ModelConfig(
            provider="deepinfra",
            model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        ),
    )

    assert len(trades) == 10
