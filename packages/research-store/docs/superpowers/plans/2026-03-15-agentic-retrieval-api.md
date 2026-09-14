# Agentic Retrieval API Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add date-range filtering to `HybridSearchEngine` and a thin `api.py` module so LLM agents can use the search engine as a retrieval primitive.

**Architecture:** The search engine gains `date_from`/`date_to` parameters. A new `api.py` wraps it with ISO date validation and plain-dict returns. A `tool_schema.json` describes the tools for agent consumption. Filtering uses a single set-intersection approach applied to both lexical and semantic paths.

**Tech Stack:** Python 3.10+, sqlite3, numpy, pytest

**Spec:** `docs/superpowers/specs/2026-03-15-agentic-retrieval-api-design.md`

---

## Chunk 1: Date-Range Filtering in HybridSearchEngine

### Task 1: Add `source_date` index to storage

**Files:**
- Modify: `distill_tool/storage.py:97-102` (after existing indexes in `init_db`)
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing test for source_date index**

In `tests/test_storage.py`, add:

```python
def test_init_db_creates_source_date_index(tmp_path: Path) -> None:
    db_path = tmp_path / "chunks.sqlite"
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(chunks)").fetchall()
        }

    assert "idx_chunks_source_date" in indexes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage.py::test_init_db_creates_source_date_index -v`
Expected: FAIL — index does not exist

- [ ] **Step 3: Add index to `init_db()`**

In `distill_tool/storage.py`, after the `idx_chunks_text_hash` index creation (line ~102), add:

```python
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunks_source_date
            ON chunks(source_date)
            """
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_storage.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add distill_tool/storage.py tests/test_storage.py
git commit -m "feat: add source_date index to chunks table"
```

---

### Task 2: Add `_chunk_ids_for_date_range()` helper to `HybridSearchEngine`

**Files:**
- Modify: `distill_tool/search.py:367-370` (after `_chunk_ids_for_run`)
- Test: `tests/test_search_date_filter.py` (new)

- [ ] **Step 1: Write failing tests for the date-range helper**

Create `tests/test_search_date_filter.py`:

```python
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

from distill_tool.search import HybridSearchEngine


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_dated_corpus(tmp_path: Path) -> tuple[Path, Path]:
    """Build a corpus with chunks spanning different source_date values, including NULLs."""
    db_path = tmp_path / "chunks.sqlite"
    npz_path = tmp_path / "embeddings.npz"

    rows = [
        ("c-jan", "run-1", "jan.md", "2025-01-15", 1, 0, "CPI consensus was above expectations"),
        ("c-feb", "run-1", "feb.md", "2025-02-10", 1, 0, "Fed rate cut expectations shifted lower"),
        ("c-mar", "run-1", "mar.md", "2025-03-05", 1, 0, "Labor market showed signs of softening"),
        ("c-null", "run-1", "old.md", None, 1, 0, "Undated legacy document about inflation"),
    ]

    keywords = [{"term": "test", "source": "dictionary", "score": 1.0}]
    kw_json = json.dumps(keywords)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                model_name TEXT NOT NULL,
                embedding_dim INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_date TEXT,
                dictionary_path TEXT,
                params_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                source_path TEXT,
                source_date TEXT,
                page_number INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                text_hash TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE chunk_keywords (
                chunk_id TEXT NOT NULL,
                term TEXT NOT NULL,
                source TEXT NOT NULL,
                score REAL NOT NULL,
                PRIMARY KEY (chunk_id, term, source)
            )
            """
        )
        conn.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, text)")
        conn.execute("CREATE VIRTUAL TABLE keyword_fts USING fts5(chunk_id UNINDEXED, terms)")
        conn.execute(
            "INSERT INTO runs (run_id, model_name, embedding_dim, source, params_json) VALUES (?, ?, ?, ?, ?)",
            ("run-1", "test", 3, "test", "{}"),
        )
        for chunk_id, run_id, source_path, source_date, page, idx, text in rows:
            text_hash = _hash(text)
            conn.execute(
                """
                INSERT INTO chunks (chunk_id, run_id, source_path, source_date, page_number, chunk_index, text, keywords_json, text_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (chunk_id, run_id, source_path, source_date, page, idx, text, kw_json, text_hash),
            )
            conn.execute("INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)", (chunk_id, text))
            conn.execute("INSERT INTO keyword_fts (chunk_id, terms) VALUES (?, ?)", (chunk_id, "test"))
            conn.execute(
                "INSERT INTO chunk_keywords (chunk_id, term, source, score) VALUES (?, ?, ?, ?)",
                (chunk_id, "test", "dictionary", 1.0),
            )
        conn.commit()

    np.savez(
        npz_path,
        chunk_ids=np.array(["c-jan", "c-feb", "c-mar", "c-null"]),
        embeddings=np.array(
            [
                [0.8, 0.1, 0.1],
                [0.1, 0.8, 0.1],
                [0.1, 0.1, 0.8],
                [0.5, 0.3, 0.2],
            ],
            dtype="float32",
        ),
    )
    return db_path, npz_path


def test_chunk_ids_for_date_range_returns_none_when_no_filter(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range(None, None)
    assert result is None


def test_chunk_ids_for_date_range_filters_by_date_from(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range("2025-02-01", None)
    assert result == {"c-feb", "c-mar"}


def test_chunk_ids_for_date_range_filters_by_date_to(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range(None, "2025-02-01")
    assert result == {"c-jan"}


def test_chunk_ids_for_date_range_filters_by_both(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range("2025-01-01", "2025-01-31")
    assert result == {"c-jan"}


def test_chunk_ids_for_date_range_excludes_null_dates(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    # Wide range that would include everything — but NULL dates are still excluded
    result = engine._chunk_ids_for_date_range("2020-01-01", "2030-01-01")
    assert "c-null" not in result
    assert result == {"c-jan", "c-feb", "c-mar"}


def test_chunk_ids_for_date_range_returns_empty_set_for_no_matches(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)
    result = engine._chunk_ids_for_date_range("2099-01-01", "2099-12-31")
    assert result == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_search_date_filter.py -v`
