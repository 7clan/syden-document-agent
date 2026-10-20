"""Resolve a displayed citation to its indexed content and safe local PDF page."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from syden_agent.tools import get_evidence


def source_detail(conn: sqlite3.Connection, citation: str) -> dict[str, Any]:
    """Return only evidence that exists in the current local index."""
    evidence = get_evidence(conn, citation)
    if "error" in evidence or citation.endswith(" | document"):
        return {"error": "No passage-level indexed evidence exists for this reference."}
    name = citation.split(" | ", 1)[0]
    document = conn.execute("SELECT kind FROM documents WHERE path=? AND status='ready'",
                            (name,)).fetchone()
    if document is None:
        return {"error": "The cited document is no longer ready in the index."}
    return {"citation": citation, "filename": name, "kind": document["kind"],
            "evidence": evidence}


def local_pdf_page(conn: sqlite3.Connection, citation: str) -> tuple[Path, int] | None:
    """Locate a cited PDF page inside the indexed folder, never outside it."""
    match = re.fullmatch(r"(.+?) \| page ([1-9]\d*) \| (?:chunk \d+|.+)", citation)
    if not match or "error" in source_detail(conn, citation):
        return None
    name, page_text = match.groups()
    row = conn.execute("SELECT value FROM metadata WHERE key='active_folder'").fetchone()
    if row is None:
        return None
    root = Path(row["value"]).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != ".pdf" or not path.is_file():
        return None
    return path, int(page_text)
