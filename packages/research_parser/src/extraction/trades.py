"""Extract trade ideas from financial research documents."""

import json
import re

import structlog
from tenacity import retry, stop_after_attempt, wait_random_exponential

from src.llm import LLMClient, ModelConfig

from .input_slicing import chunk_for_structured_extraction
from .json_utils import clean_json_response
from .models import Trade
from .prompts import get_trades_prompt
from .structured import generate_with_validation_fallback

logger = structlog.get_logger()

_TRADE_CONVICTION_RANK = {"High": 3, "Medium": 2, "Low": 1}
_TRADE_EXPOSURE_RANK = {"Large": 3, "Medium": 2, "Small": 1}
_TRADE_TIMEFRAME_RANK = {"months": 4, "weeks": 3, "days": 2, "intraday": 1}
_MAX_TRADES = 10
_NON_TRADE_PREFIXES = (
    "delay ",
    "expect ",
    "forecast ",
    "project ",
    "revise ",
    "push back ",
    "pull forward ",
)
_ACTIONABLE_TRADE_MARKERS = (
    "add ",
    "bear flattener",
    "bear steepener",
    "bull flattener",
    "bull steepener",
    "buy ",
    "call",
    "close ",
    "enter ",
    "exit ",
    "fade ",
    "flattener",
    "fly",
    "gamma",
    "hedge",
    "hold ",
    "keep ",
    "long ",
    "maintain ",
    "narrower",
    "option",
    "overweight",
    "pay ",
    "payer",
    "put",
    "receive ",
    "receiver",
    "scale ",
    "sell ",
    "short ",
    "spread",
    "stay ",
    "steepener",
    "straddle",
    "swap",
    "underweight",
)
_TRADE_DEDUPE_STOPWORDS = {
    "add",
    "and",
    "as",
    "bias",
    "close",
    "due",
    "express",
    "fade",
    "given",
    "hold",
    "keep",
    "long",
    "maintain",
    "overweight",
    "position",
    "recommend",
    "remain",
    "scale",
    "short",
    "stance",
    "stay",
    "strategic",
    "the",
    "to",
}

_TRADES_RESPONSE_SCHEMA = {
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



# _clean_json_response moved to json_utils.py


def _parse_trades_response(raw: str) -> list[Trade]:
    cleaned = clean_json_response(raw)
    data = json.loads(cleaned)
    if isinstance(data, dict) and "trades" in data:
        data = data["trades"]
    if not isinstance(data, list):
        data = [data] if data else []
    return [Trade(**t) for t in data]


def _normalize_trade_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _is_actionable_trade(trade: Trade) -> bool:
    text = _normalize_trade_key(trade.text)
    if not text:
        return False
    if text.startswith(_NON_TRADE_PREFIXES) and not any(
        marker in text for marker in _ACTIONABLE_TRADE_MARKERS
    ):
        return False
    return any(marker in text for marker in _ACTIONABLE_TRADE_MARKERS)


def _trade_similarity_tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+(?:x[a-z0-9]+)?", text.lower())
    return {word for word in words if len(word) > 1 and word not in _TRADE_DEDUPE_STOPWORDS}


def _is_near_duplicate_trade(first: Trade, second: Trade) -> bool:
    first_tokens = _trade_similarity_tokens(first.text)
    second_tokens = _trade_similarity_tokens(second.text)
    if len(first_tokens) < 3 or len(second_tokens) < 3:
        return False
    overlap = len(first_tokens & second_tokens)
    smaller = min(len(first_tokens), len(second_tokens))
    if overlap >= smaller and overlap >= 3:
        return True
    union = len(first_tokens | second_tokens)
    return union > 0 and overlap / union >= 0.62


def _merge_trade(existing: Trade, incoming: Trade) -> Trade:
    conviction = existing.conviction
    if _TRADE_CONVICTION_RANK.get(incoming.conviction, 0) > _TRADE_CONVICTION_RANK.get(
        conviction, 0
    ):
        conviction = incoming.conviction

    exposure = existing.exposure
    if _TRADE_EXPOSURE_RANK.get(incoming.exposure, 0) > _TRADE_EXPOSURE_RANK.get(exposure, 0):
        exposure = incoming.exposure

    timeframe = existing.timeframe
    if _TRADE_TIMEFRAME_RANK.get(incoming.timeframe, 0) > _TRADE_TIMEFRAME_RANK.get(
        timeframe, 0
    ):
        timeframe = incoming.timeframe

    rationale = existing.rationale
    if len(incoming.rationale.strip()) > len(rationale.strip()):
        rationale = incoming.rationale

    trigger_levels = existing.trigger_levels or incoming.trigger_levels
    if existing.trigger_levels and incoming.trigger_levels:
        trigger_levels = (
            incoming.trigger_levels
            if len(incoming.trigger_levels.strip()) > len(existing.trigger_levels.strip())
            else existing.trigger_levels
        )

    return Trade(
        text=existing.text if len(existing.text) >= len(incoming.text) else incoming.text,
        exposure=exposure,
        timeframe=timeframe,
        conviction=conviction,
        rationale=rationale,
        trigger_levels=trigger_levels,
    )


def _merge_chunk_trades(chunks: list[list[Trade]]) -> list[Trade]:
    ranked: list[Trade] = []

    for trades in chunks:
        for trade in trades:
            if not _is_actionable_trade(trade):
                continue
            key = _normalize_trade_key(trade.text)
            if not key:
                continue
            for idx, existing in enumerate(ranked):
                if _normalize_trade_key(existing.text) == key or _is_near_duplicate_trade(
                    existing,
                    trade,
                ):
                    ranked[idx] = _merge_trade(existing, trade)
                    break
            else:
                ranked.append(trade)

    ranked.sort(
        key=lambda trade: (
            _TRADE_CONVICTION_RANK.get(trade.conviction, 0),
            _TRADE_EXPOSURE_RANK.get(trade.exposure, 0),
            _TRADE_TIMEFRAME_RANK.get(trade.timeframe, 0),
            len(trade.rationale.strip()),
        ),
        reverse=True,
    )
    return ranked[:_MAX_TRADES]


@retry(
    stop=stop_after_attempt(6),
    wait=wait_random_exponential(multiplier=1, min=5, max=90),
    reraise=True,
)
def extract_trades(
    client: LLMClient,
    text: str,
    config: ModelConfig,
    log=None,
) -> list[Trade]:
    """
    Extract explicit trade ideas from a financial research document.

    Identifies positioning recommendations with conviction and timeframe.
    """
    log = log or logger
    log.info(
        "Extracting trades",
        text_length=len(text),
        provider=config.provider,
        model=config.model,
    )
    chunks = chunk_for_structured_extraction(text)
    if len(chunks) > 1:
        log.info(
            "Chunking trade extraction input",
            original_text_length=len(text),
            chunk_count=len(chunks),
            max_chunk_length=max(len(chunk) for chunk in chunks),
        )

    chunk_results: list[list[Trade]] = []
    for idx, chunk in enumerate(chunks, start=1):
        chunk_log = log.bind(chunk_index=idx, chunk_count=len(chunks))
        chunk_results.append(
            generate_with_validation_fallback(
                client=client,
                config=config,
                system=get_trades_prompt(),
                user=chunk,
                parser=_parse_trades_response,
                log=chunk_log,
                step="trades",
                response_format=_TRADES_RESPONSE_SCHEMA,
            )
        )

    trades = _merge_chunk_trades(chunk_results)
    log.info("Trades extracted", count=len(trades))
    return trades
