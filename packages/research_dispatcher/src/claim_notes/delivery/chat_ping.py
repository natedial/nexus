"""One-line chat ping for morning attention (SMTP, same pattern as other briefs)."""

from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from typing import Protocol


@dataclass
class ChatPingResult:
    subject: str
    body: str
    recipients: list[str]
    dry_run: bool = False


class ChatPingSender(Protocol):
    def send(self, *, subject: str, body: str) -> ChatPingResult:
        ...


@dataclass
class FakeChatPingSender:
    messages: list[dict[str, str]] = field(default_factory=list)

    def send(self, *, subject: str, body: str) -> ChatPingResult:
        self.messages.append({"subject": subject, "body": body})
        return ChatPingResult(
            subject=subject, body=body, recipients=["fake@example.com"], dry_run=True
        )


class SmtpChatPingSender:
    """Send a one-line ping via the dispatcher SMTP settings."""

    def __init__(
        self,
        *,
        smtp_server: str,
        smtp_port: int,
        username: str,
        password: str,
        from_email: str,
        to_email: str,
    ) -> None:
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.to_email = to_email

    def send(self, *, subject: str, body: str) -> ChatPingResult:
        recipients = [r.strip() for r in self.to_email.split(",") if r.strip()]
        if not recipients:
            raise ValueError("chat ping recipients are empty")
        msg = MIMEText(body, "plain")
        msg["From"] = self.from_email
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.username, self.password)
            server.send_message(msg)
        return ChatPingResult(subject=subject, body=body, recipients=recipients)
