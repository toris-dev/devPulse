ALTER TABLE posts ADD COLUMN IF NOT EXISTS bundle_id TEXT;

CREATE INDEX IF NOT EXISTS idx_posts_bundle_id ON posts(bundle_id);
CREATE INDEX IF NOT EXISTS idx_posts_card_generated ON posts(status) WHERE status = 'card_generated';

CREATE TABLE IF NOT EXISTS content_bundles (
    id TEXT PRIMARY KEY,
    post_ids TEXT[] NOT NULL,
    card_keys TEXT[] NOT NULL,
    video_key TEXT,
    sns_meta JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
