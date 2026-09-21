from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from research_analysis_layer.services.tools.argument_graph_tool import (
    ARGUMENT_GRAPH_TOOL_NAME,
    ARGUMENT_GRAPH_TOOL_SCHEMA,
    create_argument_graph_handlers,
)
from research_analysis_layer.services.tools.registry import ToolRegistry


def _map(
    *,
    source: str,
    research_id: int,
    claim: str,
    claim_key: str,
    rationale: str,
    ref_key: str,
    evidence_text: str,
    referent_key: str | None,
    support_strength: str = "evidenced",
) -> dict:
    evidence = []
    if referent_key is not None or evidence_text:
        row = {
            "text": evidence_text,
            "kind": "data",
            "ref_key": ref_key,
        }
        if referent_key is not None:
            row["referent_key"] = referent_key
        evidence.append(row)
    return {
        "source": source,
        "research_id": research_id,
        "argument_map": [
            {
                "claim": claim,
                "claim_key": claim_key,
                "rationale": rationale,
                "support_strength": support_strength,
                "evidence": evidence,
            }
        ],
    }


def _gap_maps() -> list[dict]:
    return [
        _map(
            source="Goldman Sachs",
            research_id=1,
            claim="A September Fed hike is very unlikely.",
            claim_key="claim:fed_policy:hike:down",
            rationale="labor has cooled",
            ref_key="span:gs-1",
            evidence_text="payrolls slowed to 5k",
            referent_key="series:nfp",
        ),
        _map(
            source="Citi",
            research_id=19,
            claim="Not setting up a September rate hike.",
            claim_key="claim:fed_policy:hike:down",
            rationale="speech was not guidance",
            ref_key="span:citi-19",
            evidence_text="payrolls cooled",
            referent_key="series:nfp",
        ),
        _map(
            source="Barclays",
            research_id=16,
            claim="25bp September hike most likely.",
            claim_key="claim:fed_policy:hike:up",
            rationale="hawkish tone",
            ref_key="span:barc-16",
            evidence_text="payrolls leave the door open",
            referent_key="series:nfp",
        ),
    ]