Expected: FAIL — `_chunk_ids_for_date_range` does not exist

- [ ] **Step 3: Implement `_chunk_ids_for_date_range()`**

In `distill_tool/search.py`, add this method to `HybridSearchEngine` after `_chunk_ids_for_run()` (line ~370):

```python
    def _chunk_ids_for_date_range(
        self, date_from: str | None, date_to: str | None
    ) -> set[str] | None:
        """Return chunk IDs within the date range, or None if no filtering needed.

        Chunks with NULL source_date are excluded from date-filtered queries.
        """
        if date_from is None and date_to is None:
            return None
        sql = "SELECT chunk_id FROM chunks WHERE source_date IS NOT NULL"
        params: list[str] = []
        if date_from is not None:
            sql += " AND source_date >= ?"
            params.append(date_from)
        if date_to is not None:
            sql += " AND source_date <= ?"
            params.append(date_to)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return {str(row[0]) for row in rows}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_search_date_filter.py -v`
Expected: all 6 tests pass

- [ ] **Step 5: Commit**

```bash
git add distill_tool/search.py tests/test_search_date_filter.py
git commit -m "feat: add _chunk_ids_for_date_range helper to HybridSearchEngine"
```

---

### Task 3: Wire date filtering into `search()` and `_semantic_scores()`

**Files:**
- Modify: `distill_tool/search.py:48-58` (search signature), `distill_tool/search.py:264-303` (_semantic_scores)
- Test: `tests/test_search_date_filter.py`

- [ ] **Step 1: Write failing tests for date-filtered search**

Append to `tests/test_search_date_filter.py`:

