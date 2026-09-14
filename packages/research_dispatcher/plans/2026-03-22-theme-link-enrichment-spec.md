# Theme Link Enrichment Spec

Last updated: 2026-03-22 America/New_York

## Purpose

Define the missing middle stage between:

1. `research_parser`
2. theme-link enrichment
3. `research_dispatcher`

The goal of this stage is to own `research_theme_links` generation without pushing that responsibility into single-document parsing or into the final report-generation path.

## Recommendation

Build a separate service/job called `research_theme_linker`.

Opinionated recommendation:

- v1 should infer document-local links between normalized themes for one document at a time
- it should write into the existing `research_theme_links` table
- it should run after normalized themes exist and before `research_dispatcher` ever depends on links

Do not start with a cross-document graph.

Reason:

- the current schema for `research_theme_links` is document-scoped
- parser output already contains enough document-local structure to support a first useful version
- cross-document linkage is a different problem and should get a different schema later if needed

## System Boundary

### `research_parser` owns

- `parsed_research`
- `research_themes`
- `research_theme_excerpts`
- top-level document metadata columns
- `document_hash`, `theme_count`, `trade_count`

### `research_theme_linker` owns

- deciding when a document is ready for link inference
- reading normalized themes and excerpts
- inferring theme-to-theme relationships for a single document
- writing `research_theme_links`
- tracking link-generation status, version, and errors

### `research_dispatcher` owns

- consuming enriched data for reporting and synthesis
- ignoring links until it has a clear product use for them
- never being responsible for generating or persisting `research_theme_links`

## V1 Scope

V1 should support:

- document-local related-theme inference
- idempotent reruns
- batch processing of newly normalized documents
- backfill processing for older normalized documents

V1 should not support:

- cross-document graph edges
- global topic ontology
- user-facing UI for link curation
- parser-time link extraction

## Why This Stage Exists

Putting theme links in the parser is the wrong boundary because parsing should stay focused on document-local extraction.

Putting theme links in `research_dispatcher` is also the wrong default because dispatcher is currently a read/report/send workflow, not a durable enrichment writer.

The missing middle stage solves that:

- parser writes stable normalized facts
- linker adds higher-order structure on top of those facts
- dispatcher consumes the enriched graph only when needed

## Data Dependencies

The linker depends on these inputs being present and trustworthy:

- `parsed_research.id`
- `parsed_research.document_hash`
- `parsed_research.theme_count`
- `research_themes` rows for that `research_id`
- `research_theme_excerpts` rows for those theme ids

Optional but useful inputs:

- `research_themes.relevance`
- `research_themes.classification`
- `research_themes.strength`
- `research_themes.confidence`
- `research_themes.directionality`
- `research_themes.argument_structure`
- `research_themes.context`

Relevant parser references:

- [src/storage/supabase.py](/Users/ncdial/devwork/research_parser/src/storage/supabase.py)
- [src/extraction/models.py](/Users/ncdial/devwork/research_parser/src/extraction/models.py)

## Readiness Rule

A document is eligible for link inference only when:

1. `document_hash IS NOT NULL`
2. `theme_count > 0`
3. `count(research_themes.id) = parsed_research.theme_count`

If those conditions are not met:

- skip the document
- leave it for a later pass

This mirrors the same mixed-mode safety issue already identified for dispatcher.

## Proposed Schema Additions

The existing `research_theme_links` table is enough for storing links, but it is not enough for observability or idempotent job control.

### Keep

- `research_theme_links`

### Add

A new run-state table:

```sql
CREATE TABLE research_theme_link_runs (
    research_id BIGINT PRIMARY KEY REFERENCES parsed_research(id) ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    linker_version TEXT NOT NULL,
    status TEXT NOT NULL,
    theme_count INTEGER NOT NULL DEFAULT 0,
    link_count INTEGER NOT NULL DEFAULT 0,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_text TEXT NULL
);

CREATE INDEX idx_research_theme_link_runs_status
    ON research_theme_link_runs(status);

CREATE INDEX idx_research_theme_link_runs_hash_version
    ON research_theme_link_runs(document_hash, linker_version);
```

### Why a separate run table

