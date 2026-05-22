from pathlib import Path

import pytest

from src.parser import BlockType, MinerUBackend


def _write_mineru_cli(script_path: Path) -> None:
    script_path.write_text(
        (
            "#!/bin/sh\n"
            'pdf=""\n'
            'out=""\n'
            'backend=""\n'
            'while [ "$#" -gt 0 ]; do\n'
            '  case "$1" in\n'
            '    -p) pdf="$2"; shift 2 ;;\n'
            '    -o) out="$2"; shift 2 ;;\n'
            '    -b) backend="$2"; shift 2 ;;\n'
            '    *) shift ;;\n'
            '  esac\n'
            'done\n'
            'stem=$(basename "$pdf" .pdf)\n'
            'mkdir -p "$out/$stem/images"\n'
            'printf \'## Heading\\nParagraph one\\r\\n- Item\\n\' > "$out/$stem/$stem.md"\n'
            "printf '%s' "
            '\'[{"type":"image","page_idx":2,"img_path":"images/figure_1.png",'
            '"caption":"Chart","section_path":["Appendix"]}]\' '
            '> "$out/$stem/${stem}_content_list.json"\n'
            'printf \'png\' > "$out/$stem/images/figure_1.png"\n'
            "exit 0\n"
        ),
        encoding="utf-8",
    )
    script_path.chmod(0o755)


def test_parse_text_reads_markdown_from_cli_output(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    binary_path = tmp_path / "mineru"
    _write_mineru_cli(binary_path)
    backend = MinerUBackend(binary_path=binary_path)

    result = backend.parse_text(pdf_path)

    assert "## Heading" in result.raw_output
    assert "\r" not in result.raw_output
    assert result.blocks[0].block_type == BlockType.HEADING
    assert result.blocks[0].text == "Heading"
    assert result.blocks[1].block_type == BlockType.PARAGRAPH
    assert result.blocks[2].block_type == BlockType.LIST_ITEM


def test_extract_figures_reads_content_list_from_cli_output(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    binary_path = tmp_path / "mineru"
    _write_mineru_cli(binary_path)
    backend = MinerUBackend(binary_path=binary_path)

    backend.parse_text(pdf_path)
    figures = backend.extract_figures(pdf_path)

    assert len(figures) == 1
    assert figures[0].page == 2
    assert figures[0].caption_text == "Chart"
    assert figures[0].section_path == ["Appendix"]
    assert figures[0].image_path is not None
    assert Path(figures[0].image_path).name == "figure_1.png"


def test_parse_text_raises_when_binary_missing(tmp_path):
    backend = MinerUBackend(binary_path=tmp_path / "missing-mineru")

    with pytest.raises(FileNotFoundError):
        backend.parse_text(tmp_path / "sample.pdf")


def test_parse_text_raises_on_cli_failure(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    binary_path = tmp_path / "mineru"
    binary_path.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
    binary_path.chmod(0o755)
    backend = MinerUBackend(binary_path=binary_path)

    with pytest.raises(RuntimeError) as excinfo:
        backend.parse_text(pdf_path)

    assert "exit code 9" in str(excinfo.value)
