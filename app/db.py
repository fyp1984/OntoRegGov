"""SQLite 操作库：连接与建表。语义层(RDF)另见 graph_store。"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from .config import DB_PATH

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS actors(
  name TEXT PRIMARY KEY, role TEXT NOT NULL, label TEXT);

CREATE TABLE IF NOT EXISTS documents(
  id TEXT PRIMARY KEY, sha256 TEXT, name TEXT, sourceGrade TEXT,
  text TEXT, uploadedAt TEXT);

-- 通用业务实体：Law/Clause/Obligation/Control/DataAsset/EvidenceRequirement/EvidenceRecord
CREATE TABLE IF NOT EXISTS entities(
  id TEXT PRIMARY KEY, type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'candidate',
  currentVersion INTEGER NOT NULL DEFAULT 0, dataJSON TEXT NOT NULL,
  relationsJSON TEXT NOT NULL DEFAULT '[]', updatedAt TEXT, updatedBy TEXT);

CREATE TABLE IF NOT EXISTS entity_versions(
  id TEXT, version INTEGER, dataJSON TEXT, relationsJSON TEXT,
  actor TEXT, changeNote TEXT, source TEXT, createdAt TEXT,
  PRIMARY KEY(id, version));

CREATE TABLE IF NOT EXISTS candidates(
  id TEXT PRIMARY KEY, documentId TEXT, kind TEXT, label TEXT,
  mappedClass TEXT, confidence REAL, provenance TEXT, span TEXT,
  payloadJSON TEXT, status TEXT DEFAULT 'new', createdBy TEXT, createdAt TEXT);

CREATE TABLE IF NOT EXISTS review_tasks(
  id TEXT PRIMARY KEY, targetType TEXT, targetId TEXT, status TEXT DEFAULT 'pending_review',
  note TEXT, reviewer TEXT, createdBy TEXT, createdAt TEXT, decidedAt TEXT,
  editsJSON TEXT);

CREATE TABLE IF NOT EXISTS proposals(
  id TEXT PRIMARY KEY, reason TEXT, status TEXT DEFAULT 'open',
  targetKind TEXT, raisedFrom TEXT, payloadJSON TEXT,
  reviewer TEXT, decidedAt TEXT, createdAt TEXT);

CREATE TABLE IF NOT EXISTS assessments(
  runId TEXT PRIMARY KEY, assetId TEXT, ranAt TEXT, overall TEXT, summaryJSON TEXT);

CREATE TABLE IF NOT EXISTS check_items(
  id TEXT PRIMARY KEY, runId TEXT, assetId TEXT, obligationCode TEXT,
  controlCode TEXT, result TEXT, whyJSON TEXT);

CREATE TABLE IF NOT EXISTS findings(
  id TEXT PRIMARY KEY, checkItemId TEXT, severity TEXT, gapKind TEXT, detail TEXT,
  status TEXT DEFAULT 'open');

CREATE TABLE IF NOT EXISTS remediations(
  id TEXT PRIMARY KEY, findingId TEXT, action TEXT, dueDate TEXT, status TEXT DEFAULT 'open');

CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT,
  target TEXT, paramsJSON TEXT);

-- v1.3.0 多人检查台账与周期复查
CREATE TABLE IF NOT EXISTS inspection_plans(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, scope TEXT, cycle TEXT,
  startDate TEXT, endDate TEXT, status TEXT DEFAULT 'active',
  owner TEXT, checkScopeJSON TEXT, createdAt TEXT, updatedAt TEXT);

CREATE TABLE IF NOT EXISTS inspection_evidence(
  id TEXT PRIMARY KEY, runId TEXT NOT NULL, checkCode TEXT,
  fileName TEXT, filePath TEXT, uploadedBy TEXT, note TEXT, uploadedAt TEXT);

CREATE TABLE IF NOT EXISTS inspection_signoffs(
  id TEXT PRIMARY KEY, runId TEXT NOT NULL, signer TEXT, role TEXT,
  decision TEXT, comment TEXT, signedAt TEXT);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 8000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


def reset_db() -> None:
    """种子重置：清空全部业务表（幂等初始化用）。"""
    with db() as conn:
        for t in ["audit_log", "inspection_signoffs", "inspection_evidence",
                  "inspection_plans", "remediations", "findings", "check_items",
                  "assessments", "proposals", "review_tasks", "candidates",
                  "entity_versions", "entities", "documents", "actors"]:
            conn.execute(f"DELETE FROM {t}")
