-- Morning Research: Supabase schema for run history, documents, and extractions.
-- Optional: only needed if SUPABASE_URL / SUPABASE_KEY are configured.
-- Apply via Supabase Dashboard → SQL Editor → New query → paste → Run.

create table if not exists public.research_digest_runs (
    run_id text primary key,
    window_start timestamptz,
    window_end timestamptz,
    used_fallback_window boolean not null default false,
    page_title text,
    notion_page_id text,
    status text not null default 'success',
    document_count integer default 0,
    alerts jsonb default '[]'::jsonb,
    word_count integer,
    created_at timestamptz not null default now()
);

create table if not exists public.research_digest_documents (
    run_id text not null references public.research_digest_runs (run_id) on delete cascade,
    file_id text not null,
    file_name text,
    content_hash text,
    publication_date date,
    drive_modified_timestamp timestamptz,
    size_bytes bigint,
    excluded boolean not null default false,
    exclusion_reason text,
    created_at timestamptz not null default now(),
    primary key (run_id, file_id)
);

create table if not exists public.research_digest_extractions (
    run_id text not null,
    file_id text not null,
    extraction jsonb,
    extraction_markdown text,
    created_at timestamptz not null default now(),
    primary key (run_id, file_id),
    foreign key (run_id, file_id)
        references public.research_digest_documents (run_id, file_id)
        on delete cascade
);

create index if not exists idx_research_digest_documents_run_id
    on public.research_digest_documents (run_id);

create index if not exists idx_research_digest_extractions_run_id
    on public.research_digest_extractions (run_id);

create index if not exists idx_research_digest_documents_file_id
    on public.research_digest_documents (file_id);

create index if not exists idx_research_digest_documents_content_hash
    on public.research_digest_documents (content_hash);
