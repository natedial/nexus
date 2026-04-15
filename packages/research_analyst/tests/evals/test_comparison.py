"""Tests for eval comparison utilities."""

from __future__ import annotations

import unittest

from research_analysis_layer.evals.comparison import (
    compare_outputs,
    compute_confidence,
    compute_field_similarity,
    confidence_delta,
    exact_match,
    list_match_rate,
    rouge_l,
    structured_match_score,
)


class TestRougeL(unittest.TestCase):
    """Tests for ROUGE-L similarity."""

    def test_identical_text(self):
        actual = "The Fed will cut rates in September"
        expected = "The Fed will cut rates in September"
        self.assertAlmostEqual(rouge_l(actual, expected), 1.0, places=2)

    def test_completely_different(self):
        actual = "The Fed will cut rates in September"
        expected = "ECB maintains policy unchanged"
        score = rouge_l(actual, expected)
        self.assertLess(score, 0.5)

    def test_partial_overlap(self):
        actual = "The Fed will cut rates in September"
        expected = "The Fed will cut rates in Q4"
        score = rouge_l(actual, expected)
        self.assertGreater(score, 0.3)

    def test_empty_strings(self):
        self.assertEqual(rouge_l("", ""), 1.0)
        self.assertEqual(rouge_l("text", ""), 0.0)
        self.assertEqual(rouge_l("", "text"), 0.0)


class TestListMatchRate(unittest.TestCase):
    """Tests for list matching."""

    def test_identical_lists(self):
        actual = ["a", "b", "c"]
        expected = ["a", "b", "c"]
        self.assertEqual(list_match_rate(actual, expected), 1.0)

    def test_completely_different(self):
        actual = ["a", "b", "c"]
        expected = ["x", "y", "z"]
        self.assertEqual(list_match_rate(actual, expected), 0.0)

    def test_partial_overlap(self):
        actual = ["a", "b", "c"]
        expected = ["a", "x", "y"]
        self.assertAlmostEqual(list_match_rate(actual, expected), 1 / 3, places=2)

    def test_empty_lists(self):
        self.assertEqual(list_match_rate([], []), 1.0)
        self.assertEqual(list_match_rate(["a"], []), 0.0)
        self.assertEqual(list_match_rate([], ["a"]), 0.0)

    def test_fuzzy_matching(self):
        actual = ["Fed cuts delayed"]
        expected = ["Fed cuts delayed to September"]
        score = list_match_rate(actual, expected)
        self.assertGreater(score, 0.5)


class TestExactMatch(unittest.TestCase):
    """Tests for exact match."""

    def test_identical(self):
        self.assertEqual(exact_match("test", "test"), 1.0)
        self.assertEqual(exact_match(1, 1), 1.0)
        self.assertEqual(exact_match(None, None), 1.0)

    def test_different(self):
        self.assertEqual(exact_match("a", "b"), 0.0)
        self.assertEqual(exact_match(1, 2), 0.0)


class TestConfidenceDelta(unittest.TestCase):
    """Tests for confidence delta comparison."""

    def test_identical(self):
        self.assertEqual(confidence_delta(0.8, 0.8), 1.0)

    def test_within_tolerance(self):
        self.assertEqual(confidence_delta(0.85, 0.80), 1.0)
        self.assertEqual(confidence_delta(0.75, 0.80), 1.0)

    def test_outside_tolerance(self):
        score = confidence_delta(0.5, 0.8)
        self.assertLess(score, 1.0)
        self.assertGreater(score, 0.0)


class TestStructuredMatchScore(unittest.TestCase):
    """Tests for structured object matching."""

    def test_identical_dicts(self):
        actual = {"a": 1, "b": 2}
        expected = {"a": 1, "b": 2}
        self.assertEqual(structured_match_score(actual, expected), 1.0)

    def test_different_dicts(self):
        actual = {"a": 1, "b": 2}
        expected = {"a": 3, "b": 4}
        self.assertEqual(structured_match_score(actual, expected), 0.0)

    def test_partial_overlap(self):
        actual = {"a": 1, "b": 2}
        expected = {"a": 1, "b": 3, "c": 4}
        score = structured_match_score(actual, expected)
        self.assertGreater(score, 0.3)
        self.assertLess(score, 0.7)


class TestComputeFieldSimilarity(unittest.TestCase):
    """Tests for field similarity dispatch."""

    def test_text_field(self):
        actual = "Hello world"
        expected = "Hello world"
        self.assertEqual(compute_field_similarity(actual, expected, "text"), 1.0)

    def test_list_field(self):
        actual = ["a", "b"]
        expected = ["a", "b"]
        self.assertEqual(compute_field_similarity(actual, expected, "list"), 1.0)

    def test_exact_field(self):
        self.assertEqual(compute_field_similarity("a", "a", "exact"), 1.0)
        self.assertEqual(compute_field_similarity("a", "b", "exact"), 0.0)

    def test_confidence_field(self):
        self.assertEqual(compute_field_similarity(0.8, 0.8, "confidence"), 1.0)

    def test_unknown_field_defaults_to_text(self):
        score = compute_field_similarity("test", "test", "unknown")
        self.assertEqual(score, 1.0)


class TestComputeConfidence(unittest.TestCase):
    """Tests for weighted confidence computation."""

    def test_empty_scores(self):
        self.assertEqual(compute_confidence({}), 0.0)

    def test_single_field(self):
        scores = {"thesis": 0.8}
        self.assertAlmostEqual(compute_confidence(scores), 0.8, places=3)

    def test_all_fields(self):
        scores = {
            "thesis": 0.9,
            "key_claims_claim": 0.8,
            "trading_opportunities_thesis": 0.7,
            "trading_opportunities_direction": 0.6,
            "talking_points_text": 0.85,
            "confidence": 0.75,
        }
        expected = (
            0.9 * 0.25
            + 0.8 * 0.15
            + 0.7 * 0.20
            + 0.6 * 0.10
            + 0.85 * 0.15
            + 0.75 * 0.15
        )
        self.assertAlmostEqual(compute_confidence(scores), expected, places=2)


class TestCompareOutputs(unittest.TestCase):
    """Tests for full output comparison."""

    def test_identical_outputs(self):
        actual = {
            "thesis": "Fed cuts delayed",
            "key_claims": [{"claim": "test", "confidence": 0.8}],
            "trading_opportunities": [],
            "talking_points": [],
            "confidence": 0.8,
        }
        expected = {
            "thesis": "Fed cuts delayed",
            "key_claims": [{"claim": "test", "confidence": 0.8}],
            "trading_opportunities": [],
            "talking_points": [],
            "confidence": 0.8,
        }
        result = compare_outputs(actual, expected)
        self.assertAlmostEqual(result["thesis"], 1.0, places=2)
        self.assertAlmostEqual(result["confidence"], 1.0, places=2)

    def test_different_thesis(self):
        actual = {"thesis": "Fed cuts delayed", "confidence": 0.8}
        expected = {"thesis": "Fed hikes rates", "confidence": 0.8}
        result = compare_outputs(actual, expected)
        self.assertLess(result["thesis"], 0.5)


if __name__ == "__main__":
    unittest.main()
