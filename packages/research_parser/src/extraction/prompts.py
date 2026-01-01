"""Prompt loader - reads prompts from markdown files."""

from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


@lru_cache(maxsize=10)
def load_prompt(name: str) -> str:
    """
    Load a prompt from the prompts directory.

    Args:
        name: Prompt name without extension (e.g., "themes", "trades")

    Returns:
        Prompt content as string
    """
    prompt_file = PROMPTS_DIR / f"{name}.md"
    if not prompt_file.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")
    return prompt_file.read_text().strip()


# Convenience accessors for each prompt
def get_boilerplate_prompt() -> str:
    return load_prompt("boilerplate")


def get_metadata_prompt() -> str:
    return load_prompt("metadata")


def get_themes_prompt() -> str:
    return load_prompt("themes")


def get_trades_prompt() -> str:
    return load_prompt("trades")


def get_synthesis_prompt() -> str:
    return load_prompt("synthesis")
