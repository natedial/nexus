"""Inside a run, no tool may show anything published after the document."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from research_analysis_layer.services.round_executor import RoundConfig, RoundExecutor
from research_analysis_layer.services.tools.argument_graph_tool import (
    ARGUMENT_GRAPH_TOOL_NAME,
    ARGUMENT_GRAPH_TOOL_SCHEMA,
    create_argument_graph_handlers,
)
from research_analysis_layer.services.tools.as_of import AsOfScope, parse_day
from research_analysis_layer.services.tools.distill_adapter import DistillAdapter, create_distill_handlers
from research_analysis_layer.services.tools.registry import ToolRegistry
from research_analysis_layer.services.tools.tholos_adapter import TholosAdapter, create_tholos_handlers

SCOPE = AsOfScope(as_of=parse_day("2026-09-20"), exclude_research_id=3)
RESULTS = [
    {"chunk_id": "before", "source_date": "2026-09-19", "text": "a"},
    {"chunk_id": "same-day", "source_date": "2026-09-20T15:00:00Z", "text": "b"},
    {"chunk_id": "after", "source_date": "2026-09-21", "text": "c"},
    {"chunk_id": "undated", "source_date": None, "text": "d"},
    {"chunk_id": "garbled", "source_date": "last week", "text": "e"},
]


class Corpus:
    def __init__(self):
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append(kwargs)
        return [dict(item) for item in RESULTS]

    def corpus_info(self):
        return {"sources": ["future-note.pdf"]}


def search_registry(kind):
    corpus = Corpus()
    if kind == "distill":
        handlers = create_distill_handlers(DistillAdapter(corpus))
    else:
        adapter = TholosAdapter()
        adapter.search, adapter.corpus_info = corpus.search, corpus.corpus_info
        handlers = create_tholos_handlers(adapter)
    registry = ToolRegistry()
    for name, handler in handlers.items():
        registry.register_handler(name, handler)
    return registry, corpus


@pytest.mark.parametrize("kind", ["distill", "tholos"])
@pytest.mark.parametrize("asked", [None, "2026-12-31", "2026-09-01"])
def test_search_is_bounded_even_if_the_model_asks_for_more(kind, asked):
    registry, corpus = search_registry(kind)
    query = {"query": "q", **({"date_to": asked} if asked else {})}
    with registry.as_of_scope(SCOPE):
        result = registry.invoke("research_search", query)
    assert corpus.calls[0]["date_to"] == min(asked or "2026-09-20", "2026-09-20")
    assert [r["chunk_id"] for r in result["content"]["results"]] == ["before", "same-day"]
    assert result["content"]["withheld_count"] == 3


@pytest.mark.parametrize("kind", ["distill", "tholos"])
def test_search_outside_a_run_is_unchanged(kind):
    registry, corpus = search_registry(kind)
    result = registry.invoke("research_search", {"query": "q"})
    assert len(result["content"]) == 5
    assert corpus.calls[0]["date_to"] is None


def test_tools_that_cannot_honour_the_limit_are_refused():
    registry, _ = search_registry("distill")
    with registry.as_of_scope(SCOPE):
        result = registry.invoke("research_corpus_info", {})
    assert result["is_error"] is True
    assert "as-of" in result["content"]


def test_unknown_document_date_blocks_every_tool():
    registry, corpus = search_registry("distill")
    with registry.as_of_scope(AsOfScope(as_of=None)):
        result = registry.invoke("research_search", {"query": "q"})
    assert result["is_error"] is True
    assert corpus.calls == []


def test_refused_calls_do_not_spend_the_tool_budget():
    registry, _ = search_registry("distill")
    registry.set_invocation_budget(1)
    with registry.as_of_scope(SCOPE):
        registry.invoke("research_corpus_info", {})
        assert registry.invoke("research_search", {"query": "q"})["is_error"] is False


def test_scope_ends_with_the_run_even_on_error():
    registry, _ = search_registry("distill")
    with pytest.raises(RuntimeError):
        with registry.as_of_scope(SCOPE):
            raise RuntimeError
    assert registry.invoke("research_corpus_info", {})["is_error"] is False


def claim_map(research_id, source, polarity, day):
    return {
        "research_id": research_id, "source": source, "source_date": day,
        "argument_map": [{
            "claim": f"{source} view", "claim_key": f"claim:fed_policy:hike:{polarity}",
            "support_strength": "evidenced", "rationale": "r",
            "evidence": [{"text": "CPI", "ref_key": "chunk-1", "referent_key": "cpi-aug"}],
        }],
    }


def graph_sides(maps, scope):
    registry = ToolRegistry()
    registry.register_schema(ARGUMENT_GRAPH_TOOL_SCHEMA)
    store = MagicMock()
    store.list_argument_maps_for_consensus.return_value = maps
    for name, handler in create_argument_graph_handlers(store).items():
        registry.register_handler(name, handler)
    with registry.as_of_scope(scope):
        result = registry.invoke(ARGUMENT_GRAPH_TOOL_NAME, {"query": "interpretation_gaps"})
    assert result["is_error"] is False, result
    return result["content"]


GS, MS = ("Goldman Sachs", "up"), ("Morgan Stanley", "down")


def test_argument_graph_shows_earlier_disagreement():
    content = graph_sides([claim_map(1, *GS, "2026-09-10"), claim_map(2, *MS, "2026-09-18")], SCOPE)
    assert content["hit_count"] == 1


@pytest.mark.parametrize("late", ["2026-09-25", None, "soon"])
def test_argument_graph_hides_later_or_undated_notes(late):
    content = graph_sides([claim_map(1, *GS, "2026-09-10"), claim_map(2, *MS, late)], SCOPE)
    assert content["hit_count"] == 0


def test_argument_graph_hides_the_document_under_debate():
    content = graph_sides([claim_map(1, *GS, "2026-09-10"), claim_map(3, *MS, "2026-09-18")], SCOPE)
    assert content["hit_count"] == 0


@pytest.mark.parametrize("source_date,expected", [("2026-04-14", "2026-04-14"), (None, None), ("??", None)])
def test_executor_scopes_tools_to_the_document_date(source_date, expected):
    seen = []
    registry = ToolRegistry()

    class Client:
        def generate_with_tools(self, **_):
            seen.append(registry.active_scope)
            raise RuntimeError("stop")

    prompts = MagicMock()
    prompts.load_prompt.return_value = "p"
    builder = MagicMock()
    builder.to_messages.return_value = []
    executor = RoundExecutor(registry=prompts, llm_client=Client(), input_builder=builder,
                             tool_registry=registry, debate_mode="on")
    document = SimpleNamespace(research_id=7, document_hash="h", file_id=None, themes=[], spans=[],
                               document=SimpleNamespace(source_date=source_date, parsed_data={}))
    agent = SimpleNamespace(name="a", config=SimpleNamespace(model="m", tools=[], provider=None), tools=[],
                            max_tool_calls=0, timeout_seconds=1, retry_count=1, temperature=0, output_schema="")
    executor.run(document=document, chunks=[], evidence_units=[], assertions=[], run_id=1, analysis_version="v",
                 rounds=[RoundConfig(name="synthesis", type="sequential", agents=["a"], receives=[])],
                 agent_specs={"a": agent})
    assert str(seen[0].as_of) == str(expected)
    assert seen[0].exclude_research_id == 7
    assert registry.active_scope is None