```python
def test_search_with_date_range_excludes_out_of_range(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    results = engine.search(
        query="CPI consensus expectations inflation",
        limit=10,
        date_from="2025-01-01",
        date_to="2025-01-31",
        semantic_weight=0.0,
    )

    chunk_ids = {r.chunk_id for r in results}
    # Only c-jan falls in January 2025
    assert "c-jan" in chunk_ids
    assert "c-feb" not in chunk_ids
    assert "c-mar" not in chunk_ids
    assert "c-null" not in chunk_ids


def test_search_without_date_filter_includes_all(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    results = engine.search(
        query="CPI consensus expectations inflation labor market Fed rate",
        limit=10,
        semantic_weight=0.0,
    )

    chunk_ids = {r.chunk_id for r in results}
    # Without date filter, undated chunks are included
    assert len(chunk_ids) >= 1


def test_search_date_filter_with_zero_matches_returns_empty(tmp_path: Path) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    results = engine.search(
        query="CPI consensus",
        limit=10,
        date_from="2099-01-01",
        date_to="2099-12-31",
        semantic_weight=0.0,
    )

    assert results == []


def test_search_date_filter_applies_to_semantic_path(tmp_path: Path, monkeypatch) -> None:
    db_path, npz_path = _build_dated_corpus(tmp_path)
    engine = HybridSearchEngine(db_path=db_path, npz_path=npz_path)

    # Use a fake model that returns the query as a unit vector
    class FakeModel:
        def embed(self, texts):
            return np.array([[0.8, 0.1, 0.1]], dtype="float32")

    monkeypatch.setattr(engine, "_get_model", lambda: FakeModel())

    results = engine.search(
        query="CPI",
        limit=10,
        date_from="2025-01-01",
        date_to="2025-01-31",
        keyword_weight=0.0,
        semantic_weight=1.0,
    )

    chunk_ids = {r.chunk_id for r in results}
    # Semantic search must also be date-filtered
    assert "c-feb" not in chunk_ids
    assert "c-mar" not in chunk_ids
    assert "c-null" not in chunk_ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_search_date_filter.py::test_search_with_date_range_excludes_out_of_range tests/test_search_date_filter.py::test_search_date_filter_with_zero_matches_returns_empty tests/test_search_date_filter.py::test_search_date_filter_applies_to_semantic_path -v`
Expected: FAIL — `search()` does not accept `date_from`/`date_to`

- [ ] **Step 3: Add `date_from`/`date_to` to `search()` signature and wire filtering**

In `distill_tool/search.py`, modify the `search()` method signature (line ~48) to add `date_from` and `date_to` after `run_id`:

```python
    def search(
        self,
        query: str,
        limit: int = 10,
        run_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword_weight: float = 0.55,
        semantic_weight: float = 0.45,
        min_lexical_score: float = 0.05,
        semantic_tail_mode: str = "filter",
        semantic_tail_penalty: float = 0.25,
    ) -> list[SearchResult]:
```

After the early return check (`if not query or limit <= 0: return []`), add the date filtering logic:

```python
        # Compute allowed chunk IDs for date filtering
        date_allowed = self._chunk_ids_for_date_range(date_from, date_to)
```

**After the weight-rebalancing fallback block** (after line ~93, the `total_weight` normalization), add the lexical intersection. This placement is critical — `lexical_scores` can be (re)computed at two points: the primary call at line ~69 and the fallback at line ~77. Placing the filter after both ensures neither path leaks unfiltered results:

```python
        # Apply date filter to lexical results (must be after the fallback block)
        if date_allowed is not None and lexical_scores:
            lexical_scores = {k: v for k, v in lexical_scores.items() if k in date_allowed}
```

Update the `_semantic_scores` call to pass the allowed set:

```python
        if semantic_weight > 0.0:
            semantic_scores = self._semantic_scores(
                query, run_id=run_id, limit=semantic_candidate_limit,
                allowed_chunk_ids=date_allowed,
            )
```

Now modify `_semantic_scores`. Update its signature (line ~264):

```python
    def _semantic_scores(
        self, query: str, run_id: str | None, limit: int,
        allowed_chunk_ids: set[str] | None = None,
    ) -> dict[str, float]:
```

**Replace lines 279-293** (the `if run_id: ... else: ...` branched masking/partitioning block) with the following unified mask approach. Keep lines 264-278 (guard checks, model loading, similarity computation) and lines 295-303 (sorting and normalization) unchanged:

