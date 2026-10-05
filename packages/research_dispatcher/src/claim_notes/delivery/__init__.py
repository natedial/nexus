"""Morning-attention delivery senders (own surface only)."""

from src.claim_notes.delivery.chat_ping import (
    ChatPingResult,
    FakeChatPingSender,
    SmtpChatPingSender,
)
from src.claim_notes.delivery.remarkable import (
    FakeRemarkableNotebookSender,
    FileRemarkableNotebookSender,
    HttpRemarkableNotebookSender,
    RemarkablePushResult,
)
from src.claim_notes.delivery.render import (
    morning_attention_chat_line,
    morning_attention_markdown,
)

__all__ = [
    "ChatPingResult",
    "FakeChatPingSender",
    "FakeRemarkableNotebookSender",
    "FileRemarkableNotebookSender",
    "HttpRemarkableNotebookSender",
    "RemarkablePushResult",
    "SmtpChatPingSender",
    "morning_attention_chat_line",
    "morning_attention_markdown",
]
