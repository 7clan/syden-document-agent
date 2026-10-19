"""Independent audit cases generated without employer documents or API calls."""
from __future__ import annotations

import datetime as dt

import xlwt
from docx import Document
from openpyxl import Workbook
from reportlab.pdfgen import canvas

from syden_agent.db import connect
from syden_agent.ingest import ingest_folder
from syden_agent.tools import extract_dates, get_evidence, query_spreadsheet


def test_explicit_currency_columns_in_xlsx_and_xls(tmp_path):
    modern = Workbook()
    modern.active.title = "Mixed"
    for row in (("Item", "Total Amount", "Currency"),
                ("Transformer", 1_500_000, "SAR"), ("Cable", 2_000_000, "AED")):
        modern.active.append(row)
    modern.save(tmp_path / "mixed.xlsx")
    legacy = xlwt.Workbook()
    sheet = legacy.add_sheet("Mixed")
    for index, row in enumerate((("Item", "Total Amount", "Currency"),
                                 ("Transformer", 1_500_000, "SAR"),
                                 ("Cable", 2_000_000, "AED"))):
        for column, value in enumerate(row):
            sheet.write(index, column, value)
    legacy.save(str(tmp_path / "mixed.xls"))
    conn = connect(tmp_path / "index.db")
    assert ingest_folder(conn, tmp_path)["indexed"] == 2
    for extension in ("xlsx", "xls"):
        result = query_spreadsheet(conn, file=f"mixed.{extension}", currency="SAR",
                                   value=1_000_000)
        assert result["total_matches"] == 1
        assert result["matched_amount_sum"] == "1500000"
        assert result["matches"][0]["citation"] == f"mixed.{extension} | Mixed!B2"
        assert get_evidence(conn, result["matches"][0]["citation"])["value"]["value"] == 1_500_000


