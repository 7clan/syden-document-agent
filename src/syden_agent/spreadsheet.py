"""Deterministic BOQ queries over source-addressed Excel and PDF table rows."""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

CURRENCIES = ("SAR", "AED", "USD", "EUR", "GBP")
AMOUNT_WORDS = ("amount", "total", "extended", "line value", "price", "cost")
UNIT_WORDS = ("unit price", "unit rate", "rate per", "quantity", "qty")
SUMMARY_WORDS = ("subtotal", "sub-total", "grand total", "tax", "vat")


def _num(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip().replace("\u00a0", " ")
    text = re.sub(r"\b(?:SAR|USD|AED|EUR|GBP|SR)\b|ر\.س|﷼", "", text,
                  flags=re.IGNORECASE)
    negative = text.strip().startswith("(") and text.strip().endswith(")")
    text = text.strip("() ").replace(",", "").replace(" ", "")
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return -number if negative else number


def _currencies(value: Any) -> set[str]:
    text = str(value or "").upper()
    found = {code for code in CURRENCIES if re.search(rf"\b{code}\b", text)}
    if any(marker in text for marker in ("ر.س", "ريال", "﷼")):
        found.add("SAR")
    return found


def _label(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


@dataclass(frozen=True)
class Header:
    row: int
    column: str
    title: str
    score: int
    currency_column: str | None
    currency: set[str]


def _header(row: dict[str, Any], hint: str, preceding: dict[str, Any] | None = None) -> Header | None:
    """Find an amount heading while allowing numeric metadata in other columns."""
    cells = row["cells"]
    exact_column = bool(re.fullmatch(r"[A-Za-z]{1,3}", hint))
    currency_column = next((col for col, cell in cells.items()
                            if _label(cell.get("value")) in {"currency", "curr", "ccy"}), None)
    if currency_column is None and preceding:
        currency_column = next((col for col, cell in preceding["cells"].items()
                                if _label(cell.get("value")) in {"currency", "curr", "ccy"}), None)
    best: Header | None = None
    for col, cell in cells.items():
        title = _label(cell.get("value"))
        if not title or len(title) > 100 or _num(title) is not None:
            continue
        previous = _label(preceding["cells"].get(col, {}).get("value")) if preceding else ""
        fragment = (any(word in title for word in AMOUNT_WORDS + UNIT_WORDS)
                    or bool(_currencies(title)))
        full_title = (f"{previous} {title}".strip()
                      if previous and previous != title and fragment else title)
        if any(word in title for word in UNIT_WORDS) and not (
                (exact_column and col.lower() == hint.lower())
                or (hint and hint.lower() in title and any(word in hint.lower() for word in UNIT_WORDS))):
            continue
        score = 0
        if exact_column and col.lower() == hint.lower():
            score = 12 if any(word in full_title for word in AMOUNT_WORDS) else 0
        elif hint and hint.lower() in full_title and not exact_column:
            score = 10
        elif hint and not exact_column and all(word in full_title for word in hint.lower().split()):
            score = 8
        elif hint.lower() in ("", "amount", "total amount", "total cost", "cost", "price"):
            if "total" in full_title and any(w in full_title for w in
                                              ("amount", "cost", "price", "value")):
                score = 7
            elif (title in {"amount", "total", "line amount", "extended price",
                            "total cost", "value", "line total"} or title.startswith("amount (")
                  or ("approved" in title and "amount" in title)):
                # An approved extended amount is a final row total, unlike
                # "Unit Price" or "Qty"; do not require the model to know its header.
                score = 6
            elif "extended" in full_title or "line amount" in full_title:
                score = 5
        if score >= 4 and (best is None or score > best.score):
            best = Header(row["row"], col, full_title, score, currency_column,
                          _currencies(full_title))
    return best


def _records(conn: sqlite3.Connection, file: str, sheet: str) -> Iterator[dict[str, Any]]:
    sql = ("SELECT d.path,s.sheet,s.row_num,s.cells_json FROM sheet_rows s "
           "JOIN documents d ON d.id=s.document_id WHERE d.status='ready'")
    params: list[Any] = []
    if file:
        sql += " AND d.path=?"
        params.append(file)
    if sheet:
        sql += " AND s.sheet=?"
        params.append(sheet)
    for record in conn.execute(sql + " ORDER BY d.path,s.sheet,s.row_num", params):
        yield {"file": record["path"], "table": record["sheet"], "row": record["row_num"],
               "kind": "excel", "cells": json.loads(record["cells_json"])}
    sql = ("SELECT d.path,p.page,p.table_num,p.row_num,p.cells_json,p.method "
           "FROM pdf_boq_rows p JOIN documents d ON d.id=p.document_id WHERE d.status='ready'")
    params = []
    if file:
        sql += " AND d.path=?"
        params.append(file)
    for record in conn.execute(sql + " ORDER BY d.path,p.page,p.table_num,p.row_num", params):
        table_name = f"page {record['page']} table {record['table_num']}"
        if sheet and sheet != table_name:
            continue
        yield {"file": record["path"], "table": table_name, "row": record["row_num"],
               "kind": "pdf", "page": record["page"], "table_num": record["table_num"],
               "method": record["method"], "cells": json.loads(record["cells_json"])}


def _citation(row: dict[str, Any], col: str) -> str:
    if row["kind"] == "pdf":
        if row["method"] == "text_lines":
            return f"{row['file']} | page {row['page']} | line {row['row']} | amount"
        return (f"{row['file']} | page {row['page']} | table {row['table_num']} | "
                f"row {row['row']} | column {col}")
    return f"{row['file']} | {row['table']}!{col}{row['row']}"


def _row_currency(row: dict[str, Any], header: Header,
                  fallback: set[str]) -> tuple[set[str], str]:
    amount_cell = row["cells"].get(header.column, {})
    amount_codes = _currencies(amount_cell.get("value")) | _currencies(
        amount_cell.get("number_format"))
    column_codes = (_currencies(row["cells"].get(header.currency_column, {}).get("value"))
                    if header.currency_column else set())
    if amount_codes and column_codes and amount_codes != column_codes:
        return set(), "conflicting amount-cell and row currency"
    explicit = amount_codes or column_codes
    if explicit and header.currency and explicit != header.currency:
        return set(), "conflicting row and amount-header currency"
    # A per-row currency is more specific than a sheet title or filename. Mixed
    # currency BOQs sometimes retain a legacy currency in their title.
    return explicit or header.currency or fallback, ""


def _worksheet_currency(name: str, table: str, header_rows: list[dict[str, Any]]) -> set[str]:
    metadata: set[str] = set()
    for row in header_rows:
        values = [_label(cell.get("value")) for cell in row["cells"].values()]
        for index, value in enumerate(values):
            if "currency" in value:
                metadata |= _currencies(value)
                if index + 1 < len(values):
                    metadata |= _currencies(values[index + 1])
    return metadata or _currencies(table) or _currencies(name)


def query_spreadsheet(
    conn: sqlite3.Connection, column_hint: str = "total amount", operator: str = "gt",
    value: float = 1_000_000, file: str = "", sheet: str = "", currency: str = "",
    limit: int = 100, offset: int = 0, text_filter: str = "",
) -> dict[str, Any]:
    """Filter indexed BOQ amounts without calculating or converting currencies."""
    operator = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte",
                "=": "eq", "==": "eq"}.get(operator, operator)
    if operator not in {"gt", "gte", "lt", "lte", "eq", "all"}:
        return {"error": "Invalid operator"}
    try:
        limit, offset = min(max(int(limit), 1), 500), max(int(offset), 0)
    except (TypeError, ValueError):
        return {"error": "Limit and offset must be integers"}
    if not all(isinstance(item, str) for item in (column_hint, currency, text_filter)):
        return {"error": "Column hint, currency and text filter must be text"}
    if len(text_filter) > 100:
        return {"error": "Text filter is too long"}
    requested = currency.strip().upper()
    if requested and requested not in CURRENCIES:
        return {"error": "Unsupported currency"}
    target = _num(value)
    if target is None or not target.is_finite():
        return {"error": "Comparison target must be a finite number"}

    matches: list[dict[str, Any]] = []
    warnings: list[str] = []
    inspected: list[dict[str, Any]] = []
    unknown_cells: list[str] = []
    unknown_count = total = 0
    sums: dict[str, Decimal] = {}
    top_matches: list[dict[str, Any]] = []
    current: tuple[str, str] | None = None
    pending: list[dict[str, Any]] = []
    selected: Header | None = None
    fallback: set[str] = set()
    previous: dict[str, Any] | None = None

    def warn(message: str) -> None:
        if message not in warnings:
            warnings.append(message)

    def add_row(row: dict[str, Any]) -> None:
        nonlocal total, unknown_count
        if selected is None or row["row"] <= selected.row:
            return
        if text_filter and text_filter.casefold() not in (
                row["file"] + " " + row["table"] + " " +
                " ".join(str(item.get("value") or "") for item in row["cells"].values())
        ).casefold():
            return
        cell = row["cells"].get(selected.column)
        if cell is None:
            return
        citation = _citation(row, selected.column)
        if cell.get("formula") and cell.get("value") is None:
            unknown_count += 1
            if len(unknown_cells) < 100:
                unknown_cells.append(citation)
            warn("Formula results without a cache make numeric results incomplete")
            return
        amount = _num(cell.get("value"))
        if amount is None:
            if str(cell.get("value") or "").strip():
                unknown_count += 1
                if len(unknown_cells) < 100:
                    unknown_cells.append(citation)
                warn(f"{citation}: non-numeric amount; results incomplete")
            return
        if not amount.is_finite():
            return
        descriptions = [_label(item.get("value")) for col, item in row["cells"].items()
                        if col != selected.column]
        if any(text.startswith(SUMMARY_WORDS) for text in descriptions):
            return
        valid = {"gt": amount > target, "gte": amount >= target, "lt": amount < target,
                 "lte": amount <= target, "eq": amount == target, "all": True}[operator]
        if not valid:
            return
        codes, conflict = _row_currency(row, selected, fallback)
        if conflict:
            warn(f"{citation}: {conflict}; row omitted")
            return
        if len(codes) != 1:
            warn(f"{citation}: currency missing or ambiguous; row omitted")
            return
        code = next(iter(codes))
        if requested and code != requested:
            return
        total += 1
        sums[code] = sums.get(code, Decimal(0)) + amount
        item = {"amount": float(amount), "amount_exact": str(amount),
                "row": row["row"], "currency": code,
                "values": {col: entry.get("value") for col, entry in row["cells"].items()},
                "citation": citation, "source_type": row["kind"]}
        top_matches.append(item)
        top_matches.sort(key=lambda entry: Decimal(entry["amount_exact"]), reverse=True)
        if len(top_matches) > 10:
            top_matches.pop()
        if offset <= total - 1 < offset + limit:
            matches.append(item)

    def set_header(row: dict[str, Any], found: Header, lead: list[dict[str, Any]]) -> None:
        nonlocal selected, fallback
        selected = found
        missing_header = f"No extended amount column identified in {row['file']} / {row['table']}"
        if missing_header in warnings:
            warnings.remove(missing_header)
        fallback = _worksheet_currency(row["file"], row["table"], lead)
        inspected.append({"file": row["file"], "sheet": row["table"], "header_row": found.row,
                          "selected_column": f"{found.column} ({found.title})",
                          "currency_column": found.currency_column,
                          "currency_verified": len(found.currency or fallback) == 1})
        if row["kind"] == "pdf" and row["method"] == "text_lines":
            warn(f"{row['file']} / {row['table']}: PDF text-line extraction needs visual review")
        if requested and found.currency and requested not in found.currency:
            warn(f"Currency {requested} conflicts with amount header in {row['file']} / {row['table']}")

    def choose_pending() -> None:
        if not pending:
            return
        candidates = [(candidate, row) for index, row in enumerate(pending)
                      if (candidate := _header(row, column_hint,
                                               pending[index - 1] if index else None))]
        if not candidates:
            sample = " ".join(str(cell.get("value") or "") for row in pending[:10]
                              for cell in row["cells"].values()).lower()
            name = f"{pending[0]['file']} {pending[0]['table']}".lower()
            if (re.search(r"\b(?:boq|bill of quantities|budget|estimate|cost)\b", name)
                    or re.search(r"\b(?:amount|price|cost|extended|unit rate)\b", sample)):
                warn(f"No extended amount column identified in {pending[0]['file']} / "
                     f"{pending[0]['table']}")
            return
        # Start at the first table. Later headers are handled as row-by-row transitions.
        found, row = min(candidates, key=lambda pair: pair[0].row)
        set_header(row, found, [r for r in pending if r["row"] <= found.row][-3:])
        prior = row
        for item in pending:
            if item["row"] <= found.row:
                continue
            repeated = _header(item, column_hint, prior)
            if repeated:
                set_header(item, repeated, [prior, item])
            else:
                add_row(item)
            prior = item

    for row in _records(conn, file, sheet):
        key = row["file"], row["table"]
        if key != current:
            if current is not None and selected is None:
                choose_pending()
            current, selected, pending, fallback, previous = key, None, [], set(), None
        if selected is None:
            if len(pending) < 50:
                pending.append(row)
                if len(pending) == 50:
                    choose_pending()
            else:
                found = _header(row, column_hint, previous)
                if found:
                    set_header(row, found, [previous, row] if previous else [row])
        else:
            found = _header(row, column_hint, previous)
            if found:
                set_header(row, found, [previous, row] if previous else [row])
            else:
                add_row(row)
        previous = row
    if current is not None and selected is None:
        choose_pending()
    missing_pdf = ("SELECT d.path FROM documents d WHERE d.kind='pdf' AND d.status='ready' "
                   "AND NOT EXISTS (SELECT 1 FROM pdf_boq_rows p WHERE p.document_id=d.id) "
                   "AND EXISTS (SELECT 1 FROM passages s WHERE s.document_id=d.id AND "
                   "(lower(d.path) LIKE '%boq%' OR lower(s.text) LIKE '%boq%' OR "
                   "lower(s.text) LIKE '%amount%' OR "
                   "lower(s.text) LIKE '%price%' OR lower(s.text) LIKE '%cost%'))")
    for missing in conn.execute(missing_pdf):
        if not file or file == missing["path"]:
            warn(f"{missing['path']}: numeric PDF content has no reliable BOQ table; results incomplete")
    for document in conn.execute("SELECT path,status,error FROM documents WHERE status!='ready' "
                                 "OR error!=''"):
        if not file or file == document["path"]:
            warn(f"{document['path']}: {document['status']}"
                 f" ({document['error'] or 'not fully indexed'}); results incomplete")
    return {"matches": matches, "top_matches": top_matches,
            "total_matches": total, "returned": len(matches),
            "offset": offset, "has_more": offset + limit < total,
            "matched_amount_sum": str(next(iter(sums.values()))) if len(sums) == 1 else None,
            "matched_amount_sums": {code: str(amount) for code, amount in sorted(sums.items())},
            "inspected_columns": inspected, "unknown_amount_rows": unknown_count,
            "unknown_amount_cells": unknown_cells, "incomplete": bool(warnings or unknown_count),
            "warnings": warnings}
