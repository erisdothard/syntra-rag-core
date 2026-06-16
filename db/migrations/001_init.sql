-- syntra-rag-core schema initialization
-- Run: psql $DATABASE_URL < db/migrations/001_init.sql

-- Enable vector extension
create extension if not exists vector;

-- Chunks table — industry-neutral. Domain meaning lives in domain_key/kind/variant/metadata.
create table if not exists chunks (
    id uuid primary key default gen_random_uuid(),
    client text not null,
    domain_key text,
    kind text,
    variant text,
    content text not null,
    metadata jsonb default '{}',
    embedding vector(1024)  -- Voyage AI voyage-3 produces 1024-dim vectors
);

-- Vector similarity search (HNSW for approximate nearest neighbor)
create index if not exists chunks_embedding_idx
    on chunks using hnsw (embedding vector_cosine_ops);

-- Full-text search
create index if not exists chunks_content_fts_idx
    on chunks using gin (to_tsvector('english', content));

-- Client + domain_key lookup
create index if not exists chunks_client_domain_idx
    on chunks (client, domain_key);

-- Hybrid search function: vector cosine + full-text in one query
create or replace function hybrid_search(
    query_text text,
    query_embedding vector(1024),
    match_client text,
    match_limit int default 10,
    vector_weight float default 0.7,
    fts_weight float default 0.3
) returns table (
    id uuid,
    client text,
    domain_key text,
    kind text,
    variant text,
    content text,
    metadata jsonb,
    score float
) language plpgsql as $$
begin
    return query
    select
        c.id, c.client, c.domain_key, c.kind, c.variant,
        c.content, c.metadata,
        (
            vector_weight * (1 - (c.embedding <=> query_embedding)) +
            fts_weight * coalesce(ts_rank(
                to_tsvector('english', c.content),
                plainto_tsquery('english', query_text)
            ), 0)
        )::float as score
    from chunks c
    where c.client = match_client
    order by score desc
    limit match_limit;
end;
$$;
