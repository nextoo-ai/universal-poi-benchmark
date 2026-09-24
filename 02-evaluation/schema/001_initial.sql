PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY,
    agent_name TEXT NOT NULL,
    dataset_name TEXT,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    schema_version TEXT,
    dataset_version TEXT,
    language TEXT,
    region_name TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    raw_document_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(agent_name, source_sha256)
);

CREATE TABLE IF NOT EXISTS canonical_pois (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    region_name TEXT,
    status TEXT NOT NULL DEFAULT 'provisional'
        CHECK(status IN ('provisional', 'verified', 'rejected')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS poi_records (
    id INTEGER PRIMARY KEY,
    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
    canonical_poi_id INTEGER REFERENCES canonical_pois(id) ON DELETE SET NULL,
    original_poi_id TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    subcategory TEXT,
    latitude REAL,
    longitude REAL,
    address TEXT,
    locality TEXT,
    region TEXT,
    country_code TEXT,
    is_hidden_gem INTEGER CHECK(is_hidden_gem IN (0, 1) OR is_hidden_gem IS NULL),
    raw_json TEXT NOT NULL,
    normalized_json TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(submission_id, original_poi_id)
);

CREATE INDEX IF NOT EXISTS idx_poi_submission ON poi_records(submission_id);
CREATE INDEX IF NOT EXISTS idx_poi_normalized_name ON poi_records(normalized_name);
CREATE INDEX IF NOT EXISTS idx_poi_coordinates ON poi_records(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_poi_canonical ON poi_records(canonical_poi_id);

CREATE TABLE IF NOT EXISTS external_identifiers (
    id INTEGER PRIMARY KEY,
    poi_record_id INTEGER NOT NULL REFERENCES poi_records(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    external_id TEXT NOT NULL,
    raw_json TEXT,
    UNIQUE(poi_record_id, namespace, external_id)
);
CREATE INDEX IF NOT EXISTS idx_external_lookup
    ON external_identifiers(namespace, external_id);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT
);

CREATE TABLE IF NOT EXISTS poi_tags (
    poi_record_id INTEGER NOT NULL REFERENCES poi_records(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    raw_value TEXT,
    PRIMARY KEY(poi_record_id, tag_id)
);

CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY,
    poi_record_id INTEGER NOT NULL REFERENCES poi_records(id) ON DELETE CASCADE,
    link_type TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    source_id TEXT,
    raw_json TEXT NOT NULL,
    UNIQUE(poi_record_id, link_type, url)
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    poi_record_id INTEGER NOT NULL REFERENCES poi_records(id) ON DELETE CASCADE,
    image_url TEXT NOT NULL,
    page_url TEXT,
    caption TEXT,
    creator TEXT,
    license TEXT,
    raw_json TEXT NOT NULL,
    UNIQUE(poi_record_id, image_url)
);

CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY,
    poi_record_id INTEGER NOT NULL REFERENCES poi_records(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    rating REAL,
    rating_scale REAL,
    review_count INTEGER,
    observed_at TEXT,
    source_url TEXT,
    raw_json TEXT NOT NULL,
    UNIQUE(poi_record_id, provider)
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY,
    poi_record_id INTEGER NOT NULL REFERENCES poi_records(id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    source_id TEXT,
    url TEXT,
    supports_json TEXT NOT NULL DEFAULT '[]',
    quote TEXT,
    note TEXT,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id INTEGER PRIMARY KEY,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    config_json TEXT NOT NULL DEFAULT '{}',
    summary_json TEXT,
    error_text TEXT
);

CREATE TABLE IF NOT EXISTS url_checks (
    id INTEGER PRIMARY KEY,
    evaluation_run_id INTEGER REFERENCES evaluation_runs(id) ON DELETE SET NULL,
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    validator_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN (
        'reachable', 'redirected', 'not_found', 'blocked', 'rate_limited',
        'timeout', 'invalid_url', 'mime_mismatch', 'network_error', 'unverified'
    )),
    request_method TEXT,
    http_status INTEGER,
    final_url TEXT,
    redirect_chain_json TEXT NOT NULL DEFAULT '[]',
    content_type TEXT,
    elapsed_ms INTEGER,
    error_code TEXT,
    error_message TEXT,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_url_checks_target ON url_checks(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_url_checks_url ON url_checks(url);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY,
    evaluation_run_id INTEGER REFERENCES evaluation_runs(id) ON DELETE SET NULL,
    left_poi_record_id INTEGER NOT NULL REFERENCES poi_records(id) ON DELETE CASCADE,
    right_poi_record_id INTEGER NOT NULL REFERENCES poi_records(id) ON DELETE CASCADE,
    relation TEXT NOT NULL CHECK(relation IN (
        'same_place', 'part_of', 'contains', 'related', 'different_place', 'uncertain'
    )),
    status TEXT NOT NULL DEFAULT 'candidate'
        CHECK(status IN ('candidate', 'auto_accepted', 'confirmed', 'rejected')),
    confidence REAL NOT NULL CHECK(confidence >= 0.0 AND confidence <= 1.0),
    distance_m REAL,
    name_similarity REAL,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    decided_by TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK(left_poi_record_id < right_poi_record_id),
    UNIQUE(left_poi_record_id, right_poi_record_id)
);

CREATE TABLE IF NOT EXISTS conflicts (
    id INTEGER PRIMARY KEY,
    canonical_poi_id INTEGER REFERENCES canonical_pois(id) ON DELETE CASCADE,
    left_poi_record_id INTEGER REFERENCES poi_records(id) ON DELETE CASCADE,
    right_poi_record_id INTEGER REFERENCES poi_records(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    conflict_type TEXT NOT NULL,
    left_value_json TEXT,
    right_value_json TEXT,
    severity TEXT NOT NULL DEFAULT 'medium' CHECK(severity IN ('low', 'medium', 'high')),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'resolved', 'dismissed')),
    resolution_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS review_queue (
    id INTEGER PRIMARY KEY,
    evaluation_run_id INTEGER REFERENCES evaluation_runs(id) ON DELETE SET NULL,
    item_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50 CHECK(priority BETWEEN 0 AND 100),
    reason_code TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'in_review', 'resolved', 'dismissed')),
    assigned_to TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT,
    resolution_json TEXT,
    UNIQUE(item_type, entity_type, entity_id, reason_code)
);
CREATE INDEX IF NOT EXISTS idx_review_queue_status_priority
    ON review_queue(status, priority DESC, id);
