# Phase 1: Introduce Artifacts + ParserBackend Interface

**Scope:** Create the seam. No behavior change to the extraction chain. LlamaIndex stays as the sole parser. We add: (a) a ParserBackend ABC, (b) a LlamaIndexBackend that wraps the existing LlamaIndexParser, (c) artifact writing (document.md + figures.jsonl). Downstream extraction consumes the exact same markdown string it does today.

---

## Design Decisions

### 1. raw_output on TextParseResult (not instance state, not a separate method)

`parse_text()` returns `TextParseResult(blocks, raw_output)`. `raw_output` is the backend's native serialization — markdown for LlamaIndex, None for future deterministic backends. The pipeline uses `raw_output` when present for the extraction chain; falls back to `blocks_to_markdown(blocks)` otherwise. This is not a leaky abstraction: it honestly models that some backends have a richer native format than blocks alone can reconstruct.

### 2. LlamaIndexBackend stores the full markdown as a single paragraph block

We do NOT parse markdown into headings/paragraphs/list_items in Phase 1. TODO (Phase 2): parse into structured blocks (alongside Docling, where the comparison is meaningful). A single block is simpler, impossible to get wrong, and the blocks field isn't consumed by anything meaningful yet — `document.md` is written from `raw_output`, and the extraction chain uses `raw_output` directly.

### 3. confidence() returns a ConfidenceResult dataclass (PASS/REPAIR/FALLBACK + score + reasons; status should be a Literal or Enum)

Matches the user's triage spec. LlamaIndex returns `PASS, 1.0, []` — it has no internal quality signal. TODO (Phase 2): add heuristic scoring in the base class once real blocks are available.

### 4. Artifact writing is non-fatal

Pipeline wraps the call in try/except and logs a warning on failure. `write_artifacts()` itself does NOT catch exceptions — it lets them propagate so the pipeline's handler has full context. This matches the existing fault-tolerant design (see the boilerplate try/except in `Pipeline._process_file_once`).

### 5. Do NOT add an "artifacts" step to StateStore

`state.py` `update_step()` dynamically constructs `f"{step}_ok"` as the SQL column name. There is no `artifacts_ok` column and we don't modify the schema. Artifact writing is auxiliary, not a pipeline stage.

### 6. figures.jsonl at artifact root, not inside figures/

Per-document layout (host path `./data/artifacts/{file_id}`; container path `/app/data/artifacts/{file_id}`):
```
data/artifacts/{file_id}/
├── document.md       ← raw LlamaIndex markdown in Phase 1 (written from raw_output)
├── figures.jsonl     ← one JSON object per line (empty file in Phase 1)
└── figures/          ← image files (empty dir in Phase 1; created only when figures exist)
```

### 7. Allow backends to cache parse results

`parse_text()` and `extract_figures()` are separate methods in Phase 1. TODO (Phase 2): allow internal caching or introduce a combined `parse()` result to avoid double work.

---

## New Files

### `src/parser/backend.py` — ABC + artifact data models

Defines:
- `BlockType` — `Enum` (string-valued): `heading`, `paragraph`, `list_item`, `caption`, `figure_ref`, `table`
- `TextBlock` — dataclass: `block_type: BlockType`, `text: str`, `page: int | None`, `level: int | None` (heading depth), `bbox: list[float] | None`
- `FigureRecord` — dataclass: `figure_id: str`, `page: int`, `bbox: list[float] | None` (documented order, e.g. `[x0, y0, x1, y1]`), `caption_text: str | None`, `section_path: list[str]` (e.g. `["US Rates", "Term Premium"]`), `image_path: str | None` (relative to artifact dir), `content_hash: str | None`
- `ConfidenceResult` — dataclass: `score: float` (0–1), `status: Literal["PASS","REPAIR","FALLBACK"]` or `Enum`, `reasons: list[str]`
- `TextParseResult` — dataclass: `blocks: list[TextBlock]`, `raw_output: str | None`
- `ParserBackend` — ABC with three abstract methods:
  - `parse_text(pdf_path: Path) -> TextParseResult`
  - `extract_figures(pdf_path: Path) -> list[FigureRecord]`
  - `confidence(blocks: list[TextBlock], figures: list[FigureRecord]) -> ConfidenceResult`

