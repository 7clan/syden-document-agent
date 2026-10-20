"""Headless Streamlit smoke test for indexing and a structured BOQ result."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from reportlab.pdfgen.canvas import Canvas
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
    pdf = Canvas(str(tmp_path / "Contract.pdf"))
    pdf.drawString(72, 700, "Submit design drawings by 15 November 2026.")
    pdf.save()
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
    assert any(isinstance(row["context"], dict) for row in date_result["dates"])
    assert any(isinstance(row["context"], str) for row in date_result["dates"])
    page.session_state["last_answer"] = Answer(
        "Candidate date", [date_result["dates"][0]["citation"]],
        [{"name": "extract_dates", "args": {}, "ok": True}], date_result,
    )
    page.run()
    assert not page.exception
    assert any("Candidate dates" in title.value for title in page.subheader)
    page.session_state["last_answer"] = Answer(
        "- Drawings are due — Contract.pdf | page 1 | chunk 0",
        ["Contract.pdf | page 1 | chunk 0"],
        [{"name": "search_documents", "ok": True}],
        verification_status="evidence_linked",
        claims=[{"text": "Drawings are due", "status": "evidence_linked",
                 "sources": ["Contract.pdf | page 1 | chunk 0"],
                 "reason": "Interpretation is not independently proven",
                 "quotes": [{"citation": "Contract.pdf | page 1 | chunk 0",
                             "quote": "Submit design drawings by 15 November 2026."}]}],
    )
    page.run()
    assert not page.exception
    assert any("AI answer with checked source references" in item.value
               for item in page.caption)
    source_button = next(button for button in page.button
                         if button.label == "Open source")
    source_button.click().run()
    assert not page.exception
    assert any("Indexed source location" in title.value for title in page.markdown)
    assert any("Submit design drawings" in item.value for item in page.text)
    page.session_state["last_answer"] = Answer(
        "Transformer amount", ["BOQ.xlsx | BOQ SAR!B2"],
        [{"name": "query_spreadsheet", "args": {"value": 1_000_000,
                                                 "currency": "SAR"}, "ok": True}],
        verification_status="evidence_linked",
    )
    page.run()
    next(button for button in page.button if button.label == "Open source").click().run()
    assert not page.exception
    assert any("Cited cell value: 1500000" in item.value for item in page.caption)
    conn.close()