- do not overload `parsed_research` with enrichment-specific status columns
- allows versioned reruns
- allows safe detection of stale outputs when logic changes
- keeps parser and linker ownership separated

## Proposed Link Taxonomy

V1 should use a small controlled enum for `research_theme_links.relationship`.

Recommended values:

- `reinforces`
- `depends_on`
- `contradicts`
- `qualifies`
- `drives`

Definitions:

- `reinforces`: both themes support the same core idea
- `depends_on`: one theme relies on the other being true
- `contradicts`: one theme weakens or conflicts with the other
- `qualifies`: one theme narrows, conditions, or scopes the other
- `drives`: one theme is presented as a causal driver of the other

Opinionated recommendation:

- keep the enum small in v1
- avoid an open-ended relationship vocabulary
- treat `explanation` as the place for nuance

## Inference Strategy

Use a hybrid pipeline:

1. deterministic candidate generation
2. deterministic shortcut rules
3. optional LLM adjudication for ambiguous candidate pairs

### Step 1: candidate generation

For a single document:

- fetch all normalized themes
- generate all theme pairs
- if theme counts are small, evaluate all pairs

This is acceptable because per-document theme counts are low enough that pairwise evaluation is cheap.

### Step 2: deterministic shortcut rules

Infer links without an LLM when strong structured evidence exists.

Examples:

- `argument_structure.dependencies` mentioning another theme label
  - emit `depends_on`
- `argument_structure.contradictions` mentioning another theme label
  - emit `contradicts`
- high lexical overlap plus same directionality and same relevance
  - emit `reinforces`

### Step 3: LLM adjudication

For remaining ambiguous pairs:

- provide the two normalized themes
- include compact context, excerpts, directionality, and argument structure
- require exactly one enum relationship or `none`
- require a short explanation suitable for `research_theme_links.explanation`

Opinionated recommendation:

- do not send the full document
- do not ask the model to invent a graph from scratch
- keep the task to pairwise or small-batch classification over already-normalized themes

## Input Contract For The Linker

Per document:

```json
{
  "research_id": 12345,
  "document_hash": "sha256...",
  "document_name": "2026-03-22_JPM_....pdf",
  "source": "JPMorgan",
  "source_date": "2026-03-22",
  "themes": [
    {
      "theme_id": 9001,
      "theme_order": 1,
      "label": "Higher term premium",
      "relevance": ["Rates"],
      "classification": "Forecast",
      "strength": "Primary",
      "confidence": "High",
      "context": "The note argues that...",
      "directionality": {"bearish_rates": 2},
      "argument_structure": {
        "conditionals": ["If inflation remains sticky"],
        "confidence_basis": "Positioning and term premium decomposition",
        "dependencies": ["Sticky inflation"],
        "contradictions": []
      },
      "excerpts": [
        "Investors should expect term premium to rise..."
      ]
    }
  ]
}
```

## Output Contract For The Linker

Per document:

```json
{
  "research_id": 12345,
  "document_hash": "sha256...",
  "linker_version": "v1",
  "links": [
    {
      "from_theme_id": 9001,
      "to_theme_id": 9002,
      "relationship": "drives",
      "explanation": "Sticky inflation is presented as the reason term premium rises."
    }
  ]
}
```

## Write Strategy

For each eligible document:

1. fetch themes and excerpts
2. infer links
3. delete existing `research_theme_links` rows for that `research_id`
4. insert the new set
5. upsert a row in `research_theme_link_runs`

If inference fails:

- do not write partial links
- record the failure in `research_theme_link_runs`

Opinionated recommendation:

- treat per-document writes as replace-all, like the current theme normalization backfill
- this keeps reruns simple and deterministic

## Proposed Workflow

### End-to-end data flow

1. `research_parser`
   - parses PDFs
   - writes `parsed_research`
   - writes `research_themes`
   - writes `research_theme_excerpts`

2. `research_theme_linker`
   - polls for eligible normalized documents
   - infers document-local links
   - writes `research_theme_links`
   - records run state in `research_theme_link_runs`

3. `research_dispatcher`
   - reads documents and normalized themes
   - optionally reads links when a reporting/synthesis use case is added
   - never computes links itself in the durable write path

