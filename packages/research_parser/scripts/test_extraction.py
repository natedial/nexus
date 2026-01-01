#!/usr/bin/env python3
"""Test Claude extraction pipeline with a parsed PDF."""

from src.config import get_settings
from src.drive import DriveWatcher
from src.extraction import (
    extract_metadata,
    extract_themes,
    extract_trades,
    strip_boilerplate,
)
from src.llm import LLMClient, load_model_config
from src.parser import LlamaIndexParser


def main():
    print("Loading settings...")
    settings = get_settings()
    model_config = load_model_config()

    # Get and parse a PDF
    print("\n--- Step 1: Get PDF from Drive ---")
    watcher = DriveWatcher(
        credentials_path=settings.google_credentials_path,
        folder_id=settings.google_drive_folder_id,
    )
    pdfs = watcher.list_pdfs()
    test_pdf = pdfs[0]
    print(f"Using: {test_pdf.name}")

    file_path = watcher.download_file(test_pdf.id, test_pdf.name)

    print("\n--- Step 2: Parse with LlamaIndex ---")
    parser = LlamaIndexParser(api_key=settings.llamaindex_api_key)
    result = parser.parse(file_path)

    if not result.markdown:
        print(f"Parse failed: {result.error}")
        return

    print(f"Got {len(result.markdown)} chars of markdown")
    markdown = result.markdown

    # Initialize LLM client
    print("\n--- Step 3: LLM Extraction ---")
    client = LLMClient(
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
    )

    # Show current configuration
    print(f"\nModel Configuration (from config/models.yaml):")
    print(f"  Boilerplate: {model_config.boilerplate.provider}/{model_config.boilerplate.model}")
    print(f"  Metadata:    {model_config.metadata.provider}/{model_config.metadata.model}")
    print(f"  Themes:      {model_config.themes.provider}/{model_config.themes.model} (thinking={model_config.themes.extended_thinking.enabled if model_config.themes.extended_thinking else False})")
    print(f"  Trades:      {model_config.trades.provider}/{model_config.trades.model}")

    # Strip boilerplate
    print(f"\n[3a] Stripping boilerplate ({model_config.boilerplate.provider}/{model_config.boilerplate.model})...")
    clean_text = strip_boilerplate(client, markdown, config=model_config.boilerplate)
    print(f"  Before: {len(markdown)} chars -> After: {len(clean_text)} chars")

    # Extract metadata
    print(f"\n[3b] Extracting metadata ({model_config.metadata.provider}/{model_config.metadata.model})...")
    metadata = extract_metadata(client, clean_text, config=model_config.metadata)
    print(f"  Source: {metadata.source}")
    print(f"  Date: {metadata.source_date}")
    print(f"  Area: {metadata.area}")
    print(f"  Asset focus: {metadata.asset_focus}")

    # Extract themes
    thinking_info = f" + thinking={model_config.themes.extended_thinking.budget_tokens}" if model_config.themes.extended_thinking and model_config.themes.extended_thinking.enabled else ""
    print(f"\n[3c] Extracting themes ({model_config.themes.provider}/{model_config.themes.model}{thinking_info})...")
    themes = extract_themes(client, clean_text, config=model_config.themes)
    print(f"  Found {len(themes)} themes:")
    for t in themes:
        print(f"    - {t.label} ({t.strength}, {t.confidence} confidence)")

    # Extract trades
    print(f"\n[3d] Extracting trades ({model_config.trades.provider}/{model_config.trades.model})...")
    trades = extract_trades(client, clean_text, config=model_config.trades)
    print(f"  Found {len(trades)} trades:")
    for t in trades:
        print(f"    - {t.text[:80]}..." if len(t.text) > 80 else f"    - {t.text}")
        print(f"      Conviction: {t.conviction}, Timeframe: {t.timeframe}")

    # Cleanup
    file_path.unlink()
    print("\n--- Done! ---")


if __name__ == "__main__":
    main()
