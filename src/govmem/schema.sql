-- Governance-aware adaptive memory: Version 1 schema (SQLite).
-- Frozen LLM + EXTERNAL adaptive memory. External policy is authoritative.
-- Nothing in the memory/discovery/feedback code paths writes to `policies`;
-- policy rows change only via the policy store's propose/approve/retire/rollback.

PRAGMA foreign_keys = ON;

-- Versioned, human-governed policies. One row per (policy_key, version).
-- status: proposed | active | retired | rejected. At most one active per key.
CREATE TABLE IF NOT EXISTS policies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_key    TEXT    NOT NULL,
    version       INTEGER NOT NULL,
    effect        TEXT    NOT NULL CHECK (effect IN ('allow','deny','review')),
    priority      INTEGER NOT NULL DEFAULT 0,
    match_json    TEXT    NOT NULL,          -- matcher: actions, resource_prefix, roles_any, roles_none, context_equals
    risk_review_threshold REAL,              -- optional per-policy memory escalation threshold
    status        TEXT    NOT NULL DEFAULT 'proposed',
    proposed_by   TEXT    NOT NULL,
    approved_by   TEXT,
    created_at    REAL    NOT NULL,
    updated_at    REAL    NOT NULL,
    UNIQUE (policy_key, version)
);

-- Promoted (validated) patterns. The canonical memory content is `record`, a fixed-size
-- binary encoding (see src/govmem/memory/encode.py). All numeric state (support, Beta
-- alpha/beta, EMA risk, reliability, usefulness, timestamps, centroid sketch) lives ONLY
-- inside `record`; byte accounting and the storage budget count LENGTH(record).
--
-- FULL layout (96 B, within the 80-128 B design band), little-endian:
--   signature     8 B  blake2b-64(action|resource_class|context_key)
--   action_h      4 B  blake2b-32(action)
--   resource_h    4 B  blake2b-32(resource_class)
--   context_h     4 B  blake2b-32(context_key)
--   support       4 B  u32
--   alpha         4 B  f32  Beta posterior "harmful" evidence (incl. prior)
--   beta          4 B  f32  Beta posterior "benign" evidence (incl. prior)
--   ema_risk      4 B  f32
--   reliability   4 B  f32  EMA of contributing reviewer/source reliability
--   usefulness    4 B  f32  EMA governance usefulness
--   first_seen    4 B  u32  unix seconds
--   last_seen     4 B  u32  unix seconds
--   windows       2 B  u16  distinct temporal windows observed
--   flags         1 B  u8
--   version       1 B  u8   (mod 256; authoritative version is the SQL column)
--   provenance    8 B  blake2b-64 over evidence ids/sources
--   centroid     32 B  int8 x 32 (quantized hashed embedding)
--
-- COMPACT-64 layout (64 B, optional, GOVMEM_ENCODING=compact64):
--   signature 8 | action_h 4 | resource_h 4 | context_h 4 | support u16 2 |
--   alpha f16 2 | beta f16 2 | ema_risk u8 1 | reliability u8 1 | usefulness u8 1 |
--   flags u8 1 | first_seen u32 4 | last_seen u32 4 | windows u16 2 | version u8 1 |
--   reserved 1 | provenance 4 | centroid int4 x 32 = 16 | reserved 2
--
-- The TEXT columns below are a human-readable index mirror for the dashboard/API; they are
-- reported separately as index_overhead_bytes and are NOT counted against the budget.
CREATE TABLE IF NOT EXISTS pattern_memory (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    signature      TEXT    NOT NULL,
    action         TEXT    NOT NULL,
    resource_class TEXT    NOT NULL,
    context_key    TEXT    NOT NULL,
    encoding       TEXT    NOT NULL CHECK (encoding IN ('full','compact64')),
    record         BLOB    NOT NULL,
    byte_size      INTEGER NOT NULL,
    status         TEXT    NOT NULL DEFAULT 'active',   -- active | merged | forgotten | quarantined
    version        INTEGER NOT NULL DEFAULT 1,
    source_candidate_id INTEGER,
    created_at     REAL    NOT NULL,
    updated_at     REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_pattern_lookup ON pattern_memory (status, action, resource_class);

-- Raw observations (episodic log). Not budgeted; reported in memory stats.
CREATE TABLE IF NOT EXISTS episodic_memory (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL    NOT NULL,
    user_id       TEXT    NOT NULL,
    source        TEXT    NOT NULL,
    action        TEXT    NOT NULL,
    resource      TEXT    NOT NULL,
    resource_class TEXT   NOT NULL,
    context_key   TEXT    NOT NULL,
    context_json  TEXT    NOT NULL,
    text          TEXT    NOT NULL DEFAULT '',
    embedding     BLOB    NOT NULL,
    routed_to     TEXT,                     -- 'pattern:<id>' | 'candidate:<id>'
    provenance_hash TEXT  NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_episode_action ON episodic_memory (action, context_key);

-- Candidates awaiting validation. Quarantined candidates are never used in decisions.
-- status: pending | needs_review | promoted | rejected
CREATE TABLE IF NOT EXISTS candidate_quarantine (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    signature      TEXT    NOT NULL,
    action         TEXT    NOT NULL,
    resource_class TEXT    NOT NULL,
    context_key    TEXT    NOT NULL,
    centroid       BLOB    NOT NULL,
    support        INTEGER NOT NULL DEFAULT 0,
    first_seen     REAL    NOT NULL,
    last_seen      REAL    NOT NULL,
    windows_json   TEXT    NOT NULL DEFAULT '[]',
    sources_json   TEXT    NOT NULL DEFAULT '{}',
    validation_score REAL  NOT NULL DEFAULT 0,
    flags_json     TEXT    NOT NULL DEFAULT '[]',
    status         TEXT    NOT NULL DEFAULT 'pending',
    review_verdict TEXT,                    -- approve | reject (human or synthetic)
    reviewer_id    TEXT,
    promoted_pattern_id INTEGER,
    created_at     REAL    NOT NULL,
    updated_at     REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cand_lookup ON candidate_quarantine (status, action, resource_class);

-- Every governance decision (deterministic G(u,a,r,c,p) output).
CREATE TABLE IF NOT EXISTS governance_decisions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             REAL    NOT NULL,
    request_json   TEXT    NOT NULL,
    decision       TEXT    NOT NULL,
    base_decision  TEXT    NOT NULL,
    policy_refs_json TEXT  NOT NULL,
    pattern_id     INTEGER,
    risk           REAL,
    reasons_json   TEXT    NOT NULL,
    llm_advisory_json TEXT
);

-- Per-pattern governance statistics (how memory was used under governance).
CREATE TABLE IF NOT EXISTS governance_stats (
    pattern_id     INTEGER NOT NULL,
    decision       TEXT    NOT NULL,
    count          INTEGER NOT NULL DEFAULT 0,
    escalations    INTEGER NOT NULL DEFAULT 0,
    updated_at     REAL    NOT NULL,
    PRIMARY KEY (pattern_id, decision)
);

-- Hash-chained, append-only audit log.
CREATE TABLE IF NOT EXISTS audit_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    actor       TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    entity_type TEXT    NOT NULL,
    entity_id   TEXT    NOT NULL,
    payload_json TEXT   NOT NULL,
    prev_hash   TEXT    NOT NULL,
    hash        TEXT    NOT NULL
);

-- Provenance: which episodes/sources support which candidate/pattern.
CREATE TABLE IF NOT EXISTS evidence_refs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT    NOT NULL,           -- candidate | pattern
    entity_id   INTEGER NOT NULL,
    episode_id  INTEGER NOT NULL,
    source      TEXT    NOT NULL,
    provenance_hash TEXT NOT NULL,
    ts          REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evidence_entity ON evidence_refs (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS ix_evidence_source ON evidence_refs (source);

-- Versioned snapshots used for rollback of pattern state.
CREATE TABLE IF NOT EXISTS pattern_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id  INTEGER NOT NULL,
    version     INTEGER NOT NULL,
    status      TEXT    NOT NULL,
    record      BLOB    NOT NULL,
    context_key TEXT    NOT NULL,
    reason      TEXT    NOT NULL,
    ts          REAL    NOT NULL,
    UNIQUE (pattern_id, version)
);

-- Reviewer reliability (Beta over agreement with consensus / gold labels).
CREATE TABLE IF NOT EXISTS reviewers (
    reviewer_id TEXT PRIMARY KEY,
    alpha       REAL NOT NULL,
    beta        REAL NOT NULL,
    updated_at  REAL NOT NULL
);

-- Source trust used by the poisoning filter (default trust applies when absent).
CREATE TABLE IF NOT EXISTS source_trust (
    source      TEXT PRIMARY KEY,
    trust       REAL NOT NULL,
    updated_at  REAL NOT NULL
);
