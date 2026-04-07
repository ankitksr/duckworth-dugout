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

-- Wire dispatches: LLM-generated editorial items
CREATE TABLE IF NOT EXISTS war_room_wire (
    id INTEGER PRIMARY KEY,
    headline VARCHAR NOT NULL,
    text TEXT,
    emoji VARCHAR,
    category VARCHAR,
    severity VARCHAR,
    teams VARCHAR[],
    context_hash VARCHAR,
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