```python
        # --- BEGIN REPLACEMENT (replaces lines 279-293) ---
        if run_id:
            allowed_ids = self._chunk_ids_for_run(run_id)
            if not allowed_ids:
                return {}
            mask = np.array([chunk_id in allowed_ids for chunk_id in self._embedding_chunk_ids], dtype=bool)
        else:
            mask = np.ones(len(self._embedding_chunk_ids), dtype=bool)

        if allowed_chunk_ids is not None:
            date_mask = np.array(
                [chunk_id in allowed_chunk_ids for chunk_id in self._embedding_chunk_ids], dtype=bool
            )
            mask = mask & date_mask

        if not np.any(mask):
            return {}

        idxs = np.where(mask)[0]
        subset_scores = similarities[idxs]
        top_n = min(limit, subset_scores.shape[0])
        top_local = np.argpartition(subset_scores, -top_n)[-top_n:]
        top_idxs = idxs[top_local]
        # --- END REPLACEMENT ---
        # Lines 295-303 (top_pairs sorting and return dict) remain unchanged.
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `python -m pytest tests/test_search_date_filter.py tests/test_search.py -v`
Expected: all pass (both new date-filter tests and existing search tests)

- [ ] **Step 5: Commit**

```bash
git add distill_tool/search.py tests/test_search_date_filter.py
git commit -m "feat: wire date_from/date_to filtering into search() and _semantic_scores()"
```

---

## Chunk 2: API Module, Tool Schema, and Package Integration

> **Prerequisite:** Chunk 1 (Tasks 1-3) must be completed first. `api.search()` depends on the `date_from`/`date_to` parameters added to `HybridSearchEngine.search()` in Task 3.

### Task 4: Create `api.py` with `corpus_info()`

**Files:**
- Create: `distill_tool/api.py`
- Test: `tests/test_api.py` (new)

- [ ] **Step 1: Write failing tests for `corpus_info()`**

Create `tests/test_api.py`:

```python
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from distill_tool.storage import init_db


def test_corpus_info_on_empty_database(tmp_path: Path) -> None:
    from distill_tool.api import corpus_info

    db_path = tmp_path / "chunks.sqlite"
    init_db(db_path)

    info = corpus_info(str(db_path))

    assert info["total_chunks"] == 0
    assert info["total_runs"] == 0
    assert info["date_range"] is None
    assert info["sources"] == []


def test_corpus_info_returns_correct_aggregates(tmp_path: Path) -> None:
    from distill_tool.api import corpus_info

    db_path = tmp_path / "chunks.sqlite"
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, model_name, embedding_dim, source, params_json) VALUES (?, ?, ?, ?, ?)",
            ("r1", "test", 3, "test", "{}"),
        )
        for chunk_id, source_date, source_path in [
            ("c1", "2025-01-15", "jan.md"),
            ("c2", "2025-03-10", "mar.md"),
            ("c3", None, "old.md"),
        ]:
            conn.execute(
                """
                INSERT INTO chunks (chunk_id, run_id, source_path, source_date, page_number, chunk_index, text, keywords_json, text_hash)
                VALUES (?, ?, ?, ?, 1, 0, 'text', '[]', ?)
                """,
                (chunk_id, "r1", source_path, source_date, chunk_id),
            )
        conn.commit()

    info = corpus_info(str(db_path))

    assert info["total_chunks"] == 3
    assert info["total_runs"] == 1
    assert info["date_range"] == {"min": "2025-01-15", "max": "2025-03-10"}
    assert sorted(info["sources"]) == ["jan.md", "mar.md", "old.md"]


