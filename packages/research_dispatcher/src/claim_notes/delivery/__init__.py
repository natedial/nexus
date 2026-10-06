"""Morning-attention delivery senders (own surface only).

Canonical: Proey connector handoff (reMarkable markdown + Grok Bot one-liner).
Chat ping → Nate's 1:1 with Proey (same as 5:55/6:10) — never SMTP / EMAIL_TO.
Notebook default title: "Morning Attention YYYY-MM-DD", next to G10 / Research From.
"""

from src.claim_notes.delivery.chat_ping import (
    ChatPingResult,
    FakeChatPingSender,
    FakeGrokBotChatPingSender,
    HandoffGrokBotChatPingSender,
    HttpGrokBotChatPingSender,
)
from src.claim_notes.delivery.remarkable import (
    FakeRemarkableNotebookSender,
    FileRemarkableNotebookSender,
    HandoffRemarkableNotebookSender,
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
    "FakeGrokBotChatPingSender",
    "FakeRemarkableNotebookSender",
    "FileRemarkableNotebookSender",
    "HandoffGrokBotChatPingSender",
    "HandoffRemarkableNotebookSender",
    "HttpGrokBotChatPingSender",
    "HttpRemarkableNotebookSender",
    "RemarkablePushResult",
    "morning_attention_chat_line",
    "morning_attention_markdown",
]
