"""Deterministic, read-only tools used by the agent. No model-generated SQL or code."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime
from typing import Any

from .spreadsheet import _num, query_spreadsheet  # noqa: F401 - backward-compatible public import


def _rows(conn: sqlite3.Connection, query: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _word_citation(row: sqlite3.Row) -> str:
    return f"{row['path']} | {row['location']}"


def list_documents(conn: sqlite3.Connection) -> dict[str, Any]:
    docs = _rows(conn, "SELECT path,kind,status,error FROM documents ORDER BY path")
    for doc in docs:
        doc["citation"] = f"{doc['path']} | document"
    return {"documents": docs, "count": len(docs)}


def inspect_document(conn: sqlite3.Connection, file: str) -> dict[str, Any]:
    rows = _rows(conn, "SELECT id,path,kind,status,error FROM documents WHERE path=?", (file,))
    if not rows:
        return {"error": "File not indexed; call list_documents first"}
    doc = rows[0]
    doc["citation"] = f"{doc['path']} | document"
    if doc["kind"] == "pdf":
        p = _rows(conn, "SELECT page,chunk,substr(text,1,550) AS preview FROM passages "
                  "WHERE document_id=? ORDER BY page,chunk LIMIT 12", (doc["id"],))
        tables = _rows(conn, "SELECT page,table_num,COUNT(*) AS populated_rows,method "
                       "FROM pdf_boq_rows WHERE document_id=? GROUP BY page,table_num,method "
                       "ORDER BY page,table_num LIMIT 20", (doc["id"],))
        return {"document": doc, "passages_preview": p,
                "boq_tables": tables,
                "page_count": conn.execute("SELECT MAX(page) FROM passages WHERE document_id=?", (doc["id"],)).fetchone()[0]}
    if doc["kind"] == "docx":
        blocks = _rows(conn, "SELECT ordinal,kind,location,section,substr(text,1,550) AS preview "
                       "FROM word_blocks WHERE document_id=? ORDER BY ordinal LIMIT 12", (doc["id"],))
        return {"document": doc, "blocks_preview": blocks,
                "block_count": conn.execute("SELECT COUNT(*) FROM word_blocks WHERE document_id=?",
                                            (doc["id"],)).fetchone()[0]}
    sheets = _rows(conn, "SELECT sheet,COUNT(*) AS populated_rows FROM sheet_rows "
                   "WHERE document_id=? GROUP BY sheet", (doc["id"],))
    for s in sheets:
        s["preview"] = []
        for row in _rows(conn, "SELECT row_num,cells_json FROM sheet_rows "
                         "WHERE document_id=? AND sheet=? ORDER BY row_num LIMIT 12", (doc["id"], s["sheet"])):
            s["preview"].append({"row": row["row_num"],
                                 "cells": {col: cell["value"] for col,cell in json.loads(row["cells_json"]).items()}})
    return {"document": doc, "sheets": sheets}


def search_documents(conn: sqlite3.Connection, query: str, limit: int = 20) -> dict[str, Any]:
    """Bounded lexical retrieval across PDF, Word and worksheet rows."""
    query = _clean(query)[:200]
    if not query:
        return {"error": "Search query is empty"}
    limit = min(max(int(limit), 1), 100)
    terms = list(dict.fromkeys(re.findall(r"[\w]+", query.lower())))
    if not terms:
        return {"results": []}
    found: list[dict[str, Any]] = []
    total = 0

    def keep(hit: dict[str, Any]) -> None:
        nonlocal total
        hit["order"] = total
        total += 1
        found.append(hit)
        if len(found) > limit:
            found.sort(key=lambda item: (-item["score"], item["order"]))
            found.pop()

    for row in conn.execute("SELECT d.path,p.page,p.chunk,p.text FROM passages p JOIN documents d "
                            "ON d.id=p.document_id WHERE d.status='ready' "
                            "ORDER BY d.path,p.page,p.chunk"):
        haystack = row["text"].lower()
        score = sum(t in haystack for t in terms)
        if score:
            keep({"citation": f"{row['path']} | page {row['page']} | chunk {row['chunk']}",
                  "preview": row["text"][:1300], "score": score})
    for row in conn.execute("SELECT d.path,w.location,w.section,w.text FROM word_blocks w "
                            "JOIN documents d ON d.id=w.document_id WHERE d.status='ready' "
                            "ORDER BY d.path,w.ordinal"):
        preview = f"{row['section']}: {row['text']}" if row["section"] else row["text"]
        score = sum(t in preview.lower() for t in terms)
        if score:
            keep({"citation": _word_citation(row), "preview": preview[:1300], "score": score})
    for row in conn.execute("SELECT d.path,s.sheet,s.row_num,s.cells_json FROM sheet_rows s "
                            "JOIN documents d ON d.id=s.document_id WHERE d.status='ready' "
                            "ORDER BY d.path,s.sheet,s.row_num"):
        cells = json.loads(row["cells_json"])
        text = " ".join(_clean(e["value"]) for e in cells.values()).lower()
        score = sum(t in text for t in terms)
        if score:
            keep({"citation": f"{row['path']} | {row['sheet']} | row {row['row_num']}",
                  "preview": {k: v["value"] for k, v in cells.items()}, "score": score})
    found.sort(key=lambda item: (-item["score"], item["order"]))
    for hit in found:
        del hit["order"]
    return {"results": found, "returned": len(found), "total_matches": total,
            "truncated": total > limit}


MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
DATE_REGEX = re.compile(
    rf"(?<!\d)(?:\d{{4}}[-/]\d{{1,2}}[-/]\d{{1,2}}|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|"
    rf"\d{{1,2}}\s+{MONTH}\.?\s+\d{{4}}|{MONTH}\.?\s+\d{{1,2}},?\s+\d{{4}})(?!\d)",
    re.IGNORECASE,
)


def _date_info(text: str) -> tuple[str | None, bool]:
    """Normalize only dates whose day, month and year are unambiguous."""
    if re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", text):
        try:
            year, month, day = map(int, re.split(r"[-/]", text))
            return date(year, month, day).isoformat(), False
        except ValueError:
            return None, True
    if re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", text):
        parts = re.split(r"[/-]", text)
        first, second, year = map(int, parts)
        if len(parts[2]) != 4 or (first <= 12 and second <= 12):
            return None, True
        day, month = (first, second) if first > 12 else (second, first)
        try:
            return date(year, month, day).isoformat(), False
        except ValueError:
            return None, True
    for pattern in ("%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            cleaned = text.replace(",", "").replace(".", "")
            return datetime.strptime(cleaned, pattern).date().isoformat(), False
        except ValueError:
            continue
    return None, True


def extract_dates(conn: sqlite3.Connection, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """Extract candidate dates and surrounding context, not fabricated deliverables."""
    limit, offset = min(max(int(limit), 1), 500), max(int(offset), 0)
    matches: list[dict[str, Any]] = []
    total = 0

    def add(date_text: str, context: Any, citation: str) -> None:
        nonlocal total
        normalized, ambiguous = _date_info(date_text)
        if offset <= total < offset + limit:
            parts = (context.values() if isinstance(context, dict) else [context])
            related = next((str(part).strip() for part in parts if re.search(
                r"\b(?:submit|deliver|install|commission|complete|approve|handover|milestone|due)\b",
                str(part), re.IGNORECASE)), None)
            matches.append({"date_text": date_text, "normalized_date": normalized,
                            "ambiguous": ambiguous, "context": context,
                            "related_action": related, "citation": citation})
        total += 1

    for row in conn.execute("SELECT d.path,p.page,p.chunk,p.text FROM passages p JOIN documents d "
                            "ON d.id=p.document_id WHERE d.status='ready' "
                            "ORDER BY d.path,p.page,p.chunk"):
        for m in DATE_REGEX.finditer(row["text"]):
            add(m.group(), row["text"][max(0, m.start()-100):m.end()+140],
                f"{row['path']} | page {row['page']} | chunk {row['chunk']}")
    for row in conn.execute("SELECT d.path,w.location,w.section,w.text FROM word_blocks w "
                            "JOIN documents d ON d.id=w.document_id WHERE d.status='ready' "
                            "ORDER BY d.path,w.ordinal"):
        for m in DATE_REGEX.finditer(row["text"]):
            context = row["text"][max(0, m.start()-100):m.end()+140]
            if row["section"]:
                context = f"{row['section']}: {context}"
            add(m.group(), context, _word_citation(row))
    for row in conn.execute("SELECT d.path,s.sheet,s.row_num,s.cells_json FROM sheet_rows s "
                            "JOIN documents d ON d.id=s.document_id WHERE d.status='ready' "
                            "ORDER BY d.path,s.sheet,s.row_num"):
        cells = json.loads(row["cells_json"])
        for col, item in cells.items():
            value = item.get("value")
            if value is None:
                continue
            for m in DATE_REGEX.finditer(str(value)):
                add(m.group(), {k: v.get("value") for k, v in cells.items()},
                    f"{row['path']} | {row['sheet']}!{col}{row['row_num']}")
    coverage_warnings = [f"{row['path']}: {row['status']}"
                         f" ({row['error'] or 'not fully indexed'})"
                         for row in conn.execute(
                             "SELECT path,status,error FROM documents WHERE status!='ready' "
                             "OR error!=''")]
    return {"dates": matches, "total_matches": total,
            "offset": offset, "has_more": offset + limit < total,
            "coverage_warnings": coverage_warnings,
            "note": "Candidate dates only. LLM must examine context to identify actual deliverables; dates may be ambiguous."}


def get_evidence(conn: sqlite3.Connection, citation: str) -> dict[str, Any]:
    """Resolve a citation against indexed evidence rather than trusting a generated reference."""
    pattern = re.fullmatch(r"(.+?) \| document", citation)
    if pattern:
        result = _rows(conn, "SELECT path,kind,status,error FROM documents WHERE path=?",
                       (pattern.group(1),))
        return {"citation": citation, "document": result[0]} if result else {
            "error": "Citation not found"}
    pattern = re.fullmatch(r"(.+?) \| page (\d+) \| chunk (\d+)", citation)
    if pattern:
        name, page, chunk = pattern.groups()
        result = _rows(conn, "SELECT p.text FROM passages p JOIN documents d ON d.id=p.document_id "
                       "WHERE d.path=? AND p.page=? AND p.chunk=?", (name,int(page),int(chunk)))
        return {"citation": citation, "text": result[0]["text"]} if result else {"error": "Citation not found"}
    pattern = re.fullmatch(
        r"(.+?) \| page ([1-9]\d*) \| table ([1-9]\d*) \| row ([1-9]\d*) \| column ([A-Z]{1,3})",
        citation,
    )
    if pattern:
        name, page, table, number, col = pattern.groups()
        result = _rows(conn, "SELECT p.cells_json,p.method FROM pdf_boq_rows p "
                       "JOIN documents d ON d.id=p.document_id WHERE d.path=? AND d.kind='pdf' "
                       "AND p.page=? AND p.table_num=? AND p.row_num=?",
                       (name, int(page), int(table), int(number)))
        if result:
            cells = json.loads(result[0]["cells_json"])
            if col in cells:
                return {"citation": citation, "value": cells[col],
                        "row": {k: v["value"] for k, v in cells.items()},
                        "extraction_method": result[0]["method"]}
    pattern = re.fullmatch(r"(.+?) \| page ([1-9]\d*) \| line ([1-9]\d*) \| amount", citation)
    if pattern:
        name, page, line = pattern.groups()
        result = _rows(conn, "SELECT p.cells_json FROM pdf_boq_rows p "
                       "JOIN documents d ON d.id=p.document_id WHERE d.path=? AND d.kind='pdf' "
                       "AND p.page=? AND p.table_num=1 AND p.row_num=? AND p.method='text_lines'",
                       (name, int(page), int(line)))
        if result:
            cells = json.loads(result[0]["cells_json"])
            return {"citation": citation, "value": cells["B"],
                    "row": {k: v["value"] for k, v in cells.items()},
                    "extraction_method": "text_lines"}
    pattern = re.fullmatch(r"(.+?) \| (paragraph [1-9]\d*|table [1-9]\d* \| row [1-9]\d*)", citation)
    if pattern:
        name, location = pattern.groups()
        result = _rows(conn, "SELECT w.text,w.section FROM word_blocks w JOIN documents d "
                       "ON d.id=w.document_id WHERE d.path=? AND d.kind='docx' AND w.location=?",
                       (name, location))
        return {"citation": citation, **result[0]} if result else {"error": "Citation not found"}
    pattern = re.fullmatch(r"(.+?) \| (.+?) \| row ([1-9]\d*)", citation)
    if pattern:
        name, sheet, number = pattern.groups()
        result = _rows(conn, "SELECT s.cells_json FROM sheet_rows s JOIN documents d "
                       "ON d.id=s.document_id WHERE d.path=? AND s.sheet=? AND s.row_num=?",
                       (name, sheet, int(number)))
        if result:
            cells = json.loads(result[0]["cells_json"])
            return {"citation": citation, "row": {k: v["value"] for k, v in cells.items()}}
    pattern = re.fullmatch(r"(.+?) \| (.+?)!([A-Z]{1,3})([1-9]\d*)", citation)
    if pattern:
        name, sheet, col, number = pattern.groups()
        result = _rows(conn, "SELECT s.cells_json FROM sheet_rows s JOIN documents d ON d.id=s.document_id "
                       "WHERE d.path=? AND s.sheet=? AND s.row_num=?", (name,sheet,int(number)))
        if result:
            cells = json.loads(result[0]["cells_json"])
            if col in cells:
                return {"citation": citation, "value": cells[col],
                        "row": {k: v["value"] for k, v in cells.items()}}
    return {"error": "Citation not found or unsupported format"}


TOOLS = {
    "list_documents": list_documents,
    "inspect_document": inspect_document,
    "search_documents": search_documents,
    "query_spreadsheet": query_spreadsheet,
    "extract_dates": extract_dates,
    "get_evidence": get_evidence,
}

# Provider-agnostic JSON-schema declarations. No write or arbitrary-code tools.
TOOL_SCHEMAS = [
    {"name": "list_documents", "description": "List files indexed, file types and ingestion errors.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "inspect_document", "description": "Inspect an exact PDF, Word document or Excel workbook and preview its contents. Call before ambiguous spreadsheet queries.",
     "parameters": {"type": "object", "properties": {"file": {"type": "string"}}, "required": ["file"]}},
    {"name": "search_documents", "description": "Search PDF text, Word paragraphs and tables, and spreadsheet rows for clauses, scope, deliverables and terminology. Returns source references.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]}},
    {"name": "query_spreadsheet", "description": "Run READ-ONLY numeric filtering across Excel rows and extracted PDF BOQ tables; return exact source cells or PDF page/table/row references. Warnings and incomplete flag identify uncertain coverage. Paginate with offset.",
     "parameters": {"type": "object", "properties": {
         "column_hint": {"type": "string"}, "operator": {"type": "string", "enum": ["gt","gte","lt","lte","eq","all"]},
         "value": {"type": "number"}, "file": {"type": "string"}, "sheet": {"type": "string"},
         "currency": {"type": "string"}, "text_filter": {"type": "string"},
         "limit": {"type": "integer"}, "offset": {"type": "integer"}}, "required": ["value"]}},
    {"name": "extract_dates", "description": "Extract candidate dates from PDF, Word and Excel, with context and citations; paginate for large results.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}, "offset": {"type": "integer"}}}},
    {"name": "get_evidence", "description": "Verify a PDF chunk/table cell, Word paragraph/table row, or Excel cell citation and read its underlying content.",
     "parameters": {"type": "object", "properties": {"citation": {"type": "string"}}, "required": ["citation"]}},
]
