"""Bootstrap node and edge resolution."""

from __future__ import annotations

from research_analysis_layer.models import AssertionDraft, EdgeResolution, NodeResolution
from research_analysis_layer.models.assertion_models import normalize_text


class Resolver:
    """Map assertions into conservative node and edge resolutions."""

    _ASSERTION_TO_NODE_TYPE = {
        "forecast": "forecast",
        "market_impact": "market_impact",
        "open_question": "open_question",
    }

    _ASSERTION_TO_EDGE_TYPE = {
        "causal_claim": "drives",
        "market_impact": "impacts",
        "risk_condition": "qualifies",
        "forecast": "forecasts",
        "policy_claim": "related_to",
        "trade_claim": "supports",
    }

    def resolve_nodes(self, assertions: list[AssertionDraft]) -> list[NodeResolution]:
        nodes: list[NodeResolution] = []
        for assertion in assertions:
            subject_text = (assertion.subject_text or assertion.summary_text).strip()
            node_type = self._ASSERTION_TO_NODE_TYPE.get(assertion.assertion_type, "concept")
            nodes.append(
                NodeResolution(
                    node_key=f"{node_type}:{normalize_text(subject_text)}",
                    node_type=node_type,
                    canonical_label=subject_text,
                    summary_text=assertion.text,
                    chunk_order=assertion.chunk_order,
                    assertion_order=assertion.assertion_order,
                    evidence_text=assertion.text,
                    alias_text=assertion.summary_text if assertion.summary_text != subject_text else None,
                )
            )
            if assertion.object_text:
                object_text = assertion.object_text.strip()
                object_type = "open_question" if assertion.assertion_type == "open_question" else "concept"
                nodes.append(
                    NodeResolution(
                        node_key=f"{object_type}:{normalize_text(object_text)}",
                        node_type=object_type,
                        canonical_label=object_text,
                        summary_text=assertion.text,
                        chunk_order=assertion.chunk_order,
                        assertion_order=assertion.assertion_order,
                        evidence_text=assertion.text,
                    )
                )
        return nodes

    def resolve_edges(
        self,
        assertions: list[AssertionDraft],
        nodes: list[NodeResolution],
    ) -> list[EdgeResolution]:
        del nodes
        edges: list[EdgeResolution] = []
        for assertion in assertions:
            subject_text = (assertion.subject_text or assertion.summary_text).strip()
            if not subject_text or not assertion.object_text:
                continue
            from_key = self._node_key_for_subject(assertion, subject_text)
            to_key = self._node_key_for_object(assertion.object_text, assertion.assertion_type)
            edge_type = self._ASSERTION_TO_EDGE_TYPE.get(assertion.assertion_type, "related_to")
            edges.append(
                EdgeResolution(
                    edge_key=f"{edge_type}:{from_key}->{to_key}",
                    from_node_key=from_key,
                    to_node_key=to_key,
                    edge_type=edge_type,
                    directionality="directed",
                    status=assertion.status,
                    authority_band=assertion.authority_band,
                    maturity="path" if assertion.confidence_label == "high" else "trace",
                    chunk_order=assertion.chunk_order,
                    assertion_order=assertion.assertion_order,
                    evidence_text=assertion.text,
                )
            )
        return edges

    def _node_key_for_subject(self, assertion: AssertionDraft, subject_text: str) -> str:
        node_type = self._ASSERTION_TO_NODE_TYPE.get(assertion.assertion_type, "concept")
        if assertion.assertion_type == "open_question":
            node_type = "concept"
        return f"{node_type}:{normalize_text(subject_text)}"

    @staticmethod
    def _node_key_for_object(object_text: str, assertion_type: str) -> str:
        node_type = "open_question" if assertion_type == "open_question" else "concept"
        return f"{node_type}:{normalize_text(object_text)}"
