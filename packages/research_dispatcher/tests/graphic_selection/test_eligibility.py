"""Shape/field eligibility and fail-closed mapping."""

from __future__ import annotations

import unittest

from src.graphic_selection.eligibility import (
    eligibility_flags,
    map_shape_to_pattern,
    pattern_fields_satisfied,
)


class EligibilityTests(unittest.TestCase):
    def test_map_shape_happy_path(self):
        self.assertEqual(
            map_shape_to_pattern(
                "signed_changes",
                ["category", "signed_change", "unit", "common_domain"],
            ),
            "diverging_bars",
        )

    def test_map_shape_fail_closed_missing_fields(self):
        self.assertEqual(
            map_shape_to_pattern("signed_changes", ["category"]),
            "prose",
        )

    def test_none_shape_is_prose(self):
        self.assertEqual(map_shape_to_pattern("none", ["label", "value"]), "prose")

    def test_eligibility_flags_shape_only(self):
        flags = eligibility_flags(
            "scalars",
            ["label", "value", "unit", "as_of_or_window", "comparison_label", "comparison_value"],
        )
        self.assertTrue(flags["has_scalar_levels"])
        self.assertFalse(flags["has_signed_changes"])
        # No significance / speaker-weight keys ever.
        self.assertNotIn("is_significant", flags)
        self.assertNotIn("deserves_chart", flags)

    def test_pattern_fields_prose_always_ok(self):
        self.assertTrue(pattern_fields_satisfied("prose", []))


if __name__ == "__main__":
    unittest.main()