### Selection query for linker work

The linker should select documents where:

- normalized themes are complete
- and no link run exists
- or the stored `document_hash` differs
- or the stored `linker_version` differs
- or the prior run status is `error`

That gives:

- idempotency
- rerun support when logic changes
- automatic pickup when parser/backfill updates a document

## Deployment Model

### Recommended form

A separate Python 3.11 batch service or scheduled CLI.

Preferred options:

1. long-running poller, like `research_parser`
2. cron-triggered batch command, like `research_dispatcher`

Opinionated recommendation:

- start with a cron-triggered or manually-triggered batch command
- move to a long-running poller only if freshness requirements demand it

Reason:

- lower operational complexity
- easier to test and backfill
- no need to introduce queue infrastructure on day one

## Proposed Tech Stack

Use the same operational stack family already present in the two neighboring systems.

### Core runtime

- Python 3.11
- `supabase-py`
- `pydantic`
- `structlog`
- `tenacity`

### Scheduling

Choose one:

- `APScheduler` if implemented as a service
- `cron` if implemented as a periodic batch job

### Inference

Recommended:

- start with Python rules plus optional LLM adjudication

LLM provider options:

- OpenAI
- Anthropic

Opinionated recommendation:

- use deterministic rules first
- reserve LLM calls for ambiguous cases
- do not make every pair classification an LLM call unless quality data proves it is necessary

### Storage

- Supabase Postgres
- existing normalized theme tables
- existing `research_theme_links`
- new `research_theme_link_runs`

### Packaging

Two acceptable options:

1. a new repo/service: `research_theme_linker`
2. a new package inside `research_parser` or a shared infra repo, but with a separate entrypoint and ownership boundary

Opinionated recommendation:

- give it a separate entrypoint even if it starts in an existing repo
- do not bury it as a side effect in parser or dispatcher

## Proposed Module Layout

If built as its own Python package:

```text
research_theme_linker/
  src/
    main.py
    config.py
    selector.py
    hydrator.py
    linker.py
    rules.py
    llm.py
    writer.py
    models.py
  tests/
    test_rules.py
    test_selector.py
    test_writer.py
    test_end_to_end.py
```

Responsibilities:

- `selector.py`
  - find eligible docs
- `hydrator.py`
  - fetch document + themes + excerpts into one in-memory payload
- `rules.py`
  - deterministic relation heuristics
- `llm.py`
  - constrained pair adjudication
- `linker.py`
  - orchestration and merge of rule-based and LLM results
- `writer.py`
  - replace-all writes plus run-state updates

## Concrete Sketch

This section sketches what the first implementation could look like without locking us into exact code yet.

### Entry point

The first version can be a simple batch command:

```bash
python -m research_theme_linker.main --batch-size 50 --max-docs 200
```

Later, that same command can be wrapped by cron or an APScheduler loop.

### Main loop sketch

```python
def run_batch(batch_size: int, max_docs: int | None = None) -> None:
    processed = 0

    while True:
        candidates = selector.fetch_candidates(batch_size=batch_size, limit=max_docs, offset=processed)
        if not candidates:
            break

        for candidate in candidates:
            payload = hydrator.load_document(candidate.research_id)
            if not linker.is_ready(payload):
                writer.mark_skipped(
                    research_id=payload.research_id,
                    document_hash=payload.document_hash,
                    linker_version=LINKER_VERSION,
                    theme_count=payload.theme_count,
                    reason="normalized themes incomplete",
                )
                continue

            try:
                links = linker.infer_links(payload)
                writer.replace_links(
                    research_id=payload.research_id,
                    document_hash=payload.document_hash,
                    linker_version=LINKER_VERSION,
                    theme_count=payload.theme_count,
                    links=links,
                )
            except Exception as exc:
                writer.mark_error(
                    research_id=payload.research_id,
                    document_hash=payload.document_hash,
                    linker_version=LINKER_VERSION,
                    theme_count=payload.theme_count,
                    error_text=str(exc),
                )

        processed += len(candidates)
```

### Selector sketch

The selector should find documents that are ready for linking and either:

- have never been processed
- were processed with an old `document_hash`
- were processed with an old linker version
- previously errored