### `src/parser/llamaindex_backend.py` — concrete ParserBackend wrapping LlamaIndexParser

- Constructor takes a `LlamaIndexParser` instance (not an api_key — keeps key knowledge in pipeline init only)
- `parse_text()`: calls `self._parser.parse(pdf_path)`. If markdown is empty/None/whitespace-only (`if not markdown or not markdown.strip()`), raises `ValueError` using the underlying parse error when present (to preserve existing fatal-path messaging). Otherwise returns `TextParseResult(blocks=[TextBlock(BlockType.PARAGRAPH, markdown)], raw_output=markdown)`.
- `extract_figures()`: returns `[]` immediately. LlamaIndex is text-only. No parser call made.
- `confidence()`: returns `ConfidenceResult(score=1.0, status="PASS", reasons=[])`. No internal signal available.

### `src/parser/artifacts.py` — artifact writing

- `blocks_to_markdown(blocks: list[TextBlock]) -> str` — shared reconstruction function. Heading → `#`/`##`/`###` prefix (define behavior if `level` is None, e.g. default to `#` or treat as paragraph). List item → `- ` prefix. Everything else → plain text. Skip empty `text` blocks. Blocks separated by blank lines. Used both by `write_artifacts` (when raw_output is None) and by pipeline.py as the fallback for the extraction chain.
- `write_artifacts(artifact_dir: Path, text_result: TextParseResult, figures: list[FigureRecord]) -> None`:
  - `mkdir(parents=True, exist_ok=True)` on artifact_dir (same pattern as `StateStore._ensure_db`)
  - Writes `document.md`: uses `raw_output` if set, otherwise `blocks_to_markdown(blocks)`; write UTF-8 with trailing newline
  - Writes `figures.jsonl`: one JSON object per FigureRecord. Empty file if no figures (the file is part of the contract — always present)
  - `figures.jsonl` is UTF-8; when figures exist, each line ends with `\n` and the file ends with a trailing newline
  - Creates `figures/` subdirectory only if there are figures with image_path set
  - Does NOT catch exceptions — caller (pipeline) handles them

---

## Modified Files

### `src/parser/__init__.py`

Replace current exports. Keep `LlamaIndexParser` exported (don't break any external consumers). Add: `ParserBackend`, `LlamaIndexBackend`, `TextBlock`, `TextParseResult`, `FigureRecord`, `ConfidenceResult`, `BlockType`, `write_artifacts`, `blocks_to_markdown`.

### `src/config.py`

Add one field after `state_db_path`:
```python
artifact_base_dir: Path = Field(
    default=Path("/app/data/artifacts"),
    description="Base directory for per-document artifact output",
)
```
Follows identical pattern to `state_db_path`. `/app/data` is already a Docker volume. No Dockerfile or docker-compose changes needed. TODO: if a `data_dir` already exists, default to `data_dir / "artifacts"` instead of a hard-coded path.

### `src/pipeline.py`

Three surgical changes only. The extraction chain (Step 3 onward) is completely untouched.

**Imports:** Replace `from src.parser import LlamaIndexParser` with imports of `LlamaIndexParser`, `LlamaIndexBackend`, `write_artifacts`, `blocks_to_markdown`.

**Init:** Replace:
```python
self.parser = LlamaIndexParser(api_key=settings.llamaindex_api_key)
```
With:
```python
self.backend = LlamaIndexBackend(
    parser=LlamaIndexParser(api_key=settings.llamaindex_api_key)
)
```

**Parse step:** Replace the `self.parser.parse()` / `parse_result.markdown` block with:
```python
# Step 2: Parse PDF
self.state.update_step(file_id, "parse", False, ProcessingStatus.PARSING)
try:
    text_result = self.backend.parse_text(file_path)
    figures = self.backend.extract_figures(file_path)
except Exception as e:
    message = f"Parse failed: {e}"
    log.error("PDF parsing failed", error=str(e))
    self.state.update_step(file_id, "parse", False, error_message=message)
    self.state.mark_failed(file_id, message)
    return ProcessingStatus.FAILED, message

self.state.update_step(file_id, "parse", True)

# Write artifacts (non-fatal — do not add a state step)
try:
    artifact_dir = self.settings.artifact_base_dir / file_id
    write_artifacts(artifact_dir, text_result, figures)
    log.info("Artifacts written", artifact_dir=str(artifact_dir))
except Exception as e:
    log.warning("Artifact writing failed", error=str(e))

# Log confidence (informational only in Phase 1 — not acted upon)
confidence = self.backend.confidence(text_result.blocks, figures)
log.info("Parse confidence", score=confidence.score, status=confidence.status, reasons=confidence.reasons)

# Extraction chain receives identical text to today.
# raw_output is LlamaIndex's markdown; the fallback is for other backends.
# TODO (Phase 2): replace fallback with section-aware reconstruction
markdown = text_result.raw_output or blocks_to_markdown(text_result.blocks)
```

Everything from `# Step 3: Strip boilerplate` onward stays byte-for-byte identical.

---

## Tests

Follow existing conventions: plain `test_` functions, no unittest.mock, hand-written fakes (see `FakeClient` in `tests/test_boilerplate_safeguard.py`). Use pytest's `tmp_path` fixture for filesystem tests (it's a pytest primitive, not a custom fixture).

