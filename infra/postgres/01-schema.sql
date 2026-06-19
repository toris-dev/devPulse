CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'GeekNews',
    feed_type TEXT NOT NULL DEFAULT 'all',
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    summary TEXT,
    raw_content TEXT,
    author TEXT,
    published_at TIMESTAMPTZ,
    upvotes INT,
    comments_count INT,
    status TEXT NOT NULL DEFAULT 'collected'
        CHECK (status IN ('collected', 'summarized', 'card_generated', 'video_generated', 'published', 'failed')),
    category TEXT,
    difficulty TEXT,
    impact_score REAL,
    llm_summary JSONB,
    card_image_key TEXT,
    video_key TEXT,
    sns_post_id TEXT,
    sns_posted_at TIMESTAMPTZ,
    bundle_id TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_published_at ON posts(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_posts_source ON posts(source);
CREATE INDEX IF NOT EXISTS idx_posts_bundle_id ON posts(bundle_id);

CREATE TABLE IF NOT EXISTS content_bundles (
    id TEXT PRIMARY KEY,
    post_ids TEXT[] NOT NULL,
    card_keys TEXT[] NOT NULL,
    video_key TEXT,
    sns_meta JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    items_processed INT NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);
