"""Jev DecisionModel adapter contract tests (fake transport; optional live)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import pytest

from research_analysis_layer.config import Settings
from research_analysis_layer.evals.decision_classifier import ShadowDecisionClassifier
from research_analysis_layer.evals.decision_question_set import build_questions_for_unit
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text
from research_analysis_layer.models.decision_models import (
    STATEMENT_TYPE_OPTIONS,
    DecisionBatch,
    DecisionUnit,
)
from research_analysis_layer.services.decision_model_factory import (
    DecisionModelConfigError,
    build_decision_model,
)
from research_analysis_layer.services.fake_decision_model import FakeDecisionModel
from research_analysis_layer.services.jev_decision_model import JevDecisionModel
from research_analysis_layer.services.jev_transport import (
    FakeJevTransport,
    JevTransportError,
)


def _unit(
    unit_id: str = "chunk-1:assertion-1",
    *,
    text: str = "We expect two cuts in H2.",
    assertion_type: str = "forecast",
) -> DecisionUnit:
    chunk_order, assertion_order = 1, 1
    if ":" in unit_id:
        chunk_part, assertion_part = unit_id.split(":", 1)
        chunk_order = int(chunk_part.replace("chunk-", ""))
        assertion_order = int(assertion_part.replace("assertion-", ""))
    return DecisionUnit(
        unit_id=unit_id,
        text=text,
        chunk_order=chunk_order,
        assertion_order=assertion_order,
        assertion_type=assertion_type,
    )


def _batch_for_unit(unit: DecisionUnit) -> DecisionBatch:
    return DecisionBatch(
        batch_id="batch-jev-test",
        shared_context="Macro outlook excerpt",
        units=[unit],
        questions=build_questions_for_unit(unit),
        document_key="doc-jev",
        document_hash="hash-jev",
    )


def _complete_answers(unit: DecisionUnit) -> dict[str, object]:
    answers: dict[str, object] = {}
    for question in build_questions_for_unit(unit):
        key = f"{question.target_unit_id}::{question.question_id}"
        if question.question_kind == "choice":
            probs = {opt: 0.02 for opt in STATEMENT_TYPE_OPTIONS}
            probs["assertion"] = 0.9
            # renormalize lightly
            total = sum(probs.values())
            probs = {k: v / total for k, v in probs.items()}
            answers[key] = {
                "type": "choice",
                "choice": "assertion",
                "probabilities": probs,
                "confidence": 0.8,
            }
        else:
            yes = 0.82 if question.question_id == "is_forecast" else 0.12
            answers[key] = {"type": "noul", "noul": yes}
    return answers


class JevAdapterContractTest(unittest.TestCase):
    def test_request_translation_preserves_ids_and_kinds(self) -> None:
        unit = _unit()
        batch = _batch_for_unit(unit)
        transport = FakeJevTransport(
            response_body={
                "model": "jev-1.13.0",
                "answers": _complete_answers(unit),
                "usage": {"input_tokens": 120, "output_tokens": 0},
            }
        )
        model = JevDecisionModel(transport, model="jev-1.13.0")
        result = model.classify_batch(batch)

        self.assertEqual(len(transport.requests), 1)
        request = transport.requests[0]
        self.assertEqual(request["model"], "jev-1.13.0")
        self.assertIn("units", request["state"])
        self.assertIn(unit.unit_id, request["state"]["units"])
        self.assertEqual(len(request["questions"]), len(batch.questions))
        choice_key = f"{unit.unit_id}::statement_type"
        self.assertEqual(request["questions"][choice_key]["type"], "choice")
        self.assertEqual(
            set(request["questions"][choice_key]["criteria"]),
            set(STATEMENT_TYPE_OPTIONS),
        )
        noul_key = f"{unit.unit_id}::is_forecast"
        self.assertEqual(request["questions"][noul_key]["type"], "noul")
        evidence_key = f"{unit.unit_id}::contains_verifiable_evidence"
        self.assertIn("criteria", request["questions"][evidence_key])
        self.assertIn("true", request["questions"][evidence_key]["criteria"])

        self.assertEqual(result.status, "complete")
        self.assertEqual(result.metadata.provider_name, "jev")
        self.assertEqual(result.metadata.model_version, "jev-1.13.0")
        self.assertEqual(result.usage.get("input_tokens"), 120.0)
        choice = next(r for r in result.results if r.question_id == "statement_type")
        assert choice.distribution is not None
        self.assertEqual(choice.distribution.selected, "assertion")
        self.assertIsNone(choice.distribution.calibrated_probability)
        forecast = next(r for r in result.results if r.question_id == "is_forecast")
        assert forecast.distribution is not None
        self.assertEqual(forecast.distribution.selected, "yes")
        self.assertAlmostEqual(forecast.distribution.raw_probability or 0.0, 0.82)

    def test_partial_missing_and_unknown_ids(self) -> None:
        unit = _unit()
        batch = _batch_for_unit(unit)
        answers = _complete_answers(unit)
        del answers[f"{unit.unit_id}::is_comparative"]
        answers["ghost::question"] = {"type": "noul", "noul": 0.9}
        transport = FakeJevTransport(
            response_body={"model": "jev-1.13.0", "answers": answers, "usage": {}}
        )
        result = JevDecisionModel(transport).classify_batch(batch)
        self.assertEqual(result.status, "partial")
        self.assertTrue(
            any("is_comparative" in key for key in result.missing_question_ids)
        )
        self.assertIn("ghost::question", result.unknown_question_ids)
        failed = [r for r in result.results if r.status == "failed"]
        self.assertTrue(any(r.question_id == "is_comparative" for r in failed))

    def test_malformed_probabilities_are_failed_not_negative(self) -> None:
        unit = _unit()
        question = build_questions_for_unit(unit)[0]
        batch = DecisionBatch(
            batch_id="bad-probs",
            shared_context="",
            units=[unit],
            questions=[question],
        )
        key = f"{unit.unit_id}::{question.question_id}"
        transport = FakeJevTransport(
            response_body={
                "model": "jev-1.13.0",
                "answers": {
                    key: {
                        "type": "choice",
                        "choice": "assertion",
                        "probabilities": {"assertion": 2.0, "question": 2.0},
                    }
                },
            }
        )
        result = JevDecisionModel(transport).classify_batch(batch)
        self.assertEqual(len(result.results), 1)
        self.assertEqual(result.results[0].status, "failed")
        self.assertIsNone(result.results[0].distribution)

    def test_retryable_then_success(self) -> None:
        unit = _unit()
        batch = _batch_for_unit(unit)
        transport = FakeJevTransport(
            errors=[
                JevTransportError("rate limited", status_code=429, retryable=True)
            ],
            response_body={
                "model": "jev-1.13.0",
                "answers": _complete_answers(unit),
                "usage": {},
            },
        )
        model = JevDecisionModel(transport, max_retries=2, retry_backoff_seconds=0.0)
        result = model.classify_batch(batch)
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(len(transport.requests), 2)

    def test_permanent_error_fails_closed(self) -> None:
        unit = _unit()
        batch = _batch_for_unit(unit)
        transport = FakeJevTransport(
            error=JevTransportError("unauthorized", status_code=401, retryable=False)
        )
        result = JevDecisionModel(transport, max_retries=3).classify_batch(batch)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.results, [])
        self.assertTrue(result.missing_question_ids)
        self.assertIn("unauthorized", result.provider_error or "")

    def test_shadow_runner_with_jev_fake_transport(self) -> None:
        unit = _unit()
        answers = _complete_answers(unit)

        def responder(request: dict) -> dict:
            return {"model": "jev-1.13.0", "answers": answers, "usage": {"input_tokens": 10}}

        model = JevDecisionModel(FakeJevTransport(responder=responder))
        draft = AssertionDraft(
            chunk_order=1,
            assertion_order=1,
            assertion_type="forecast",
            text=unit.text,
            normalized_text=normalize_text(unit.text),
            summary_text=unit.text,
        )
        artifact = ShadowDecisionClassifier(model).classify_assertions(
            [draft], document_key="jev-shadow"
        )
        self.assertEqual(artifact.provider, "jev")
        self.assertEqual(artifact.units[0].coverage_status, "full")
        self.assertIsNone(
            artifact.units[0].results[0].distribution.calibrated_probability  # type: ignore[union-attr]
        )


class DecisionModelFactoryTest(unittest.TestCase):
    def _settings(self, **overrides: object) -> Settings:
        env = {
            "NEXUS_DATABASE_URL": "postgresql://nexus:nexus@localhost:5432/nexus",
            "RESEARCH_ANALYST_PARSED_DATABASE_URL": (
                "postgresql://nexus:nexus@localhost:5432/nexus"
            ),
            "RESEARCH_ANALYST_DECISION_MODEL_PROVIDER": "fake",
            "RESEARCH_ANALYST_JEV_ENABLED": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            for key in (
                "RESEARCH_ANALYST_JEV_API_KEY",
                "RESEARCH_ANALYST_JEV_LIVE",
                "JEV_API_KEY",
                "JEV_LIVE",
            ):
                os.environ.pop(key, None)
            settings = Settings.from_env()
        for key, value in overrides.items():
            setattr(settings, key, value)
        return settings

    def test_default_is_fake(self) -> None:
        model = build_decision_model(self._settings())
        self.assertIsInstance(model, FakeDecisionModel)

    def test_jev_fails_closed_without_credentials(self) -> None:
        settings = self._settings(
            decision_model_provider="jev",
            jev_enabled=False,
            jev_api_key=None,
        )
        with self.assertRaises(DecisionModelConfigError):
            build_decision_model(settings, provider="jev")

    def test_jev_fails_closed_when_disabled(self) -> None:
        settings = self._settings(
            decision_model_provider="jev",
            jev_enabled=False,
            jev_api_key="sk-test",
        )
        with self.assertRaises(DecisionModelConfigError):
            build_decision_model(settings, provider="jev")

    def test_from_env_defaults_disabled(self) -> None:
        settings = self._settings()
        self.assertEqual(settings.decision_model_provider, "fake")
        self.assertFalse(settings.jev_enabled)
        self.assertFalse(settings.jev_live_tests)
        self.assertEqual(settings.jev_model, "jev-1.13.0")

    def test_validate_jev_provider_requires_key(self) -> None:
        settings = self._settings(
            decision_model_provider="jev",
            jev_enabled=True,
            jev_api_key=None,
        )
        errors = settings.validate()
        self.assertTrue(any("JEV_API_KEY" in err for err in errors))


@pytest.mark.jev_live
def test_live_jev_smoke_opt_in() -> None:
    """Live smoke test — skipped unless RESEARCH_ANALYST_JEV_LIVE=1 + creds."""
    from research_analysis_layer.env import load_env_files

    load_env_files()
    settings = Settings.from_env()
    live = settings.jev_live_tests or os.getenv(
        "RESEARCH_ANALYST_JEV_LIVE", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    if not live:
        pytest.skip("RESEARCH_ANALYST_JEV_LIVE not set")
    if not settings.jev_enabled or not (settings.jev_api_key or "").strip():
        pytest.skip("Jev credentials not configured")

    model = build_decision_model(settings, provider="jev")
    unit = _unit(text="Core PCE printed 2.4% year over year.")
    # Keep the live call tiny: statement_type only.
    question = build_questions_for_unit(unit)[0]
    batch = DecisionBatch(
        batch_id="live-smoke",
        shared_context="fixture smoke",
        units=[unit],
        questions=[question],
    )
    result = model.classify_batch(batch)
    assert result.status in {"complete", "partial"}
    assert result.results
    assert result.metadata.provider_name == "jev"
    assert result.results[0].distribution is not None
    assert result.results[0].distribution.calibrated_probability is None


if __name__ == "__main__":
    unittest.main()
