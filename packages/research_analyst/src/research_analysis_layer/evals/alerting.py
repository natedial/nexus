"""Alerting for eval regression detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class Alert:
    """Alert for regression detection."""

    alert_type: str  # "regression" or "improvement"
    metric_name: str
    baseline_value: float
    current_value: float
    delta: float
    threshold: float


class AlertHandler:
    """Handler for eval alerts."""

    def __init__(
        self,
        db: "EvalDatabase | None" = None,
        webhook_url: str | None = None,
        slack_webhook: str | None = None,
        alert_on_improvements: bool = False,
    ):
        """Initialize alert handler.

        Args:
            db: Optional database for persisting alerts
            webhook_url: Optional generic webhook URL
            slack_webhook: Optional Slack webhook URL
            alert_on_improvements: If True, also alert on improvements (default: False)
        """
        self.db = db
        self.webhook_url = webhook_url
        self.slack_webhook = slack_webhook
        self.alert_on_improvements = alert_on_improvements
        self.handlers: list[Callable[[Alert], None]] = []

    def register_handler(self, handler: Callable[[Alert], None]) -> None:
        """Register a custom alert handler."""
        self.handlers.append(handler)

    def check_regression(
        self,
        baseline_metrics: dict[str, float],
        current_metrics: dict[str, float],
        threshold: float = 0.10,
    ) -> list[Alert]:
        """Check for regressions between baseline and current metrics.

        Args:
            baseline_metrics: Metrics from baseline run
            current_metrics: Metrics from current run
            threshold: Percentage threshold for alert (default 10%)

        Returns:
            List of alerts triggered
        """
        alerts = []

        for metric_name, baseline_value in baseline_metrics.items():
            if metric_name not in current_metrics:
                continue

            current_value = current_metrics[metric_name]

            if baseline_value == 0:
                delta = current_value
            else:
                delta = (current_value - baseline_value) / baseline_value

            if delta < -threshold:
                alert = Alert(
                    alert_type="regression",
                    metric_name=metric_name,
                    baseline_value=baseline_value,
                    current_value=current_value,
                    delta=delta,
                    threshold=threshold,
                )
                alerts.append(alert)
                self._handle_alert(alert)
            elif delta > threshold and self.alert_on_improvements:
                alert = Alert(
                    alert_type="improvement",
                    metric_name=metric_name,
                    baseline_value=baseline_value,
                    current_value=current_value,
                    delta=delta,
                    threshold=threshold,
                )
                alerts.append(alert)
                self._handle_alert(alert)
            elif delta > threshold:
                logger.info(
                    f"Improvement on {metric_name}: {baseline_value:.3f} -> {current_value:.3f} "
                    f"({delta:.1%})"
                )

        return alerts

    def _handle_alert(self, alert: Alert) -> None:
        """Handle a triggered alert."""
        logger.warning(
            f"Alert: {alert.alert_type} on {alert.metric_name}: "
            f"{alert.baseline_value:.3f} -> {alert.current_value:.3f} "
            f"({alert.delta:.1%})"
        )

        if self.db:
            self.db.insert_alert(
                alert_type=alert.alert_type,
                metric_name=alert.metric_name,
                baseline_value=alert.baseline_value,
                current_value=alert.current_value,
                delta=alert.delta,
                threshold=alert.threshold,
            )

        for handler in self.handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Alert handler failed: {e}")

        if self.slack_webhook:
            self._send_slack_notification(alert)

    def _send_slack_notification(self, alert: Alert) -> None:
        """Send alert to Slack webhook."""
        if not self.slack_webhook:
            return

        import urllib.request
        import json

        emoji = ":warning:" if alert.alert_type == "regression" else ":tada:"

        payload = {
            "text": f"{emoji} *Eval Alert: {alert.alert_type.title()}*",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{alert.alert_type.title()} detected on {alert.metric_name}*",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*Baseline:*\n{alert.baseline_value:.3f}",
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Current:*\n{alert.current_value:.3f}",
                        },
                        {"type": "mrkdwn", "text": f"*Delta:*\n{alert.delta:.1%}"},
                        {
                            "type": "mrkdwn",
                            "text": f"*Threshold:*\n{alert.threshold:.1%}",
                        },
                    ],
                },
            ],
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                self.slack_webhook,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(request, timeout=5)
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")


def create_alert_handler(config: dict[str, Any] | None = None) -> AlertHandler:
    """Create an alert handler from config."""
    config = config or {}

    return AlertHandler(
        db=config.get("db"),
        webhook_url=config.get("webhook_url"),
        slack_webhook=config.get("slack_webhook"),
    )
