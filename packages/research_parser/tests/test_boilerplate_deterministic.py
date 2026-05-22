from src.extraction.boilerplate import _strip_boilerplate_deterministic


def _build_document(
    *,
    total_lines: int,
    header_index: int,
    legal_lines: int,
    header: str = "Analyst Certification",
) -> str:
    lines = [f"Research content line {i}" for i in range(total_lines)]
    lines[header_index] = header
    for i in range(legal_lines):
        idx = min(total_lines - 1, header_index + 1 + i)
        lines[idx] = (
            "Analyst disclosures, conflict of interest, regulatory details, "
            "and compensation notes."
        )
    return "\n".join(lines)


def test_deterministic_strips_when_legal_density_is_high():
    text = _build_document(total_lines=120, header_index=95, legal_lines=10)

    cleaned, info = _strip_boilerplate_deterministic(text)

    assert cleaned is not None
    assert info is not None
    assert info["confidence"] in {"medium", "high"}
    assert "Analyst Certification" not in cleaned


def test_deterministic_rejects_low_density_header_match():
    text = _build_document(total_lines=120, header_index=95, legal_lines=0)

    cleaned, info = _strip_boilerplate_deterministic(text)

    assert cleaned is None
    assert info is not None
    assert info["reason"] == "low_legal_density"
    assert info["confidence"] == "low"


def test_deterministic_rejects_header_that_is_too_early():
    text = _build_document(total_lines=120, header_index=40, legal_lines=10)

    cleaned, info = _strip_boilerplate_deterministic(text)

    assert cleaned is None
    assert info is not None
    assert info["reason"] == "header_too_early"


def test_source_specific_rule_allows_earlier_cut_for_jpm():
    text = _build_document(total_lines=120, header_index=75, legal_lines=8)

    cleaned_default, _ = _strip_boilerplate_deterministic(
        text,
        document_name="2026-03-01_ABC_Macro_Update.pdf",
    )
    cleaned_jpm, info_jpm = _strip_boilerplate_deterministic(
        text,
        document_name="2026-03-01_JPM_Macro_Update.pdf",
    )

    assert cleaned_default is None
    assert cleaned_jpm is not None
    assert info_jpm is not None
    assert info_jpm["source_key"] == "jpm"
