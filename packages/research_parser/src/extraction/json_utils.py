"""Shared JSON extraction utilities for LLM responses."""

import re


_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_MINIMAX_TOOL_RE = re.compile(
    r"<minimax:tool_call>.*?</minimax:tool_call>",
    re.IGNORECASE | re.DOTALL,
)


def strip_model_markup(text: str) -> str:
    """Remove common reasoning/tool wrappers before JSON extraction."""
    text = _THINK_TAG_RE.sub("", text)
    text = _MINIMAX_TOOL_RE.sub("", text)
    return text.strip()


def extract_json_block(text: str) -> str:
    """Extract the first complete JSON object/array from text.

    Uses bracket-matching with proper string/escape handling to find
    the boundaries of the JSON, rather than naive code-fence splitting.
    """
    json_start = -1
    for i, char in enumerate(text):
        if char in "[{":
            json_start = i
            break

    if json_start == -1:
        return text

    stack: list[str] = []
    in_string = False
    escape = False
    for i in range(json_start, len(text)):
        char = text[i]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == "\"":
                in_string = False
            continue

        if char == "\"":
            in_string = True
            continue

        if char in "[{":
            stack.append(char)
            continue

        if char in "]}":
            if not stack:
                continue
            opener = stack.pop()
            if (opener == "[" and char != "]") or (opener == "{" and char != "}"):
                # Mismatch — push opener back and skip this closer
                stack.append(opener)
                continue
            if not stack:
                return text[json_start : i + 1]

    return text[json_start:]


def clean_json_response(text: str) -> str:
    """Clean JSON response from LLM output.

    Removes code fences and explanatory text, then uses bracket-matching
    to extract the JSON payload.
    """
    text = text.strip()

    # Strip leading code fence marker (e.g. ```json)
    if text.startswith("```"):
        parts = text.split("```", 2)
        if len(parts) >= 2:
            text = parts[1]

    text = strip_model_markup(text)
    text = extract_json_block(text)

    return text.strip()
