-- War Room schema — enrichment.duckdb
-- Idempotent: all statements use IF NOT EXISTS.

-- Article store: RSS articles ingested for LLM context
CREATE TABLE IF NOT EXISTS war_room_articles (
    guid VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    snippet TEXT,
    body TEXT,
    teams VARCHAR[],
    is_ipl BOOLEAN DEFAULT FALSE,
    published TIMESTAMP,
    ingested_at TIMESTAMP DEFAULT current_timestamp,
    content_hash VARCHAR
);

-- Wire dispatches: LLM-generated editorial items from multiple generators
CREATE TABLE IF NOT EXISTS war_room_wire (
    id INTEGER PRIMARY KEY,
    headline VARCHAR NOT NULL,
    text TEXT,
    emoji VARCHAR,
    category VARCHAR,
    severity VARCHAR,
    teams VARCHAR[],
    source VARCHAR DEFAULT 'wire',
    context_hash VARCHAR,
    hash_version VARCHAR DEFAULT 'v1',
    season VARCHAR NOT NULL,
    match_day VARCHAR,
    expired BOOLEAN DEFAULT FALSE,
    generated_at TIMESTAMP DEFAULT current_timestamp
);

-- Panel snapshots: versioned JSON for change detection
CREATE TABLE IF NOT EXISTS war_room_snapshots (
    id INTEGER PRIMARY KEY,
    panel VARCHAR NOT NULL,
    payload JSON NOT NULL,
    context_hash VARCHAR NOT NULL,
    season VARCHAR NOT NULL,
    snapshot_at TIMESTAMP DEFAULT current_timestamp
);

-- Per-article structured extraction (one row per article_guid + version).
-- The row's existence at the current extraction_version IS the processed marker.
-- is_relevant = NULL is a sentinel for failed extractions (prevents retry loops).
CREATE TABLE IF NOT EXISTS war_room_article_extractions (
    article_guid VARCHAR NOT NULL,
    extraction_version INTEGER NOT NULL DEFAULT 1,
    season VARCHAR NOT NULL,
    is_relevant BOOLEAN,
    story_type VARCHAR,
    summary TEXT,
    headline_takeaway TEXT,
    mentioned_players VARCHAR[],
    match_result_claim JSON,
    key_quotes JSON,
    extracted_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (article_guid, extraction_version)
);

-- Player availability events (append-only, derived from extractions).
-- Current state per player = latest event by article_published, with
-- clear-on-play override applied at query time.
CREATE TABLE IF NOT EXISTS war_room_player_availability_events (
    id INTEGER PRIMARY KEY,
    season VARCHAR NOT NULL,
    player_name VARCHAR NOT NULL,
    franchise_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    reason VARCHAR,
    expected_return VARCHAR,
    article_guid VARCHAR NOT NULL,
    article_published TIMESTAMP,
    source VARCHAR,
    confidence VARCHAR,
    quote VARCHAR,
    extracted_at TIMESTAMP DEFAULT current_timestamp
);