Conceptual SQL:

```sql
SELECT pr.id
FROM parsed_research pr
LEFT JOIN (
    SELECT research_id, COUNT(*) AS normalized_theme_count
    FROM research_themes
    GROUP BY research_id
) rtc ON rtc.research_id = pr.id
LEFT JOIN research_theme_link_runs tlr
    ON tlr.research_id = pr.id
WHERE pr.document_hash IS NOT NULL
  AND pr.theme_count > 0
  AND COALESCE(rtc.normalized_theme_count, 0) = pr.theme_count
  AND (
      tlr.research_id IS NULL
      OR tlr.document_hash <> pr.document_hash
      OR tlr.linker_version <> :linker_version
      OR tlr.status = 'error'
  )
ORDER BY pr.id
LIMIT :batch_size;
```

### Hydrator sketch

The hydrator should return one fully assembled document payload for the linker:

```python
DocumentPayload(
    research_id=123,
    document_hash="sha256...",
    document_name="2026-03-22_JPM_....pdf",
    source="JPMorgan",
    source_date="2026-03-22",
    theme_count=4,
    themes=[
        ThemePayload(
            theme_id=1,
            theme_order=1,
            label="Higher term premium",
            relevance=["Rates"],
            classification="Forecast",
            strength="Primary",
            confidence="High",
            context="...",
            directionality={"bearish_rates": 2},
            argument_structure={
                "dependencies": ["Sticky inflation"],
                "contradictions": [],
                "conditionals": ["If inflation remains sticky"],
                "confidence_basis": "..."
            },
            excerpts=["Quote 1", "Quote 2"],
        )
    ],
)
```

The hydrator should do this in two batch-friendly reads:

1. fetch the document and normalized theme rows
2. fetch all excerpts for those theme ids and attach them in memory

### Linker sketch

The linker should expose one orchestration method:

```python
def infer_links(payload: DocumentPayload) -> list[ThemeLink]:
    candidate_pairs = build_candidate_pairs(payload.themes)
    links = []

    for pair in candidate_pairs:
        rule_link = rules.classify(pair)
        if rule_link is not None:
            links.append(rule_link)
            continue

        llm_link = llm.classify(pair)
        if llm_link is not None:
            links.append(llm_link)

    return dedupe_and_normalize_links(links)
```

### Rule examples

The deterministic rule layer should be explicit and testable.

Examples:

```python
def classify(pair: ThemePair) -> ThemeLink | None:
    if mentions(pair.left.argument_structure.dependencies, pair.right.label):
        return ThemeLink(pair.left.theme_id, pair.right.theme_id, "depends_on", "Theme A depends on Theme B.")

    if mentions(pair.left.argument_structure.contradictions, pair.right.label):
        return ThemeLink(pair.left.theme_id, pair.right.theme_id, "contradicts", "Theme A conflicts with Theme B.")

    if strong_overlap(pair.left, pair.right) and same_directionality(pair.left, pair.right):
        return ThemeLink(pair.left.theme_id, pair.right.theme_id, "reinforces", "Both themes support the same core idea.")

    return None
```

### LLM sketch

The LLM layer should classify a pair into one of:

- `reinforces`
- `depends_on`
- `contradicts`
- `qualifies`
- `drives`
- `none`

Minimal prompt contract:

```json
{
  "theme_a": {...},
  "theme_b": {...},
  "allowed_relationships": [
    "reinforces",
    "depends_on",
    "contradicts",
    "qualifies",
    "drives",
    "none"
  ]
}
```

Expected output:

```json
{
  "relationship": "drives",
  "explanation": "Theme A is presented as the cause of Theme B."
}
```

Opinionated recommendation:

- use a strict response schema
- keep explanation short
- treat `none` as a valid and common answer

### Writer sketch

The writer owns replace-all semantics per document:

```python
def replace_links(
    research_id: int,
    document_hash: str,
    linker_version: str,
    theme_count: int,
    links: list[ThemeLink],
) -> None:
    delete_links_for_research_id(research_id)
    insert_links(research_id, links)
    upsert_run_state(
        research_id=research_id,
        document_hash=document_hash,
        linker_version=linker_version,
        status="complete",
        theme_count=theme_count,
        link_count=len(links),
        error_text=None,
    )
```