def test_row_currency_overrides_worksheet_name(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ SAR"
    sheet.append(["Item", "Total Amount", "Currency"])
    sheet.append(["Imported item", 1_750_000, "AED"])
    book.save(tmp_path / "priced.xlsx")
    conn = connect(tmp_path / "index.db")
    ingest_folder(conn, tmp_path)
    sar = query_spreadsheet(conn, currency="SAR")
    aed = query_spreadsheet(conn, currency="AED")
    assert sar["total_matches"] == 0
    assert aed["total_matches"] == 1
    assert aed["matches"][0]["citation"] == "priced.xlsx | BOQ SAR!B2"


def test_non_financial_workbook_does_not_make_boq_result_incomplete(tmp_path):
    boq = Workbook()
    boq.active.append(["Item", "Total Amount (SAR)"])
    boq.active.append(["Transformer", 1_500_000])
    boq.save(tmp_path / "BOQ.xlsx")
    milestones = Workbook()
    milestones.active.append(["Deliverable", "Date"])
    milestones.active.append(["Design drawings", "2026-11-15"])
    milestones.save(tmp_path / "Milestones.xlsx")
    conn = connect(tmp_path / "index.db")
    assert ingest_folder(conn, tmp_path)["indexed"] == 2
    result = query_spreadsheet(conn, currency="SAR")
    assert result["total_matches"] == 1
    assert result["incomplete"] is False


def test_currency_conflict_is_reported_and_cell_format_can_declare_currency(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "Mixed"
    sheet.append(["Item", "Total Amount (SAR)", "Currency"])
    sheet.append(["Conflicting", 1_500_000, "AED"])
    sheet.append(["Valid", 1_750_000, "SAR"])
    book.save(tmp_path / "conflict.xlsx")
    formatted = Workbook()
    sheet = formatted.active
    sheet.append(["Item", "Total Amount"])
    sheet.append(["Formatted", 2_000_000])
    sheet["B2"].number_format = '#,##0 "SAR"'
    formatted.save(tmp_path / "formatted.xlsx")
    conn = connect(tmp_path / "index.db")
    assert ingest_folder(conn, tmp_path)["indexed"] == 2
    conflict = query_spreadsheet(conn, file="conflict.xlsx", currency="SAR", value=1_000_000)
    assert conflict["total_matches"] == 1
    assert conflict["matches"][0]["citation"] == "conflict.xlsx | Mixed!B3"
    assert conflict["incomplete"] is True
    assert any("conflicting" in warning for warning in conflict["warnings"])
    formatted_result = query_spreadsheet(conn, file="formatted.xlsx", currency="SAR",
                                         value=1_000_000)
    assert formatted_result["total_matches"] == 1
    assert formatted_result["matches"][0]["citation"] == "formatted.xlsx | Sheet!B2"


def test_explicit_unit_price_query_uses_requested_column(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ SAR"
    sheet.append(["Item", "Total Amount (SAR)", "Unit Price (SAR)"])
    sheet.append(["Generator", 500_000, 1_200_000])
    book.save(tmp_path / "unit.xlsx")
    conn = connect(tmp_path / "index.db")
    ingest_folder(conn, tmp_path)
    default = query_spreadsheet(conn, currency="SAR", value=1_000_000)
    assert default["total_matches"] == 0
    explicit = query_spreadsheet(conn, column_hint="C", currency="SAR", value=1_000_000)
    assert explicit["total_matches"] == 1
    assert explicit["matches"][0]["citation"] == "unit.xlsx | BOQ SAR!C2"


def test_numeric_year_merged_multiline_and_repeated_headers(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "Tender"
    sheet.append(["Item", "Amount (SAR)", 2026])
    sheet.append(["Generator", 2_450_000, 2026])
    sheet.append([])
    sheet.merge_cells("B4:D4")
    sheet["B4"] = "Currency: SAR"
    sheet["A5"] = "Item"
    sheet["B5"] = "Quantity"
    sheet["C5"] = "Unit Price"
    sheet["D5"] = "Total Amount"
    sheet["A6"] = "Switchgear"
    sheet["B6"] = 5
    sheet["C6"] = 100_000
    sheet["D6"] = 1_750_000
    book.save(tmp_path / "bid.xlsx")
    conn = connect(tmp_path / "index.db")
    assert ingest_folder(conn, tmp_path)["indexed"] == 1
    result = query_spreadsheet(conn, file="bid.xlsx", currency="SAR", value=1_000_000)
    assert result["total_matches"] == 2
    assert [item["citation"] for item in result["matches"]] == [
        "bid.xlsx | Tender!B2", "bid.xlsx | Tender!D6"]
    assert result["matched_amount_sum"] == "4200000"


def test_missing_formula_cache_is_explicitly_incomplete(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ SAR"
    sheet.append(["Item", "Total Amount (SAR)"])
    sheet.append(["Known", 1_500_000])
    sheet.append(["Computed", "=2000000+1"])
    book.save(tmp_path / "formula.xlsx")
    conn = connect(tmp_path / "index.db")
    ingest_folder(conn, tmp_path)
    result = query_spreadsheet(conn, currency="SAR", value=1_000_000)
    assert result["total_matches"] == 1
    assert result["unknown_amount_rows"] == 1
    assert result["unknown_amount_cells"] == ["formula.xlsx | BOQ SAR!B3"]
    assert result["incomplete"] is True
    assert result["warnings"]


def test_non_numeric_amount_is_reported_as_unknown(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ SAR"
    sheet.append(["Item", "Total Amount (SAR)"])
    sheet.append(["Awaiting quote", "TBD"])
    book.save(tmp_path / "unknown.xlsx")
    conn = connect(tmp_path / "index.db")
    ingest_folder(conn, tmp_path)
    result = query_spreadsheet(conn, currency="SAR", value=1_000_000)
    assert result["total_matches"] == 0
    assert result["unknown_amount_cells"] == ["unknown.xlsx | BOQ SAR!B2"]
    assert result["incomplete"] is True


def _draw_pdf_boq(path):
    pdf = canvas.Canvas(str(path))
    pdf.setFont("Helvetica", 11)
    x = (50, 250, 390, 520)
    y = (730, 700, 670, 640)
    rows = (("Item", "Total Amount", "Currency"),
            ("Transformer", "1500000", "SAR"),
            ("Cable", "1000000", "SAR"))
    for ypos, values in zip(y, rows):
        for xpos, value in zip(x, values):
            pdf.drawString(xpos + 4, ypos + 8, value)
    for xpos in x:
        pdf.line(xpos, 640, xpos, 760)
    for ypos in (640, 670, 700, 730, 760):
        pdf.line(50, ypos, 520, ypos)
    pdf.showPage()
    pdf.save()


def test_independently_generated_pdf_boq_has_numerical_citations(tmp_path):
    _draw_pdf_boq(tmp_path / "BOQ.pdf")
    conn = connect(tmp_path / "index.db")
    assert ingest_folder(conn, tmp_path)["indexed"] == 1
    result = query_spreadsheet(conn, currency="SAR", value=1_000_000)
    assert result["total_matches"] == 1
    match = result["matches"][0]
    assert match["amount_exact"] == "1500000"
    assert match["citation"].startswith("BOQ.pdf | page 1 | table 1 | row ")
    assert get_evidence(conn, match["citation"])["value"]["value"] == "1500000"


def test_pdf_without_currency_and_scanned_pdf_are_reported(tmp_path):
    text_pdf = canvas.Canvas(str(tmp_path / "text_boq.pdf"))
    text_pdf.drawString(50, 700, "Transformer 1500000")
    text_pdf.drawString(50, 680, "Generator 2400000")
    text_pdf.save()
    scanned = canvas.Canvas(str(tmp_path / "scan.pdf"))
    scanned.rect(50, 50, 100, 100, fill=1)
    scanned.save()
    conn = connect(tmp_path / "index.db")
    report = ingest_folder(conn, tmp_path)
    assert report["indexed"] == 1
    assert report["failed"] == 1
    assert "extractable text" in next(x["error"] for x in report["files"]
                                      if x["file"] == "scan.pdf")
    result = query_spreadsheet(conn, currency="SAR", value=1_000_000)
    assert result["total_matches"] == 0
    assert result["incomplete"] is True
    assert any("currency" in warning.lower() for warning in result["warnings"])


def test_borderless_pdf_boq_with_declared_currency_is_qualified(tmp_path):
    pdf = canvas.Canvas(str(tmp_path / "text_boq.pdf"))
    for index, line in enumerate(("Currency: SAR", "Transformer 1500000",
                                  "Cable 1000000", "Generator 2400000")):
        pdf.drawString(50, 700 - 20 * index, line)
    pdf.save()
    conn = connect(tmp_path / "index.db")
    assert ingest_folder(conn, tmp_path)["indexed"] == 1
    result = query_spreadsheet(conn, currency="SAR", value=1_000_000)
    assert result["total_matches"] == 2
    assert result["matched_amount_sum"] == "3900000"
    assert result["incomplete"] is True
    assert any("visual review" in warning for warning in result["warnings"])


def test_five_thousand_rows_remain_paginated_and_exact(tmp_path):
    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ SAR"
    sheet.append(["Item", "Total Amount (SAR)"])
    for index in range(5000):
        sheet.append([f"Item {index}", 1_500_000 if index % 2 == 0 else 500_000])
    book.save(tmp_path / "large.xlsx")
    conn = connect(tmp_path / "index.db")
    assert ingest_folder(conn, tmp_path)["indexed"] == 1
    first = query_spreadsheet(conn, currency="SAR", value=1_000_000, limit=100)
    last = query_spreadsheet(conn, currency="SAR", value=1_000_000,
                             limit=100, offset=2400)
    assert first["total_matches"] == 2500
    assert first["matched_amount_sum"] == "3750000000"
    assert first["has_more"] is True
    assert last["returned"] == 100
    assert last["has_more"] is False


def test_dates_month_variants_and_pagination(tmp_path):
    document = Document()
    document.add_paragraph("Submit design by Nov 15, 2026.")
    document.add_paragraph("Commission by November 16, 2026.")
    document.add_paragraph("Deliver equipment on 17 Nov 2026.")
    document.add_paragraph("Review on 03/04/26.")
    document.save(tmp_path / "contract.docx")
    book = Workbook()
    book.active.title = "Dates"
    book.active.append(["Deliverable", "Due"])
    for index in range(120):
        book.active.append([f"Milestone {index}",
                            (dt.date(2026, 1, 1) + dt.timedelta(days=index)).isoformat()])
    book.save(tmp_path / "dates.xlsx")
    conn = connect(tmp_path / "index.db")
    assert ingest_folder(conn, tmp_path)["indexed"] == 2
    first = extract_dates(conn, limit=100)
    second = extract_dates(conn, limit=100, offset=100)
    assert first["total_matches"] == 124
    assert first["has_more"] is True
    assert len(first["dates"]) == 100
    assert len(second["dates"]) == 24
    assert {d["normalized_date"] for d in first["dates"] if d["date_text"].startswith("Nov")} == {
        "2026-11-15", "2026-11-16"}
    assert any(d["ambiguous"] for d in first["dates"])


def test_month_first_abbreviation_is_extracted_from_pdf(tmp_path):
    pdf = canvas.Canvas(str(tmp_path / "contract.pdf"))
    for index, line in enumerate(("Submit design by Nov 15, 2026.",
                                  "Commission by November 16, 2026.",
                                  "Deliver on 17 Nov 2026.",
                                  "Review by 2026-11-18.")):
        pdf.drawString(50, 700 - 20 * index, line)
    pdf.save()
    conn = connect(tmp_path / "index.db")
    assert ingest_folder(conn, tmp_path)["indexed"] == 1
    dates = extract_dates(conn)
    assert dates["total_matches"] == 4
    assert {item["normalized_date"] for item in dates["dates"]} == {
        "2026-11-15", "2026-11-16", "2026-11-17", "2026-11-18"}
    assert all(item["citation"].startswith("contract.pdf | page 1 | chunk ")
               for item in dates["dates"])
