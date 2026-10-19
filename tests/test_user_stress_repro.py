"""Reproduce the October live stress-test failures using source-shaped fixtures."""
from __future__ import annotations

import io

from openpyxl import Workbook
from reportlab.pdfgen import canvas

from syden_agent.agent import _final_answer, _needs_dates_query, _question_filter
from syden_agent.db import connect
from syden_agent.ingest import ingest_folder
from syden_agent.spreadsheet import query_spreadsheet
from syden_agent.tools import inspect_document


def _contract_and_qa(tmp_path):
    folder = tmp_path / "documents"
    folder.mkdir()
    pdf = io.BytesIO()
    c = canvas.Canvas(pdf)
    c.drawString(55, 750, "Six control circuits were checked during the preliminary field inspection.")
    c.drawString(55, 733, "Four circuits passed and two circuits require retesting.")
    c.save()
    (folder / "06_QA_Inspection_Report.pdf").write_bytes(pdf.getvalue())
    conn = connect(tmp_path / "database.sqlite")
    assert ingest_folder(conn, folder)["indexed"] == 1
    return conn


def test_qa_inspect_only_provides_passage_citation(tmp_path):
    conn = _contract_and_qa(tmp_path)
    try:
        inspection = inspect_document(conn, "06_QA_Inspection_Report.pdf")
        assert inspection["passages_preview"][0]["citation"] == (
            "06_QA_Inspection_Report.pdf | page 1 | chunk 0"
        )
        # Previously the provider collected only '... | document' and lacked
        # any usable passage-level evidence for verification.
        answer = _final_answer(
            conn,
            "According to the inspection record:\n"
            "- **4 circuits passed inspection**\n"
            "- **2 circuits require retesting**",
            [inspection["document"]["citation"],
             inspection["passages_preview"][0]["citation"]],
            [{"name": "inspect_document", "ok": True}],
            "According to 06_QA_Inspection_Report.pdf, how many circuits passed "
            "inspection and how many require retesting?",
            provider="ollama_cloud",
            semantic_checker=lambda _q, _a, _e: {
                "supported": True, "complete": True,
                "supporting_quotes": [{
                    "citation": "06_QA_Inspection_Report.pdf | page 1 | chunk 0",
                    "quote": "Four circuits passed and two circuits require retesting.",
                }],
            },
        )
        assert "4 circuits passed inspection" in answer.text
        assert "2 circuits require retesting" in answer.text
        assert answer.sources == [
            "06_QA_Inspection_Report.pdf | page 1 | chunk 0"
        ]
        assert not any(x.get("name") == "answer_verification" and not x.get("ok")
                       for x in answer.tool_calls)
    finally:
        conn.close()


def test_approved_amount_column_is_detected_without_model_hint(tmp_path):
    folder = tmp_path / "documents"
    folder.mkdir()
    wb = Workbook()
    sheet = wb.active
    sheet.title = "Electrical BOQ"
    sheet.append(["Item Code", "Description", "Qty", "Unit",
                  "Unit Price (SAR)", "Approved Amount (SAR)", "Status"])
    for row in (
        ("EL-101", "500 kVA transformers - Building A", 3, "ea", 525000, 1575000, "Base contract"),
        ("EL-102", "Switchgear panel SG-01", 1, "ea", 1240000, 1240000, "Base contract"),
        ("EL-103", "Switchgear panel SG-02", 1, "ea", 890000, 890000, "Base contract"),
        ("EL-105", "Control relay upgrades", 4, "ea", 380000, 1520000, "Base contract"),
    ):
        sheet.append(row)
    extra = wb.create_sheet("Change Order BOQ")
    extra.append(["Item Code", "Description", "Qty", "Unit",
                  "Unit Price (SAR)", "Approved Amount (SAR)", "Status"])
    extra.append(("CO-07-B", "Cable tray - Building B", 40, "m", 8000, 320000, "Approved"))
    wb.save(folder / "04_Electrical_BOQ.xlsx")
    conn = connect(tmp_path / "database.sqlite")
    try:
        assert ingest_folder(conn, folder)["indexed"] == 1
        question = (
            "List all BOQ items in 04_Electrical_BOQ.xlsx with total costs "
            "strictly above SAR 1,000,000, including their combined total."
        )
        # The previous implementation dropped the model's correct column_hint
        # and could not identify 'Approved Amount (SAR)' automatically.
        args = _question_filter(question, {
            "file": "04_Electrical_BOQ.xlsx",
            "operator": "gt",
            "value": 1000000,
            "column_hint": "Approved Amount (SAR)",
        })
        result = query_spreadsheet(conn, **args)
        assert result["total_matches"] == 3
        assert result["matched_amount_sums"] == {"SAR": "4335000"}
        assert {m["values"]["A"] for m in result["matches"]} == {
            "EL-101", "EL-102", "EL-105"
        }
        assert not result["incomplete"]
        answer = _final_answer(
            conn, "The correct three items total SAR 4,335,000.",
            [], [{"name": "query_spreadsheet", "ok": True}],
            question, numeric_args={"file": "04_Electrical_BOQ.xlsx",
                                    "sheet": "Electrical BOQ", "operator": "all"},
        )
        assert "4335000" in answer.text
        assert all(code in answer.text for code in ["EL-101", "EL-102", "EL-105"])
    finally:
        conn.close()


def test_specific_change_order_deadline_is_not_exhaustive_date_inventory():
    assert not _needs_dates_query(
        "What additional work did approved change order CO-07 authorize, "
        "and did it extend the contractual completion deadline?"
    )
    assert _needs_dates_query("Extract all dates and deliverables.")
    assert _needs_dates_query("List all deadlines.")
    assert not _needs_dates_query("Did CO-07 extend the deadline?")
