"""Real-document export, pilot preparation/run, and Jev comparison (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_analysis_layer.evals.decision_agent_models import (
    ModelCatalog,
    load_model_catalog,
)
from research_analysis_layer.evals.decision_agent_pilot_run import (
    build_jev_comparison,
    prepare_real_pilot,
    run_prepared_pilot,
)
from research_analysis_layer.evals.decision_agent_references import AXIS_IDS
from research_analysis_layer.evals.decision_classifier import ShadowDecisionClassifier
from research_analysis_layer.evals.decision_real_units import (
    RealAssertionRow,
    export_real_units,
    prepare_units,
)
from research_analysis_layer.models.decision_models import QUESTION_SET_VERSION
from research_analysis_layer.services.agent_llm_client import AgentCallResult, TokenUsage
from research_analysis_layer.services.fake_decision_model import FakeDecisionModel

PREFIX = "a" * 64 + ": "

SUBSTANTIVE = [
    "We expect the curve to steepen over the next six months as supply rises.",
    "Underperformance of France sovereign bonds has been accelerating this quarter.",
    "We recommend a short in 10y Belgium versus EU bonds into year end.",
    "Higher starting yields should lift optimal bond allocations over time.",
    "Basis returns have compressed as asset-manager futures demand fell sharply.",
    "Dealer exposure has increased only marginally over the past year overall.",
]
BOILERPLATE = [
    "Past performance is not a guide to future performance, future returns are not guaranteed.",
    "For important disclosures, please see the research disclosures website here.",
    "Matthew Example | Global Head of Strategy | +1 212 555-0100 |",
    "This research is not an offer to sell or the solicitation of an offer to buy any security.",
]


def _rows(research_id: int = 7) -> list[RealAssertionRow]:
    rows: list[RealAssertionRow] = []
    for index, text in enumerate(SUBSTANTIVE, start=1):
        rows.append(
            RealAssertionRow(index, research_id, "h", 1 + (index - 1) // 3, index, "forecast", PREFIX + text)
        )
    rows.append(RealAssertionRow(50, research_id, "h", 2, 50, "forecast", PREFIX + SUBSTANTIVE[0]))
    rows.append(RealAssertionRow(51, research_id, "h", 2, 51, "observation", PREFIX + "Too short."))
    for offset, text in enumerate(BOILERPLATE):
        rows.append(RealAssertionRow(60 + offset, research_id, "h", 3, offset, "observation", PREFIX + text))
    # A substantive-looking line inside the trailing disclosures section.
    rows.append(RealAssertionRow(70, research_id, "h", 4, 1, "observation", PREFIX + "Each report is reviewed and approved on behalf of the firm."))
    return rows


def test_prepare_units_strips_prefix_and_explains_every_exclusion() -> None:
    kept, excluded = prepare_units(_rows())
    assert [unit.text for unit in kept] == SUBSTANTIVE
    assert all(unit.prefix_stripped for unit in kept)
    reasons = {item["text"][:20]: item["reason"] for item in excluded}
    assert reasons["Too short."] .startswith("too_short")
    assert any(reason == "duplicate_text_in_document" for reason in reasons.values())
    assert any(reason.startswith("boilerplate:past_performance") for reason in reasons.values())
    assert any(reason.startswith("boilerplate:table_fragment") or reason.startswith("boilerplate:contact") for reason in reasons.values())
    assert any(reason.startswith("trailing_disclosures(from chunk 3)") for reason in reasons.values())
    assert len(kept) + len(excluded) == len(_rows())


def test_stray_boilerplate_mid_report_does_not_cut_the_rest() -> None:
    rows = [
        RealAssertionRow(1, 7, "h", 1, 1, "x", PREFIX + "Past performance of the curve trade has been strong this year."),
        *[
            RealAssertionRow(i + 2, 7, "h", 2 + i, 1, "x", PREFIX + text)
            for i, text in enumerate(SUBSTANTIVE)
        ],
    ]
    kept, excluded = prepare_units(rows)
    assert len(kept) == len(SUBSTANTIVE)
    assert [item["reason"] for item in excluded] == ["boilerplate:past_performance"]


LAYOUT = [
    "Figure\n\nGlobal Markets Daily: Re-Assessing the Value of Duration\n\nGlobal bond yields have risen sharply.",
    "Exhibit 7: Similar to during the Tech Bubble, the proportion of stocks with a negative beta has increased",
    "Interpolated SOFR rates 15bp used for repo rate Source: Morgan Stanley Research, Bloomberg.",
    "Note: ESTR implied rate refers to the implied rate in short-term interest rate futures.",
]
KEPT_DESPITE_LAYOUT_WORDS = [
    "On the ratings side, the shift away from AA exposure continued (Exhibit 20).",
    "Key Takeaways\n\nBasis notional has fallen to $1.2tn from $1.5tn, but risk is unchanged.",
    "Our main source of concern is the supply calendar into year end.",
]


def test_layout_fragments_are_excluded_but_inline_references_are_kept() -> None:
    rows = [
        RealAssertionRow(i + 1, 7, "h", 1, i + 1, "x", PREFIX + text)
        for i, text in enumerate(LAYOUT + KEPT_DESPITE_LAYOUT_WORDS)
    ]
    kept, excluded = prepare_units(rows)
    assert [unit.text for unit in kept] == KEPT_DESPITE_LAYOUT_WORDS
    assert [item["reason"] for item in excluded] == [
        "layout:figure_title_block",
        "layout:exhibit_caption",
        "layout:source_note",
        "layout:source_note",
    ]


def test_captions_late_in_a_report_do_not_start_a_trailing_cut() -> None:
    rows = [
        *[
            RealAssertionRow(i + 1, 7, "h", 1 + i, 1, "x", PREFIX + text)
            for i, text in enumerate(SUBSTANTIVE[:2])
        ],
        *[
            RealAssertionRow(10 + i, 7, "h", 3, i, "x", PREFIX + text)
            for i, text in enumerate(LAYOUT)
        ],
        RealAssertionRow(20, 7, "h", 4, 1, "x", PREFIX + SUBSTANTIVE[2]),
    ]
    kept, excluded = prepare_units(rows)
    assert [unit.text for unit in kept] == SUBSTANTIVE[:3]
    assert all(item["reason"].startswith("layout:") for item in excluded)


class FakeConnection:
    def __init__(self, rows: list[RealAssertionRow]) -> None:
        self.rows = rows

    def execute(self, sql: str, params):
        research_ids = set(params[0])
        if "from analysis_documents" in sql:
            data = [
                (rid, "hash", "Test Bank", "2026-09-21", f"Doc {rid}")
                for rid in sorted({row.research_id for row in self.rows})
                if rid in research_ids
            ]
        else:
            data = [
                (r.assertion_id, r.research_id, r.document_hash, r.chunk_order, r.assertion_order, r.assertion_type, r.text)
                for r in self.rows
                if r.research_id in research_ids
            ]
        return type("Result", (), {"fetchall": lambda self_: data})()


def _export(tmp_path: Path) -> Path:
    export_dir = tmp_path / "export"
    rows = _rows(7) + [
        RealAssertionRow(100 + r.assertion_id, 8, r.document_hash, r.chunk_order, r.assertion_order, r.assertion_type, r.text)
        for r in _rows(8)
    ]
    classifier = ShadowDecisionClassifier(
        FakeDecisionModel(question_set_version=QUESTION_SET_VERSION), batch_size=4
    )
    manifest = export_real_units(
        connection=FakeConnection(rows),
        research_ids=[7, 8],
        output_dir=export_dir,
        classifier=classifier,
    )
    assert manifest["kept_units"] == 2 * len(SUBSTANTIVE)
    assert manifest["database_access"] == "read_only"
    assert ["exhibit_caption", r"(?:^|\n)\s*exhibit \d+:"] in manifest["layout_rules"]
    return export_dir


def test_export_refuses_unknown_documents(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no rows for research_id"):
        export_real_units(
            connection=FakeConnection(_rows(7)),
            research_ids=[7, 9],
            output_dir=tmp_path / "x",
            classifier=None,
        )


class AgreeingClient:
    """Labels every axis the same way for every role, quoting the first word."""

    reference_calls_are_single_attempt = True

    def __init__(self, sampling: dict) -> None:
        self.sampling = sampling
        self.calls = 0

    def reference_sampling_for_model(self, model: str) -> dict:
        return dict(self.sampling)

    def generate_with_tools(self, **kwargs):
        self.calls += 1
        payload = json.loads(kwargs["messages"][0]["content"])
        text = payload["source"]["target_text"]
        word = text.split()[0]
        axes = [
            {
                "axis_id": axis_id,
                "state": "labeled",
                "value": "assertion" if axis_id == "statement_type" else axis_id == "is_forecast",
                "rationale": f"{axis_id} judged from '{word}'.",
                "quotes": [word],
            }
            for axis_id in AXIS_IDS
        ]
        body = {"axes": axes}
        return AgentCallResult(
            raw_text=json.dumps(body),
            parsed_output=body,
            token_usage=TokenUsage(input_tokens=3000, output_tokens=1500),
            model_used=kwargs["model"],
            stop_reason="end_turn",
        )


def _clients(resolved):
    return {
        role: AgreeingClient(entry.sampling) for role, entry in resolved.entries.items()
    }


def test_prepare_run_report_end_to_end(tmp_path: Path) -> None:
    export_dir = _export(tmp_path)
    prep = tmp_path / "prep"
    result = prepare_real_pilot(
        export_dir=export_dir,
        output_dir=prep,
        pilot_id="pilot-test",
        seed="seed-1",
        max_units=10,
        catalog=load_model_catalog(),
        role_overrides={"reviewer": "openai:gpt-5.6-sol"},
        max_usd=4.5,
    )
    assert result["selected_units"] == 10
    assert result["dry_run"]["ready_for_live_execution"] is True
    assert "gpt-5.6-sol" in result["role_models"]["reviewer"]
    frozen = json.loads((prep / "role_models.json").read_text())
    assert frozen["reviewer"]["model"] == "gpt-5.6-sol"
    sources = [json.loads(line) for line in (prep / "sources.jsonl").read_text().splitlines()]
    assert sources[0]["transformations"][0]["transformation_id"] == "strip-document-hash-prefix"
    assert not sources[0]["source_text"].startswith(PREFIX)

    smoke_dir = run_prepared_pilot(
        preparation_dir=prep, run_dir=tmp_path / "smoke", smoke_units=2, client_factory=_clients
    )
    smoke = json.loads((smoke_dir / "manifest.json").read_text())
    assert smoke["status"] == "complete"
    assert len(smoke["completed_source_ids"]) == 2
    assert smoke["config"]["run_id"] == "pilot-test-smoke2"

    run_dir = run_prepared_pilot(
        preparation_dir=prep, run_dir=tmp_path / "run", client_factory=_clients
    )
    report = build_jev_comparison(run_dir=run_dir, export_dir=export_dir)
    assert report["references"] == 10
    assert report["usd_per_request"] == pytest.approx((3000 * 2 + 1500 * 10) / 1e6 / 2 + (3000 * 4 + 1500 * 20) / 1e6 / 2)
    forecast = report["per_axis"]["is_forecast"]
    assert forecast["admitted"] == 10
    assert forecast["jev_agree"] + forecast["jev_disagree"] + forecast["jev_not_comparable"] == 10
    assert forecast["outcome"] in {"looks_sound_so_far", "wording_needs_work", "needs_human_labels"}
    assert len(report["audit_sample"]) == 1
    assert (run_dir / "JEV_COMPARISON.md").is_file()


def test_catalog_edit_after_prepare_cannot_change_the_run(tmp_path: Path) -> None:
    export_dir = _export(tmp_path)
    prep = tmp_path / "prep"
    prepare_real_pilot(
        export_dir=export_dir, output_dir=prep, pilot_id="p", seed="s",
        max_units=4, catalog=load_model_catalog(), max_usd=1.0,
    )
    stored = json.loads((prep / "role_models.json").read_text())
    stored["reviewer"]["model"] = "gpt-5.6-luna"
    (prep / "role_models.json").write_text(json.dumps(stored))
    with pytest.raises(ValueError, match="do not match the pilot specification"):
        run_prepared_pilot(preparation_dir=prep, run_dir=tmp_path / "run", client_factory=_clients)


def test_invalid_unit_is_recorded_and_the_run_continues(tmp_path: Path) -> None:
    export_dir = _export(tmp_path)
    prep = tmp_path / "prep"
    prepare_real_pilot(
        export_dir=export_dir, output_dir=prep, pilot_id="p", seed="s",
        max_units=3, catalog=load_model_catalog(), max_usd=1.0,
    )

    class SometimesBroken(AgreeingClient):
        def generate_with_tools(self, **kwargs):
            payload = json.loads(kwargs["messages"][0]["content"])
            if payload["source"]["source_id"] == broken_id:
                self.calls += 1
                return AgentCallResult(raw_text="no json", parsed_output=None,
                    token_usage=TokenUsage(input_tokens=10, output_tokens=5),
                    model_used=kwargs["model"], stop_reason="end_turn")
            return super().generate_with_tools(**kwargs)

    # Match by source_id: the fake export repeats sentences across documents.
    broken_id = json.loads((prep / "sources.jsonl").read_text().splitlines()[0])["source_id"]
    run_dir = run_prepared_pilot(
        preparation_dir=prep, run_dir=tmp_path / "run",
        client_factory=lambda resolved: {
            role: SometimesBroken(entry.sampling) for role, entry in resolved.entries.items()
        },
    )
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    assert len(manifest["failed_source_ids"]) == 1
    assert len(manifest["completed_source_ids"]) == 2
    failed = (run_dir / "failed_sources.jsonl").read_text().splitlines()
    assert "InvalidJudgmentResponse" in failed[0]
