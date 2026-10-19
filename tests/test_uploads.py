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



def test_confirmed_replacement_updates_same_name_without_duplicate(tmp_path):
    folder = tmp_path / "documents"
    assert save_uploaded_file(folder, "mohammad.pdf", b"old content", 1024) == "mohammad.pdf"
    assert save_uploaded_file(
        folder, "mohammad.pdf", b"updated content", 1024, replace_existing=True,
    ) == "mohammad.pdf"
    assert (folder / "mohammad.pdf").read_bytes() == b"updated content"
    assert [item.name for item in folder.iterdir()] == ["mohammad.pdf"]


def test_only_exact_full_filename_can_be_replaced(tmp_path):
    folder = tmp_path / "documents"
    save_uploaded_file(folder, "mohammad.pdf", b"original PDF", 1024)
    save_uploaded_file(folder, "mohammad.xlsx", b"Excel workbook", 1024)
    save_uploaded_file(
        folder, "mohammad.pdf", b"updated PDF", 1024, replace_existing=True,
    )
    assert (folder / "mohammad.pdf").read_bytes() == b"updated PDF"
    assert (folder / "mohammad.xlsx").read_bytes() == b"Excel workbook"
    assert len(list(folder.iterdir())) == 2


def test_replacement_requires_existing_target(tmp_path):
    folder = tmp_path / "documents"
    with pytest.raises(ValueError, match="Replacement target not found"):
        save_uploaded_file(
            folder, "missing.pdf", b"new", 1024, replace_existing=True,
        )
    assert not folder.exists()


def test_failed_replacement_keeps_original_and_removes_temp_file(tmp_path, monkeypatch):
    folder = tmp_path / "documents"
    save_uploaded_file(folder, "Contract.pdf", b"old valid content", 1024)

    def fail_rename(_source, _dest):
        raise OSError("Simulated rename failure")

    monkeypatch.setattr("syden_agent.uploads.os.replace", fail_rename)
    with pytest.raises(OSError, match="Simulated rename failure"):
        save_uploaded_file(
            folder, "Contract.pdf", b"new content", 1024, replace_existing=True,
        )
    assert (folder / "Contract.pdf").read_bytes() == b"old valid content"
    assert sorted(item.name for item in folder.iterdir()) == ["Contract.pdf"]


def test_confirmed_pdf_replacement_refreshes_search_index(tmp_path):
    from reportlab.pdfgen import canvas

    def make_pdf(sentence):
        output = io.BytesIO()
        document = canvas.Canvas(output)
        document.drawString(55, 750, sentence)
        document.save()
        return output.getvalue()

    folder = tmp_path / "documents"
    save_uploaded_file(
        folder, "mohammad.pdf", make_pdf("Old deadline 12 December 2026."),
        10 * 1024 * 1024,
    )
    conn = connect(tmp_path / "index.sqlite")
    try:
        assert ingest_folder(conn, folder)["indexed"] == 1
        assert search_documents(conn, "12 December 2026")["total_matches"] == 1
        save_uploaded_file(
            folder, "mohammad.pdf", make_pdf("Updated deadline 14 January 2027."),
            10 * 1024 * 1024, replace_existing=True,
        )
        report = ingest_folder(conn, folder)
        assert report["indexed"] == 1
        assert report["failed"] == 0
        assert list_documents(conn)["count"] == 1
        assert search_documents(conn, "14 January 2027")["total_matches"] == 1
        assert search_documents(conn, "12 December 2026")["total_matches"] == 0
    finally:
        conn.close()
