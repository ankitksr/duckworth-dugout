-- War Room schema — 3 tables for enrichment.duckdb

-- Article store: RSS articles ingested for LLM context
CREATE TABLE IF NOT EXISTS war_room_articles (
    id VARCHAR PRIMARY KEY,
    source VARCHAR NOT NULL,
    title VARCHAR NOT NULL,
    url VARCHAR,
    body TEXT,
    published TIMESTAMP,
    teams VARCHAR[],
    ingested_at TIMESTAMP DEFAULT current_timestamp
);

-- Wire dispatches: LLM-generated news wire items
CREATE TABLE IF NOT EXISTS war_room_wire (
    id VARCHAR PRIMARY KEY,
    season VARCHAR NOT NULL,
    headline VARCHAR NOT NULL,
    body TEXT,
    category VARCHAR,
    source_articles VARCHAR[],
    generated_at TIMESTAMP DEFAULT current_timestamp
);

-- Panel snapshots: versioned JSON for change detection
CREATE TABLE IF NOT EXISTS war_room_snapshots (
    panel VARCHAR NOT NULL,
    season VARCHAR NOT NULL,
    hash VARCHAR NOT NULL,
    data JSON NOT NULL,
    created_at TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (panel, season, hash)
);
