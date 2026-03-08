from __future__ import annotations

from types import SimpleNamespace

from distill_tool.judge_cli import render_worksheet


def test_render_worksheet_includes_template_and_candidates() -> None:
    results = [
        SimpleNamespace(
            chunk_id="chunk-1",
            source_path="sample.md",
            page_number=2,
            chunk_index=1,
            hybrid_score=0.9,
            lexical_score=0.8,
            semantic_score=0.7,
            text="This is a preview text for judging.",
        )
    ]

    worksheet = render_worksheet(
        query_id="q1",
        query="example query",
        results=results,
        preview_chars=40,
    )

    assert "Judging Worksheet: q1" in worksheet
    assert '"query":"example query"' in worksheet
    assert "`chunk_id`: `chunk-1`" in worksheet