Error and skip flows should update run state without touching existing good links unless a replacement is actually happening.

### Config sketch

Recommended config surface:

```env
SUPABASE_URL=...
SUPABASE_KEY=...
LINKER_VERSION=v1
LINKER_BATCH_SIZE=50
LINKER_MAX_DOCS=200
LINKER_ENABLE_LLM=true
LINKER_PROVIDER=openai
OPENAI_API_KEY=...
```

If `LINKER_ENABLE_LLM=false`, the service should still run with rules only.

### First test fixture sketch

The first gold fixture should look like:

```json
{
  "document_name": "desk_note.pdf",
  "themes": [
    {
      "label": "Sticky inflation",
      "argument_structure": {
        "dependencies": [],
        "contradictions": []
      }
    },
    {
      "label": "Higher term premium",
      "argument_structure": {
        "dependencies": ["Sticky inflation"],
        "contradictions": []
      }
    }
  ],
  "expected_links": [
    {
      "from_label": "Higher term premium",
      "to_label": "Sticky inflation",
      "relationship": "depends_on"
    }
  ]
}
```

This gives one clear deterministic path before the LLM path is introduced.

## Draft SQL Migration

If we keep `research_theme_links` as the durable output table, the first missing database piece is the run-state table.

Recommended migration:

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS research_theme_link_runs (
    research_id BIGINT PRIMARY KEY
        REFERENCES parsed_research(id)
        ON DELETE CASCADE,
    document_hash TEXT NOT NULL,
    linker_version TEXT NOT NULL,
    status TEXT NOT NULL,
    theme_count INTEGER NOT NULL DEFAULT 0,
    link_count INTEGER NOT NULL DEFAULT 0,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_text TEXT NULL,
    CONSTRAINT chk_research_theme_link_runs_status
        CHECK (status IN ('complete', 'error', 'skipped'))
);

CREATE INDEX IF NOT EXISTS idx_research_theme_link_runs_status
    ON research_theme_link_runs(status);

CREATE INDEX IF NOT EXISTS idx_research_theme_link_runs_hash_version
    ON research_theme_link_runs(document_hash, linker_version);

CREATE INDEX IF NOT EXISTS idx_research_theme_link_runs_processed_at
    ON research_theme_link_runs(processed_at DESC);

COMMENT ON TABLE research_theme_link_runs IS
    'Run-state tracking for the downstream theme linker.';

COMMENT ON COLUMN research_theme_link_runs.document_hash IS
    'Document hash from parsed_research used to detect stale linker outputs.';

COMMENT ON COLUMN research_theme_link_runs.linker_version IS
    'Semantic version or build identifier of the linker logic used for this run.';

COMMENT ON COLUMN research_theme_link_runs.status IS
    'Linking outcome: complete, error, or skipped.';

COMMIT;
```

### Optional hardening migration

If link quality stabilizes later, consider adding a constrained enum-like check to `research_theme_links.relationship`.

Example:

```sql
ALTER TABLE research_theme_links
    ADD CONSTRAINT chk_research_theme_links_relationship
    CHECK (relationship IN (
        'reinforces',
        'depends_on',
        'contradicts',
        'qualifies',
        'drives'
    ));
```

Opinionated recommendation:

- do not add that constraint on day one
- first verify that the proposed taxonomy is stable on real documents

## Starter Package Scaffold

If we stand this up as a separate Python package or service, this is the minimum viable layout.

```text
research_theme_linker/
  pyproject.toml
  README.md
  src/
    main.py
    config.py
    models.py
    selector.py
    hydrator.py
    rules.py
    llm.py
    linker.py
    writer.py
  tests/
    test_selector.py
    test_rules.py
    test_writer.py
    test_linker.py
```

### `pyproject.toml` sketch

```toml
[project]
name = "research-theme-linker"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "supabase>=2.10.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "structlog>=24.4.0",
    "tenacity>=9.0.0",
    "openai>=1.60.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.8.0",
]
```

### `models.py` sketch

```python
from pydantic import BaseModel, Field


