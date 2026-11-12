"""Local document index. Source references are stored at ingestion time."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents (
          id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, kind TEXT NOT NULL,
          status TEXT NOT NULL, error TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
          file_size INTEGER, mtime_ns INTEGER
        );
        CREATE TABLE IF NOT EXISTS passages (
          id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          page INTEGER NOT NULL, chunk INTEGER NOT NULL, text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_passages_document ON passages(document_id);
        CREATE TABLE IF NOT EXISTS sheet_rows (
          id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          sheet TEXT NOT NULL, row_num INTEGER NOT NULL, cells_json TEXT NOT NULL,
          UNIQUE(document_id, sheet, row_num)
        );
        CREATE INDEX IF NOT EXISTS idx_sheet_rows_lookup ON sheet_rows(document_id, sheet, row_num);
        CREATE TABLE IF NOT EXISTS pdf_boq_rows (
          id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          page INTEGER NOT NULL, table_num INTEGER NOT NULL, row_num INTEGER NOT NULL,
          cells_json TEXT NOT NULL, method TEXT NOT NULL,
          UNIQUE(document_id, page, table_num, row_num)
        );
        CREATE INDEX IF NOT EXISTS idx_pdf_boq_document ON pdf_boq_rows(document_id, page);
        CREATE TABLE IF NOT EXISTS word_blocks (
          id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          ordinal INTEGER NOT NULL, kind TEXT NOT NULL, location TEXT NOT NULL,
          section TEXT NOT NULL, text TEXT NOT NULL,
          UNIQUE(document_id, location)
        );
        CREATE INDEX IF NOT EXISTS idx_word_blocks_document ON word_blocks(document_id, ordinal);
    """)
    # Existing local indexes can be opened after the fingerprint columns were added.
    columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)")}
    for column in ("file_size", "mtime_ns"):
        if column not in columns:
            connection.execute(f"ALTER TABLE documents ADD COLUMN {column} INTEGER")
    connection.commit()
    return connection


def replace_document(conn: sqlite3.Connection, relative_path: str, kind: str) -> int:
    conn.execute("INSERT INTO documents(path, kind, status) VALUES (?, ?, 'indexing') "
                 "ON CONFLICT(path) DO UPDATE SET kind=excluded.kind, status='indexing', error='', "
                 "updated_at=CURRENT_TIMESTAMP", (relative_path, kind))
    doc_id = conn.execute("SELECT id FROM documents WHERE path=?", (relative_path,)).fetchone()[0]
    conn.execute("DELETE FROM passages WHERE document_id=?", (doc_id,))
    conn.execute("DELETE FROM sheet_rows WHERE document_id=?", (doc_id,))
    conn.execute("DELETE FROM pdf_boq_rows WHERE document_id=?", (doc_id,))
    conn.execute("DELETE FROM word_blocks WHERE document_id=?", (doc_id,))
    conn.commit()
    return doc_id


def mark_document(conn: sqlite3.Connection, doc_id: int, status: str, error: str = "") -> None:
    conn.execute("UPDATE documents SET status=?, error=? WHERE id=?", (status, error[:1500], doc_id))
    conn.commit()
