"""Headless Streamlit smoke test for indexing and a structured BOQ result."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from streamlit.testing.v1 import AppTest

from syden_agent.agent import Answer
from syden_agent.db import connect
from syden_agent.tools import extract_dates, query_spreadsheet


def test_streamlit_indexes_and_displays_verified_boq(tmp_path, monkeypatch):
    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ SAR"
    sheet.append(["Item", "Total Amount (SAR)", "Due"])
    sheet.append(["Transformer", 1_500_000, "2026-11-15"])
    book.save(tmp_path / "BOQ.xlsx")
    db_path = tmp_path / "app.db"
    monkeypatch.setenv("SYDEN_DB_PATH", str(db_path))
    app = Path(__file__).resolve().parents[1] / "app.py"
    page = AppTest.from_file(app, default_timeout=10).run()
    assert not page.exception
    page.text_input[0].set_value(str(tmp_path)).run()
    page.sidebar.button[0].click().run()
    assert not page.exception
    conn = connect(db_path)
    result = query_spreadsheet(conn, currency="SAR", value=1_000_000)
    assert result["total_matches"] == 1
    page.session_state["last_answer"] = Answer(
        "Verified match", ["BOQ.xlsx | BOQ SAR!B2"],
        [{"name": "query_spreadsheet", "args": {"value": 1_000_000, "currency": "SAR"},
          "ok": True}], {**result, "verified_args": {"value": 1_000_000, "currency": "SAR"}},
    )
    page.run()
    assert not page.exception
    assert page.dataframe
    assert any("Spreadsheet matches" in title.value for title in page.subheader)
    date_result = extract_dates(conn)
    page.session_state["last_answer"] = Answer(
        "Candidate date", [date_result["dates"][0]["citation"]],
        [{"name": "extract_dates", "args": {}, "ok": True}], date_result,
    )
    page.run()
    assert not page.exception
    assert any("Candidate dates" in title.value for title in page.subheader)
    conn.close()