class ThemePayload(BaseModel):
    theme_id: int
    theme_order: int
    label: str
    relevance: list[str] = Field(default_factory=list)
    classification: str = "Description"
    strength: str = "Secondary"
    confidence: str = "Medium"
    context: str = ""
    directionality: dict[str, int] | None = None
    argument_structure: dict | None = None
    excerpts: list[str] = Field(default_factory=list)


class DocumentPayload(BaseModel):
    research_id: int
    document_hash: str
    document_name: str
    source: str
    source_date: str | None = None
    theme_count: int = 0
    themes: list[ThemePayload] = Field(default_factory=list)


class ThemeLink(BaseModel):
    from_theme_id: int
    to_theme_id: int
    relationship: str
    explanation: str
```

### `config.py` sketch

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_key: str

    linker_version: str = "v1"
    linker_batch_size: int = 50
    linker_max_docs: int = 200
    linker_enable_llm: bool = False

    openai_api_key: str | None = None


def get_settings() -> Settings:
    return Settings()
```

### `selector.py` sketch

```python
from supabase import Client


class CandidateSelector:
    def __init__(self, client: Client, linker_version: str):
        self.client = client
        self.linker_version = linker_version

    def fetch_candidates(self, batch_size: int) -> list[int]:
        # Initial implementation can call a SQL view or RPC.
        # The selector should return eligible parsed_research ids only.
        raise NotImplementedError
```

Opinionated recommendation:

- implement selector logic as SQL or an RPC on the database side once the conditions settle
- do not reimplement complex eligibility joins with many client-side round trips

### `hydrator.py` sketch

```python
from collections import defaultdict

from supabase import Client

from .models import DocumentPayload, ThemePayload


class DocumentHydrator:
    def __init__(self, client: Client):
        self.client = client

    def load_document(self, research_id: int) -> DocumentPayload:
        # 1. fetch parsed_research row
        # 2. fetch research_themes rows
        # 3. fetch excerpts for fetched theme ids
        # 4. assemble DocumentPayload
        raise NotImplementedError
```

### `rules.py` sketch

```python
from .models import ThemeLink, ThemePayload


def classify_pair(left: ThemePayload, right: ThemePayload) -> ThemeLink | None:
    # Deterministic link classification based on dependencies,
    # contradictions, lexical overlap, and directionality agreement.
    raise NotImplementedError
```

### `llm.py` sketch

```python
from .models import ThemeLink, ThemePayload


class LLMClassifier:
    def classify_pair(self, left: ThemePayload, right: ThemePayload) -> ThemeLink | None:
        # Return None when the model selects "none".
        raise NotImplementedError
```

### `linker.py` sketch

```python
from itertools import combinations

from .models import DocumentPayload, ThemeLink
from .rules import classify_pair


class ThemeLinker:
    def __init__(self, llm_classifier=None):
        self.llm_classifier = llm_classifier

    def is_ready(self, payload: DocumentPayload) -> bool:
        return payload.theme_count > 0 and len(payload.themes) == payload.theme_count

    def infer_links(self, payload: DocumentPayload) -> list[ThemeLink]:
        links: list[ThemeLink] = []

        for left, right in combinations(payload.themes, 2):
            rule_link = classify_pair(left, right)
            if rule_link is not None:
                links.append(rule_link)
                continue

            if self.llm_classifier is not None:
                llm_link = self.llm_classifier.classify_pair(left, right)
                if llm_link is not None:
                    links.append(llm_link)

        return self._dedupe_links(links)

    def _dedupe_links(self, links: list[ThemeLink]) -> list[ThemeLink]:
        seen: set[tuple[int, int, str]] = set()
        deduped: list[ThemeLink] = []
        for link in links:
            key = (link.from_theme_id, link.to_theme_id, link.relationship)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(link)
        return deduped
```

### `writer.py` sketch