def test_corpus_info_null_dates_returns_none_date_range(tmp_path: Path) -> None:
    from distill_tool.api import corpus_info

    db_path = tmp_path / "chunks.sqlite"
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, model_name, embedding_dim, source, params_json) VALUES (?, ?, ?, ?, ?)",
            ("r1", "test", 3, "test", "{}"),
        )
        conn.execute(
            """
            INSERT INTO chunks (chunk_id, run_id, source_path, source_date, page_number, chunk_index, text, keywords_json, text_hash)
            VALUES ('c1', 'r1', 'x.md', NULL, 1, 0, 'text', '[]', 'h1')
            """
        )
        conn.commit()

    info = corpus_info(str(db_path))

    assert info["date_range"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL — `distill_tool.api` does not exist

- [ ] **Step 3: Implement `corpus_info()` in `api.py`**

Create `distill_tool/api.py`:

```python
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from distill_tool.search import HybridSearchEngine, SearchResult

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(value: str | None, name: str) -> None:
    if value is not None and not _ISO_DATE_RE.match(value):
        raise ValueError(f"{name} must be ISO format YYYY-MM-DD, got: {value!r}")


def corpus_info(db_path: str) -> dict:
    """Return metadata about the corpus.

    Returns dict with keys:
        total_chunks, total_runs, date_range (dict with min/max or None),
        sources (list of distinct source_path strings)
    """
    with sqlite3.connect(db_path) as conn:
        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        date_row = conn.execute(
            "SELECT MIN(source_date), MAX(source_date) FROM chunks WHERE source_date IS NOT NULL"
        ).fetchone()
        sources = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT source_path FROM chunks WHERE source_path IS NOT NULL ORDER BY source_path"
            ).fetchall()
        ]
    return {
        "total_chunks": total_chunks,
        "total_runs": total_runs,
        "date_range": {"min": date_row[0], "max": date_row[1]} if date_row[0] else None,
        "sources": sources,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -v`
Expected: all 3 pass

- [ ] **Step 5: Commit**

```bash
git add distill_tool/api.py tests/test_api.py
git commit -m "feat: add corpus_info() to api module"
```

---

### Task 5: Add `api.search()` with date validation

**Files:**
- Modify: `distill_tool/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing tests for `api.search()`**

Append to `tests/test_api.py`:

```python
import hashlib

import numpy as np


def _build_api_test_corpus(tmp_path: Path) -> tuple[str, str]:
    """Build a minimal corpus for API tests. Returns (db_path, npz_path) as strings."""
    db_path = tmp_path / "chunks.sqlite"
    npz_path = tmp_path / "embeddings.npz"

    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO runs (run_id, model_name, embedding_dim, source, params_json) VALUES (?, ?, ?, ?, ?)",
            ("r1", "test", 3, "test", "{}"),
        )
        keywords = json.dumps([{"term": "cpi", "source": "dictionary", "score": 1.0}])
        text = "CPI consensus was above expectations in January"
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        conn.execute(
            """
            INSERT INTO chunks (chunk_id, run_id, source_path, source_date, page_number, chunk_index, text, keywords_json, text_hash)
            VALUES ('c1', 'r1', 'jan.md', '2025-01-15', 1, 0, ?, ?, ?)
            """,
            (text, keywords, text_hash),
        )
        conn.execute("INSERT INTO chunks_fts (chunk_id, text) VALUES ('c1', ?)", (text,))
        conn.execute("INSERT INTO keyword_fts (chunk_id, terms) VALUES ('c1', 'cpi')")
        conn.execute(
            "INSERT INTO chunk_keywords (chunk_id, term, source, score) VALUES ('c1', 'cpi', 'dictionary', 1.0)"
        )
        conn.commit()

    np.savez(
        npz_path,
        chunk_ids=np.array(["c1"]),
        embeddings=np.array([[0.8, 0.1, 0.1]], dtype="float32"),
    )
    return str(db_path), str(npz_path)


def test_api_search_returns_list_of_dicts(tmp_path: Path) -> None:
    from distill_tool.api import search

    db_path, npz_path = _build_api_test_corpus(tmp_path)
    results = search("CPI consensus", db_path=db_path, npz_path=npz_path, limit=5)

    assert isinstance(results, list)
    assert len(results) >= 1
    result = results[0]
    assert isinstance(result, dict)
    expected_keys = {
        "chunk_id", "source_path", "source_date", "page_number",
        "text", "keywords", "lexical_score", "semantic_score", "hybrid_score",
    }
    assert set(result.keys()) == expected_keys
    # Internal fields should NOT be present
    assert "run_id" not in result
    assert "chunk_index" not in result


def test_api_search_validates_date_format(tmp_path: Path) -> None:
    from distill_tool.api import search

    db_path, npz_path = _build_api_test_corpus(tmp_path)

    with pytest.raises(ValueError, match="date_from must be ISO format"):
        search("CPI", db_path=db_path, date_from="January 2025")

    with pytest.raises(ValueError, match="date_to must be ISO format"):
        search("CPI", db_path=db_path, date_to="2025/01/31")