### `tests/test_llamaindex_backend.py`

Fake: `FakeLlamaIndexParser` with a call counter (validates `extract_figures` doesn't trigger a second parse call).

- `test_parse_text_returns_raw_output` — happy path, asserts `raw_output == markdown` and blocks is a single PARAGRAPH block
- `test_parse_text_raises_on_empty_markdown` — empty markdown → ValueError with error message
- `test_parse_text_raises_on_whitespace_markdown` — whitespace-only markdown → ValueError
- `test_extract_figures_returns_empty_without_parsing` — asserts `[]` and parser call count stays at 0
- `test_confidence_returns_pass` — returns score 1.0, status PASS, empty reasons

### `tests/test_artifacts.py`

- `test_write_document_md_from_raw_output` — raw_output is set; document.md content matches it exactly
- `test_write_document_md_from_blocks` — raw_output is None; document.md is reconstructed correctly (heading levels, list markers); includes list + heading cases
- `test_figures_jsonl_empty_when_no_figures` — file exists, 0 lines
- `test_figures_jsonl_serializes_correctly` — one FigureRecord, verify JSON fields including section_path as list
- `test_artifact_dir_created_if_missing` — passes a non-existent path, no error
- `test_exceptions_propagate` — create an unwritable temp dir (e.g., chmod 0) and attempt to write inside it; verify exception is NOT swallowed

---

## Verification

1. Run `pytest tests/` — all existing tests pass unchanged, new tests pass.
2. Run `python -c "from src.parser import ParserBackend, LlamaIndexBackend; print('imports ok')"` — confirms no circular imports or missing deps.
3. Smoke-test artifact layout: after a single pipeline run, verify `data/artifacts/{file_id}/document.md` exists and contains the LlamaIndex markdown, and `figures.jsonl` exists (empty).
4. Confirm extraction output in Supabase is identical to before the refactor for the same input PDF. This should hold because the extraction chain receives the exact same LlamaIndex markdown, but verify to be safe.

---

## What is NOT touched

- `src/parser/llamaindex.py` — the HTTP client. Wrapped, not modified.
- `src/extraction/*` — all extraction modules. They receive the same `clean_text` string.
- `src/storage/*` — state.py schema unchanged, supabase.py unchanged.
- `docker-compose.yml`, `Dockerfile` — `/app/data` volume already covers artifacts.
- `config/models.yaml` — model config is orthogonal to parsing.
- `src/llm.py` — unified LLM client unchanged.
