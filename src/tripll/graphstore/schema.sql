CREATE TABLE nodes (
  node_id           TEXT PRIMARY KEY,             -- "<layer>:<kind>:<natural_key>"
  layer             TEXT NOT NULL CHECK (layer IN ('code','task','finding')),
  kind              TEXT NOT NULL,                -- Module | Symbol | Wave | Finding | …
  natural_key       TEXT NOT NULL,                -- canonical form per ontology.yaml
  repo              TEXT,                         -- NULL for factory-internal nodes
  props             TEXT NOT NULL DEFAULT '{}',   -- JSON, validated per kind
  -- provenance: non-negotiable (§5.1)
  source            TEXT NOT NULL,
  evidence          TEXT,                         -- file:line span or URL
  extractor         TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  confidence        REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  extracted_at      TEXT NOT NULL,
  -- validity: commit-scoped for code, wall-clock for task/finding
  valid_from_sha    TEXT, valid_to_sha TEXT,
  valid_from        TEXT, valid_to      TEXT,
  merged_from       TEXT,                          -- JSON array → reversible fusion
  UNIQUE (layer, kind, natural_key, repo, valid_from_sha)
);
CREATE INDEX nodes_kind  ON nodes(layer, kind);
CREATE INDEX nodes_live  ON nodes(layer, kind, repo)
  WHERE valid_to IS NULL AND valid_to_sha IS NULL;

CREATE TABLE edges (
  edge_id           TEXT PRIMARY KEY,
  predicate         TEXT NOT NULL,                -- DECLARES | CALLS | COVERS | ABOUT | …
  src               TEXT NOT NULL REFERENCES nodes(node_id),
  dst               TEXT NOT NULL REFERENCES nodes(node_id),
  props             TEXT NOT NULL DEFAULT '{}',
  reason            TEXT,                          -- REQUIRED for DEPENDS_ON (D19)
  source            TEXT NOT NULL,
  evidence          TEXT,
  extractor         TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  confidence        REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  extracted_at      TEXT NOT NULL,
  valid_from_sha    TEXT, valid_to_sha TEXT,
  valid_from        TEXT, valid_to      TEXT,
  merged_from       TEXT,
  UNIQUE (predicate, src, dst, valid_from_sha, valid_from)
);
CREATE INDEX edges_out ON edges(src, predicate) WHERE valid_to IS NULL;
CREATE INDEX edges_in  ON edges(dst, predicate) WHERE valid_to IS NULL;

CREATE TABLE merges (                              -- reversibility (§5.1)
  merge_id TEXT PRIMARY KEY, kept TEXT NOT NULL, dropped TEXT NOT NULL,
  reason TEXT NOT NULL, payload TEXT NOT NULL, merged_at TEXT NOT NULL
);