def test_api_search_passes_date_filters(tmp_path: Path) -> None:
    from distill_tool.api import search

    db_path, npz_path = _build_api_test_corpus(tmp_path)

    # Should find the chunk — it's dated 2025-01-15
    results = search(
        "CPI consensus",
        db_path=db_path,
        npz_path=npz_path,
        date_from="2025-01-01",
        date_to="2025-01-31",
    )
    assert len(results) >= 1

    # Should NOT find the chunk — wrong date range
    results = search(
        "CPI consensus",
        db_path=db_path,
        npz_path=npz_path,
        date_from="2025-06-01",
        date_to="2025-06-30",
    )
    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py::test_api_search_returns_list_of_dicts tests/test_api.py::test_api_search_validates_date_format tests/test_api.py::test_api_search_passes_date_filters -v`
Expected: FAIL — `search` not importable from `distill_tool.api`

- [ ] **Step 3: Implement `api.search()`**

Add to `distill_tool/api.py`:

```python
def search(
    query: str,
    *,
    db_path: str,
    npz_path: str | None = None,
    limit: int = 10,
    date_from: str | None = None,
    date_to: str | None = None,
    run_id: str | None = None,
    keyword_weight: float = 0.55,
    semantic_weight: float = 0.45,
) -> list[dict]:
    """Search the distilled research corpus.

    Returns list of dicts with keys:
        chunk_id, source_path, source_date, page_number,
        text, keywords, lexical_score, semantic_score, hybrid_score
    """
    _validate_date(date_from, "date_from")
    _validate_date(date_to, "date_to")

    engine = HybridSearchEngine(
        db_path=Path(db_path),
        npz_path=Path(npz_path) if npz_path else None,
    )
    results: list[SearchResult] = engine.search(
        query=query,
        limit=limit,
        run_id=run_id,
        date_from=date_from,
        date_to=date_to,
        keyword_weight=keyword_weight,
        semantic_weight=semantic_weight,
    )
    return [
        {
            "chunk_id": r.chunk_id,
            "source_path": r.source_path,
            "source_date": r.source_date,
            "page_number": r.page_number,
            "text": r.text,
            "keywords": r.keywords,
            "lexical_score": round(r.lexical_score, 6),
            "semantic_score": round(r.semantic_score, 6),
            "hybrid_score": round(r.hybrid_score, 6),
        }
        for r in results
    ]
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `python -m pytest tests/test_api.py -v`
Expected: all 6 pass

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `python -m pytest tests/ -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add distill_tool/api.py tests/test_api.py
git commit -m "feat: add api.search() with ISO date validation"
```

---

### Task 6: Create tool schema and update package exports

**Files:**
- Create: `distill_tool/tool_schema.json`
- Modify: `distill_tool/__init__.py`

- [ ] **Step 1: Create `tool_schema.json`**

Create `distill_tool/tool_schema.json`:

```json
[
  {
    "name": "research_search",
    "description": "Search the indexed research corpus for specific topics, data points, or market themes. Returns ranked text chunks with source attribution and dates. Use focused, narrow queries — not full analytical questions. For complex topics, call multiple times with different angles and combine the results yourself.",
    "parameters": {
      "type": "object",
      "required": ["query"],
      "properties": {
        "query": {
          "type": "string",
          "description": "A focused search query targeting a specific concept, data point, or theme. Examples: 'CPI print January 2025', 'Fed dot plot rate expectations', 'labor market softening signals'. Do NOT pass full analytical questions."
        },
        "date_from": {
          "type": "string",
          "description": "ISO date lower bound, inclusive (e.g. '2025-01-01'). Omit to search all dates."
        },
        "date_to": {
          "type": "string",
          "description": "ISO date upper bound, inclusive (e.g. '2025-01-31'). Omit to search all dates."
        },
        "limit": {
          "type": "integer",
          "description": "Max results to return. Default 10. Use 5 for narrow queries, 15-20 for broad sweeps.",
          "default": 10
        }
      }
    }
  },
  {
    "name": "research_corpus_info",
    "description": "Returns metadata about the research corpus: total chunks, date range covered, and list of sources. Call this first to understand what data is available before searching.",
    "parameters": {
      "type": "object",
      "properties": {}
    }
  }
]
```

- [ ] **Step 2: Update `__init__.py` exports**

Replace the contents of `distill_tool/__init__.py` with:

```python
from distill_tool.pipeline import distill_file, distill_markdown
from distill_tool.search import HybridSearchEngine
from distill_tool.api import search, corpus_info

__all__ = ["distill_file", "distill_markdown", "HybridSearchEngine", "search", "corpus_info"]
```

- [ ] **Step 3: Verify imports work**

Run: `python -c "from distill_tool import search, corpus_info; print('OK')"`
Expected: prints `OK`

- [ ] **Step 4: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add distill_tool/tool_schema.json distill_tool/__init__.py
git commit -m "feat: add tool schema and export search/corpus_info from package"
```
