"""Browser-upload saving and ingestion: no document overwrites or unsafe paths."""
from __future__ import annotations

import io

import pytest

from syden_agent.db import connect
from syden_agent.ingest import ingest_folder
from syden_agent.tools import list_documents, search_documents
from syden_agent.uploads import save_uploaded_file


def test_uploads_create_folder_and_save_multiple_files(tmp_path):
    folder = tmp_path / "uploaded documents"
    files = {
        "contract.PDF": b"%PDF-1.4\nExample",
        "boq.xlsx": b"first-excel-bytes",
        "meeting.docx": b"word-test",
    }
    for name, data in files.items():
        assert save_uploaded_file(folder, name, memoryview(data), 1000) == name
        assert (folder / name).read_bytes() == data


def test_uploaded_name_collisions_never_overwrite_original(tmp_path):
    destination = tmp_path / "documents"
    assert save_uploaded_file(destination, "Contract.pdf", b"original", 1024) == "Contract.pdf"
    assert save_uploaded_file(destination, "Contract.pdf", b"second", 1024) == (
        "Contract (2).pdf"
    )
    assert save_uploaded_file(destination, "Contract.pdf", b"third", 1024) == (
        "Contract (3).pdf"
    )
    assert (destination / "Contract.pdf").read_bytes() == b"original"
    assert (destination / "Contract (2).pdf").read_bytes() == b"second"
    assert (destination / "Contract (3).pdf").read_bytes() == b"third"


@pytest.mark.parametrize("filename", [
    "", ".pdf", "../contract.pdf", r"..\contract.pdf", r"C:\contract.pdf",
    "stuff/contract.pdf", "CON.pdf", "LPT1.xlsx", "a:b.pdf", "file?.docx",
    "unsafe.pdf ", "readme.txt", "data.xlsb", "archive.zip",
])
def test_upload_rejects_unsafe_and_unsupported_filenames(tmp_path, filename):
    target = tmp_path / "documents"
    with pytest.raises(ValueError):
        save_uploaded_file(target, filename, b"some content", 1024)
    assert not target.exists()


def test_upload_rejects_empty_and_too_large_without_side_effects(tmp_path):
    target = tmp_path / "documents"
    for content in (b"", b"123456"):
        with pytest.raises(ValueError):
            save_uploaded_file(target, "contract.pdf", content, 5)
    assert not target.exists()


def test_uploaded_pdf_excel_word_become_searchable_after_indexing(tmp_path):
    from docx import Document
    from openpyxl import Workbook
    from reportlab.pdfgen import canvas

    source = tmp_path / "incoming"
    pdf_content = io.BytesIO()
    pdf = canvas.Canvas(pdf_content)
    pdf.drawString(55, 750, "Contractor shall install three solar arrays.")
    pdf.save()

    workbook = Workbook()
    workbook.active.title = "Electrical BOQ"
    workbook.active.append(["Item", "Description", "Amount (SAR)"])
    workbook.active.append(["PV-01", "Solar inverter", 1400000])
    xlsx_content = io.BytesIO()
    workbook.save(xlsx_content)

    word = Document()
    word.add_paragraph("The solar handover is scheduled for 18 June 2027.")
    docx_content = io.BytesIO()
    word.save(docx_content)

    for name, data in (
        ("Contract.pdf", pdf_content.getvalue()),
        ("Cost.xlsx", xlsx_content.getvalue()),
        ("Minutes.docx", docx_content.getvalue()),
    ):
        save_uploaded_file(source, name, data, 10 * 1024 * 1024)
    conn = connect(tmp_path / "index.sqlite")
    try:
        report = ingest_folder(conn, source)
        assert report["indexed"] == 3
        assert report["failed"] == 0
        assert list_documents(conn)["count"] == 3
        for term, filename in [
            ("solar arrays", "Contract.pdf"),
            ("Solar inverter", "Cost.xlsx"),
            ("handover", "Minutes.docx"),
        ]:
            results = search_documents(conn, term)["results"]
            assert any(filename in item["citation"] for item in results), (term, results)
    finally:
        conn.close()
