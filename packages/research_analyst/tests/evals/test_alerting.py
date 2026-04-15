"""Tests for alerting."""

import unittest

from research_analysis_layer.evals.alerting import Alert, AlertHandler


class TestAlert(unittest.TestCase):
    """Tests for Alert dataclass."""

    def test_alert_creation(self):
        alert = Alert(
            alert_type="regression",
            metric_name="confidence_avg",
            baseline_value=0.80,
            current_value=0.65,
            delta=-0.15,
            threshold=0.10,
        )

        self.assertEqual(alert.alert_type, "regression")
        self.assertEqual(alert.metric_name, "confidence_avg")
        self.assertEqual(alert.baseline_value, 0.80)
        self.assertEqual(alert.current_value, 0.65)
        self.assertEqual(alert.delta, -0.15)


class TestAlertHandler(unittest.TestCase):
    """Tests for AlertHandler class."""

    def test_handler_initialization(self):
        handler = AlertHandler()
        self.assertFalse(handler.alert_on_improvements)

    def test_handler_with_improvements_enabled(self):
        handler = AlertHandler(alert_on_improvements=True)
        self.assertTrue(handler.alert_on_improvements)

    def test_check_regression_detects_regression(self):
        handler = AlertHandler()

        baseline = {"confidence_avg": 0.80, "schema_validity_rate": 0.95}
        current = {"confidence_avg": 0.65, "schema_validity_rate": 0.95}

        alerts = handler.check_regression(baseline, current, threshold=0.10)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].alert_type, "regression")
        self.assertEqual(alerts[0].metric_name, "confidence_avg")

    def test_check_regression_no_alert_when_above_threshold(self):
        handler = AlertHandler()

        baseline = {"confidence_avg": 0.80}
        current = {"confidence_avg": 0.78}

        alerts = handler.check_regression(baseline, current, threshold=0.10)

        self.assertEqual(len(alerts), 0)

    def test_check_regression_improvement_logged_by_default(self):
        handler = AlertHandler(alert_on_improvements=False)

        baseline = {"confidence_avg": 0.70}
        current = {"confidence_avg": 0.85}

        alerts = handler.check_regression(baseline, current, threshold=0.10)

        self.assertEqual(len(alerts), 0)

    def test_check_regression_improvement_alerts_when_enabled(self):
        handler = AlertHandler(alert_on_improvements=True)

        baseline = {"confidence_avg": 0.70}
        current = {"confidence_avg": 0.85}

        alerts = handler.check_regression(baseline, current, threshold=0.10)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].alert_type, "improvement")

    def test_check_regression_with_zero_baseline(self):
        handler = AlertHandler()

        baseline = {"metric": 0.0}
        current = {"metric": 0.0}

        alerts = handler.check_regression(baseline, current, threshold=0.10)

        self.assertEqual(len(alerts), 0)

    def test_custom_handler_called(self):
        handler = AlertHandler()
        called = []

        def custom_handler(alert):
            called.append(alert)

        handler.register_handler(custom_handler)

        baseline = {"confidence_avg": 0.80}
        current = {"confidence_avg": 0.60}

        handler.check_regression(baseline, current, threshold=0.10)

        self.assertEqual(len(called), 1)
        self.assertEqual(called[0].metric_name, "confidence_avg")

    def test_multiple_metrics(self):
        handler = AlertHandler()

        baseline = {
            "confidence_avg": 0.80,
            "thesis_similarity": 0.85,
            "latency_avg_ms": 2000,
        }
        current = {
            "confidence_avg": 0.65,
            "thesis_similarity": 0.70,
            "latency_avg_ms": 2500,
        }

        alerts = handler.check_regression(baseline, current, threshold=0.10)

        self.assertEqual(len(alerts), 2)
        alert_metrics = {a.metric_name for a in alerts}
        self.assertIn("confidence_avg", alert_metrics)
        self.assertIn("thesis_similarity", alert_metrics)

    def test_ignore_missing_current_metrics(self):
        handler = AlertHandler()

        baseline = {"confidence_avg": 0.80, "other_metric": 0.90}
        current = {"confidence_avg": 0.65}

        alerts = handler.check_regression(baseline, current, threshold=0.10)

        self.assertEqual(len(alerts), 1)


if __name__ == "__main__":
    unittest.main()
