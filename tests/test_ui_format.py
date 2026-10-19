"""Regression tests for mixed PDF/Excel date-context rendering."""
from __future__ import annotations

import json

from syden_agent.ui_format import display_safe_rows


def test_date_rows_with_text_and_workbook_dictionary_context_are_arrow_safe():
    records = [
        {"date_text": "15 November 2026", "context": "Deliver drawings", "ambiguous": False},
        {"date_text": "2026-12-01", "context": {"A": "Commission plant", "B": "2026-12-01"},
         "ambiguous": False},
        {"date_text": "03/04/26", "context": {"A": "Review", "B": "03/04/26"},
         "ambiguous": True},
    ]
    formatted = display_safe_rows(records)
    assert formatted[0]["context"] == "Deliver drawings"
    assert json.loads(formatted[1]["context"]) == records[1]["context"]
    assert json.loads(formatted[2]["context"]) == records[2]["context"]
    assert all(isinstance(row["context"], str) for row in formatted)
    assert all(isinstance(row["ambiguous"], bool) for row in formatted)
    assert isinstance(records[1]["context"], dict)  # original evidence unchanged


def test_ui_format_handles_nested_lists_and_null_without_changing_content():
    rows = [{"context": [{"code": "EL-01"}], "related_action": None, "note": "text"}]
    assert json.loads(display_safe_rows(rows)[0]["context"]) == rows[0]["context"]
    assert display_safe_rows(rows)[0]["related_action"] is None
