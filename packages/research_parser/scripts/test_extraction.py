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
    if not pdfs:
        print("No PDFs found.")
        return
    pdfs = sorted(pdfs, key=lambda p: p.name)
    test_pdf = pdfs[0]
    print(f"Using (deterministic): {test_pdf.name}")

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
        groq_api_key=getattr(settings, "groq_api_key", None),
        deepinfra_api_key=getattr(settings, "deepinfra_api_key", None),
        openrouter_api_key=getattr(settings, "openrouter_api_key", None),
        fireworks_api_key=getattr(settings, "fireworks_api_key", None),
        together_api_key=getattr(settings, "together_api_key", None),
    )

    # Show current configuration
    print(f"\nModel Configuration (from config/models.yaml):")
    print(f"  Boilerplate: {model_config.boilerplate.provider}/{model_config.boilerplate.model}")
    print(f"  Metadata:    {model_config.metadata.provider}/{model_config.metadata.model}")
    extended_thinking = (
        model_config.themes.extended_thinking.enabled
        if model_config.themes.extended_thinking
        else False
    )
    reasoning = model_config.themes.reasoning_effort or "off"
    print(
        f"  Themes:      {model_config.themes.provider}/{model_config.themes.model} "
        f"(extended_thinking={extended_thinking}, reasoning_effort={reasoning})"
    )
    print(f"  Trades:      {model_config.trades.provider}/{model_config.trades.model}")

    # Strip boilerplate
    print(f"\n[3a] Stripping boilerplate ({model_config.boilerplate.provider}/{model_config.boilerplate.model})...")
    clean_text = strip_boilerplate(
        client,
        markdown,
        config=model_config.boilerplate,
        deterministic_only=settings.boilerplate_deterministic_only,
        document_name=test_pdf.name,
        artifact_dir=settings.artifact_base_dir / "debug_test_extraction",
    )
    print(f"  Before: {len(markdown)} chars -> After: {len(clean_text)} chars")

    # Extract metadata
    print(f"\n[3b] Extracting metadata ({model_config.metadata.provider}/{model_config.metadata.model})...")
    metadata = extract_metadata(client, clean_text, config=model_config.metadata)
    print(f"  Source: {metadata.source}")
    print(f"  Date: {metadata.source_date}")
    print(f"  Area: {metadata.area}")
    print(f"  Asset focus: {metadata.asset_focus}")

    # Extract themes
    thinking_info = (
        f" + thinking={model_config.themes.extended_thinking.budget_tokens}"
        if model_config.themes.extended_thinking and model_config.themes.extended_thinking.enabled
        else ""
    )
    reasoning_info = (
        f" + reasoning={model_config.themes.reasoning_effort}"
        if model_config.themes.reasoning_effort
        else ""
    )
    print(
        f"\n[3c] Extracting themes "
        f"({model_config.themes.provider}/{model_config.themes.model}"
        f"{thinking_info}{reasoning_info})..."
    )
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