```python
from supabase import Client

from .models import ThemeLink


class LinkWriter:
    def __init__(self, client: Client, linker_version: str):
        self.client = client
        self.linker_version = linker_version

    def replace_links(
        self,
        research_id: int,
        document_hash: str,
        theme_count: int,
        links: list[ThemeLink],
    ) -> None:
        # delete existing links for research_id
        # insert replacement set
        # upsert research_theme_link_runs with status=complete
        raise NotImplementedError

    def mark_error(
        self,
        research_id: int,
        document_hash: str,
        theme_count: int,
        error_text: str,
    ) -> None:
        # upsert research_theme_link_runs with status=error
        raise NotImplementedError

    def mark_skipped(
        self,
        research_id: int,
        document_hash: str,
        theme_count: int,
        reason: str,
    ) -> None:
        # upsert research_theme_link_runs with status=skipped
        raise NotImplementedError
```

### `main.py` sketch

```python
import structlog
from supabase import create_client

from .config import get_settings
from .hydrator import DocumentHydrator
from .linker import ThemeLinker
from .selector import CandidateSelector
from .writer import LinkWriter

logger = structlog.get_logger()


def main() -> None:
    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_key)

    selector = CandidateSelector(client, settings.linker_version)
    hydrator = DocumentHydrator(client)
    writer = LinkWriter(client, settings.linker_version)
    linker = ThemeLinker()

    research_ids = selector.fetch_candidates(batch_size=settings.linker_batch_size)

    for research_id in research_ids:
        payload = hydrator.load_document(research_id)
        if not linker.is_ready(payload):
            writer.mark_skipped(
                research_id=payload.research_id,
                document_hash=payload.document_hash,
                theme_count=payload.theme_count,
                reason="normalized themes incomplete",
            )
            continue

        try:
            links = linker.infer_links(payload)
            writer.replace_links(
                research_id=payload.research_id,
                document_hash=payload.document_hash,
                theme_count=payload.theme_count,
                links=links,
            )
        except Exception as exc:
            writer.mark_error(
                research_id=payload.research_id,
                document_hash=payload.document_hash,
                theme_count=payload.theme_count,
                error_text=str(exc),
            )
            logger.exception("Link generation failed", research_id=payload.research_id)
```

## Suggested Implementation Order

If we build this for real, the fastest safe order is:

1. land the SQL migration for `research_theme_link_runs`
2. implement `models.py`, `config.py`, `hydrator.py`, and `writer.py`
3. implement rules-only `linker.py`
4. add rule-focused tests
5. run a small reviewed batch
6. only then decide whether `llm.py` is necessary

## Dispatcher Dependency

`research_dispatcher` should not depend on theme links in phase 1.

When a use case appears, dispatcher can consume links in one of two ways:

1. optional hydration in `src/database.py`
2. a dedicated read path for enriched theme relationships

Opinionated recommendation:

- keep links off the critical path until you know exactly how they improve synthesis or report structure

## Failure Modes

The linker must handle:

- normalized themes incomplete
- theme count mismatch
- stale `document_hash`
- LLM failure
- malformed argument structure
- empty excerpt sets

Required behavior:

- no partial writes
- record status as `error` or `skipped`
- safe rerun on next batch

## Testing Strategy

### Unit tests

- selector chooses only eligible docs
- rules emit expected relationships from dependencies/contradictions
- replace-all write logic is idempotent

### Integration tests

- complete document with 3-6 themes produces stable links
- rerun with same `document_hash` and same `linker_version` is a no-op
- rerun with new version replaces links
- partial normalized document is skipped

### Evaluation set

Create a small gold dataset of documents with hand-labeled theme links.

Use it to answer:

- are rules enough for most pairs?
- where does LLM adjudication actually improve precision?
- which relationship types are too ambiguous and should be merged or dropped?

## Rollout Plan

1. add run-state table
2. implement selector, hydrator, replace-all writer
3. ship deterministic rules only
4. test on a small manually reviewed batch
5. add LLM adjudication only if rules are insufficient
6. backfill older normalized documents
7. expose links to dispatcher only after product value is clear

## Architecture Summary

Recommended shape:

- `research_parser` stays narrow and deterministic
- `research_theme_linker` becomes the owner of document-level theme relationship inference
- `research_dispatcher` remains a consumer, not the writer of durable link state

That is the cleanest three-stage pipeline:

1. extraction
2. enrichment
3. consumption

## Status

`DONE_WITH_CONCERNS`
