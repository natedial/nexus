"""graphic-question-set-v1 integrity tests."""

from __future__ import annotations

import unittest

from src.graphic_selection.kit import kit_patterns
from src.graphic_selection.question_set import (
    PATTERN_OPTIONS,
    QUESTION_SET_VERSION,
    REPRESENTATION_QUESTION_ID,
    expected_question_ids,
    noul_ids,
    shape_preference,
    snapshot_question_set,
)


class QuestionSetTests(unittest.TestCase):
    def test_version_and_choice_options(self):
        self.assertEqual(QUESTION_SET_VERSION, "graphic-question-set-v1")
        self.assertEqual(REPRESENTATION_QUESTION_ID, "representation")
        self.assertIn("prose", PATTERN_OPTIONS)
        kit_ids = set(kit_patterns())
        for option in PATTERN_OPTIONS:
            if option == "prose":
                continue
            self.assertIn(option, kit_ids)

    def test_options_cover_all_kit_patterns(self):
        kit_ids = set(kit_patterns())
        self.assertEqual(kit_ids, set(PATTERN_OPTIONS) - {"prose"})

    def test_shape_preference_maps_to_options(self):
        pref = shape_preference()
        self.assertEqual(pref["none"], "prose")
        for pattern in pref.values():
            self.assertIn(pattern, PATTERN_OPTIONS)

    def test_snapshot_is_stable(self):
        a = snapshot_question_set()
        b = snapshot_question_set()
        self.assertEqual(a.content_hash, b.content_hash)
        self.assertEqual(a.version, QUESTION_SET_VERSION)
        self.assertEqual(
            [q.question_id for q in a.questions],
            expected_question_ids(),
        )
        self.assertEqual(len(noul_ids()), 13)


if __name__ == "__main__":
    unittest.main()