class ArgumentGraphToolTest(unittest.TestCase):
    def _handler(self, maps=None):
        maps = maps if maps is not None else _gap_maps()
        handlers = create_argument_graph_handlers(maps=maps, min_publishers=2)
        return handlers[ARGUMENT_GRAPH_TOOL_NAME]

    def test_interpretation_gaps_match_argument_graph_fixture(self) -> None:
        result = self._handler()({"query": "interpretation_gaps"})
        self.assertEqual(result["query"], "interpretation_gaps")
        self.assertEqual(result["hit_count"], 1)
        self.assertFalse(result["truncated"])
        hit = result["hits"][0]
        self.assertEqual(hit["referent_key"], "series:nfp")
        self.assertEqual(
            {side["publisher"] for side in hit["sides"]},
            {"Barclays", "Citi", "Goldman Sachs"},
        )
        polarities = {side["publisher"]: side["polarity"] for side in hit["sides"]}
        self.assertEqual(polarities["Barclays"], "up")
        self.assertEqual(polarities["Goldman Sachs"], "down")
        self.assertTrue(all(side["publisher"] for side in hit["sides"]))
        self.assertNotIn("thesis", {side["publisher"] for side in hit["sides"]})
        self.assertNotIn("contrarian", {side["publisher"] for side in hit["sides"]})

    def test_same_evidence_alias_and_default_all(self) -> None:
        aliased = self._handler()({"query": "same_evidence"})
        self.assertEqual(aliased["query"], "interpretation_gaps")
        self.assertEqual(aliased["hit_count"], 1)

        full = self._handler()({})
        self.assertEqual(full["query"], "all")
        self.assertEqual(full["interpretation_gaps"]["hit_count"], 1)
        self.assertIn("independence", full)
        self.assertIn("contradictions", full)
        self.assertIn("backed_vs_asserted", full)

    def test_independence_distinguishes_robust_from_herding(self) -> None:
        robust_maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor has cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                rationale="speech was not guidance",
                ref_key="span:citi-19",
                evidence_text="Warsh said the speech was not guidance",
                referent_key="event:jackson_hole_2026:not_guidance",
            ),
        ]
        herding_maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor has cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor cooled",
                ref_key="span:citi-19",
                evidence_text="payrolls cooled",
                referent_key="series:nfp",
            ),
        ]
        robust = self._handler(robust_maps)({"query": "independence"})
        herding = self._handler(herding_maps)({"query": "herding"})
        self.assertEqual(robust["hits"][0]["kind"], "robust")
        self.assertEqual(herding["hits"][0]["kind"], "herding")
        self.assertEqual(robust["hits"][0]["positions"], ["Citi", "Goldman Sachs"])

    def test_claim_key_scopes_the_join(self) -> None:
        result = self._handler()(
            {
                "query": "interpretation_gaps",
                "claim_key": "claim:fed_policy:hike:down",
            }
        )
        self.assertEqual(result["claim_key"], "claim:fed_policy:hike:down")
        self.assertEqual(result["hit_count"], 1)

        missed = self._handler()(
            {
                "query": "interpretation_gaps",
                "claim_key": "claim:other:thing:up",
            }
        )
        self.assertEqual(missed["hit_count"], 0)
        self.assertEqual(missed["hits"], [])

    def test_limit_truncates_hits(self) -> None:
        maps = []
        for idx, house in enumerate(["Goldman Sachs", "Morgan Stanley", "Citi"]):
            maps.append(
                _map(
                    source=house,
                    research_id=idx + 1,
                    claim=f"{house} hike call",
                    claim_key="claim:fed_policy:hike:down",
                    rationale="labor cooled",
                    ref_key=f"span:{idx}",
                    evidence_text="payrolls slowed",
                    referent_key=f"series:nfp:{idx}",
                )
            )
        for idx, house in enumerate(["Barclays", "JPM"]):
            maps.append(
                _map(
                    source=house,
                    research_id=idx + 10,
                    claim=f"{house} hike call",
                    claim_key="claim:fed_policy:hike:up",
                    rationale="hawkish",
                    ref_key=f"span:up:{idx}",
                    evidence_text="payrolls leave the door open",
                    referent_key=f"series:nfp:{idx}",
                )
            )
        result = self._handler(maps)({"query": "interpretation_gaps", "limit": 1})
        self.assertGreaterEqual(result["hit_count"], 2)
        self.assertEqual(len(result["hits"]), 1)
        self.assertTrue(result["truncated"])

    def test_store_is_read_on_invoke(self) -> None:
        store = MagicMock()
        store.list_argument_maps_for_consensus.return_value = _gap_maps()
        handlers = create_argument_graph_handlers(store, min_publishers=2)
        result = handlers[ARGUMENT_GRAPH_TOOL_NAME](
            {"query": "interpretation_gaps"}
        )
        store.list_argument_maps_for_consensus.assert_called_once_with()
        self.assertEqual(result["hit_count"], 1)

    def test_unknown_query_is_an_error_through_the_registry(self) -> None:
        registry = ToolRegistry()
        registry.register_schema(ARGUMENT_GRAPH_TOOL_SCHEMA)
        handlers = create_argument_graph_handlers(maps=_gap_maps())
        registry.register_handler(ARGUMENT_GRAPH_TOOL_NAME, handlers[ARGUMENT_GRAPH_TOOL_NAME])
        result = registry.invoke(ARGUMENT_GRAPH_TOOL_NAME, {"query": "not-a-join"})
        self.assertTrue(result["is_error"])
        self.assertIn("unknown query", result["content"])

    def test_schema_is_additive_to_corpus_search(self) -> None:
        registry = ToolRegistry()
        self.assertIn("research_search", registry.list_tools())
        self.assertNotIn(ARGUMENT_GRAPH_TOOL_NAME, registry.list_tools())
        registry.register_schema(ARGUMENT_GRAPH_TOOL_SCHEMA)
        self.assertIn("research_search", registry.list_tools())
        self.assertIn(ARGUMENT_GRAPH_TOOL_NAME, registry.list_tools())
        schema = registry.get_schema(ARGUMENT_GRAPH_TOOL_NAME)
        self.assertEqual(schema, ARGUMENT_GRAPH_TOOL_SCHEMA)
        self.assertIn("publisher", schema["description"])

    def test_register_agent_tools_adds_argument_graph_beside_search(self) -> None:
        import sys
        import types

        if "research_pipeline_ops" not in sys.modules:
            stub = types.ModuleType("research_pipeline_ops")
            stub.PipelineOpsClient = MagicMock
            sys.modules["research_pipeline_ops"] = stub
        from research_analysis_layer.main import register_agent_tools
        from research_analysis_layer.services.tools.argument_graph_tool import (
            ARGUMENT_GRAPH_TOOL_NAME,
        )

        store = MagicMock()
        store.list_argument_maps_for_consensus.return_value = _gap_maps()
        settings = MagicMock()
        settings.tholos_enabled = False
        settings.consensus_min_publishers = 2
        registry = ToolRegistry()
        register_agent_tools(registry, settings, store)
        self.assertIn("research_search", registry.list_tools())
        self.assertIn(ARGUMENT_GRAPH_TOOL_NAME, registry.list_tools())
        result = registry.invoke(
            ARGUMENT_GRAPH_TOOL_NAME, {"query": "interpretation_gaps"}
        )
        self.assertFalse(result["is_error"])
        self.assertEqual(result["content"]["hit_count"], 1)


if __name__ == "__main__":
    unittest.main()
