# Search Evaluation Instructions

## What this is

This repo now has a small judged-set workflow for search quality.

The judged set is an answer key for search:
- a query you care about
- the chunk IDs that should count as good results
- optional grades for how good each result is

The main file is [eval/queries.jsonl](/Users/ncdial/devwork/research-store/eval/queries.jsonl).

## How to access it

Open:
- [eval/queries.jsonl](/Users/ncdial/devwork/research-store/eval/queries.jsonl)

Each line is one query. Example:

```json
{"query_id":"q1","query":"financial conduct authority","relevant":{"chunk-a":3,"chunk-b":2,"chunk-c":1}}
```

Grades mean:
- `1` = relevant
- `2` = very relevant
- `3` = exact hit

## Fast workflow

### 1. Run a search

```bash
make search ARGS='--db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --query "your query" --json'
```

### 2. Generate a judging worksheet

This is the easiest way for a human to label results.

```bash
make search-judge ARGS='--db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --query "your query" --query-id "q_new" --output eval/q_new.md'
```

That creates a markdown worksheet with:
- a starter JSONL line
- candidate `chunk_id` values
- source, page, scores, and a short preview

Open the worksheet:
- [eval/q_new.md](/Users/ncdial/devwork/research-store/eval/q_new.md)

If you do not pass `--output`, the worksheet prints to the terminal.

### 3. Add the judged query

Copy the starter JSON line from the worksheet into:
- [eval/queries.jsonl](/Users/ncdial/devwork/research-store/eval/queries.jsonl)

Then edit the `relevant` grades.

Example:

```json
{"query_id":"q_new","query":"your query","relevant":{"chunk-id-1":3,"chunk-id-2":2,"chunk-id-3":1}}
```

### 4. Run evaluation

```bash
make search-eval ARGS='--db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --queries eval/queries.jsonl --limit 10'
```

This reports:
- `Recall@10`
- `MRR@10`
- `nDCG@10`

### 5. Compare settings

Lexical only:

```bash
make search-eval ARGS='--db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --queries eval/queries.jsonl --limit 10 --semantic-weight 0'
```

Default hybrid:

```bash
make search-eval ARGS='--db distill_out/chunks.sqlite --npz distill_out/embeddings.npz --queries eval/queries.jsonl --limit 10'
```

## Plain-English labeling advice

When you review results:
- mark the chunk that best answers the query as `3`
- mark strong supporting results as `2`
- mark weaker but still useful results as `1`
- do not include bad results at all

Keep queries realistic:
- use searches a real user would type
- mix exact names, topics, and fuzzy natural-language questions
- include both easy and hard queries

Good judged sets usually include:
- navigational queries: exact entity or document names
- topical queries: broad themes
- semantic queries: natural-language questions
- confusing queries: terms that appear in boilerplate and real content

## Current commands

Local:

```bash
make search ARGS='...'
make search-judge ARGS='...'
make search-eval ARGS='...'
```

Docker:

```bash
make docker-search ARGS='...'
make docker-search-judge ARGS='...'
make docker-search-eval ARGS='...'
```

## Current state

This repo already has a provisional starter set:
- [eval/queries.jsonl](/Users/ncdial/devwork/research-store/eval/queries.jsonl)

Use it as a baseline, but expand it with your own real queries before trusting the metrics too much.
