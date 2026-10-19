"""Document sidebar file-management tests: only chosen files leave the active index."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from syden_agent.db import connect
from syden_agent.file_manager import folder_files, remove_document
from syden_agent.ingest import ingest_folder
from syden_agent.tools import list_documents, search_documents


def _pdf(sentence: str) -> bytes:
    result = io.BytesIO()
    doc = canvas.Canvas(result)
    doc.drawString(65, 735, sentence)
    doc.save()
    return result.getvalue()


def test_archive_excludes_only_selected_document_from_next_index(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "original.pdf").write_bytes(_pdf("Unique original transformers task."))
    (root / "other.pdf").write_bytes(_pdf("Unique other generator task."))
    conn = connect(tmp_path / "index.db")
    try:
        assert ingest_folder(conn, root)["indexed"] == 2
        archived = remove_document(root, "original.pdf")
        assert archived == tmp_path / "documents_removed" / "original.pdf"
        assert archived.read_bytes() == _pdf("Unique original transformers task.")
        assert not (root / "original.pdf").exists()
        report = ingest_folder(conn, root)
        assert report["failed"] == 0
        assert list_documents(conn)["count"] == 1
        assert [doc["path"] for doc in list_documents(conn)["documents"]] == ["other.pdf"]
        assert search_documents(conn, "original transformers")["total_matches"] == 0
        assert search_documents(conn, "other generator")["total_matches"] == 1
    finally:
        conn.close()


def test_permanent_delete_erases_only_selected_file(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "mohammad.pdf").write_bytes(b"old pdf")
    (root / "mohammad.xlsx").write_bytes(b"unchanged workbook")
    assert remove_document(root, "mohammad.pdf", delete_permanently=True) is None
    assert not (root / "mohammad.pdf").exists()
    assert (root / "mohammad.xlsx").read_bytes() == b"unchanged workbook"
    assert not (tmp_path / "documents_removed").exists()


def test_same_name_archived_twice_never_overwrites(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "contract.pdf").write_bytes(b"first version")
    first = remove_document(root, "contract.pdf")
    (root / "contract.pdf").write_bytes(b"second version")
    second = remove_document(root, "contract.pdf")
    assert first != second
    assert first.read_bytes() == b"first version"
    assert second.read_bytes() == b"second version"


def test_sidebar_list_supports_nested_files_and_excludes_archived(tmp_path):
    root = tmp_path / "documents"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "notes.docx").write_bytes(b"word")
    (root / "costs.xlsx").write_bytes(b"excel")
    (root / "not_supported.txt").write_text("text")
    assert sorted(folder_files(root)) == sorted([
        "sub/notes.docx" if Path().anchor == "/" else str(Path("sub") / "notes.docx"),
        "costs.xlsx",
    ])
    remove_document(root, str(Path("sub") / "notes.docx"))
    assert folder_files(root) == ["costs.xlsx"]


@pytest.mark.parametrize("invalid", [
    "", "../outside.pdf", "../../outside.pdf", "missing.pdf",
    "subdir/../../outside.pdf", "/tmp/outside.pdf", "other.txt",
])
def test_file_manager_rejects_invalid_paths(tmp_path, invalid):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "safe.pdf").write_bytes(b"safe")
    with pytest.raises(ValueError):
        remove_document(root, invalid)
    assert (root / "safe.pdf").read_bytes() == b"safe"


def test_symlinks_cannot_be_removed_or_archived(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"keep me")
    link = root / "link.pdf"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation unavailable")
    assert folder_files(root) == []
    with pytest.raises(ValueError):
        remove_document(root, "link.pdf", delete_permanently=True)
    assert outside.read_bytes() == b"keep me"


def test_last_file_removed_clears_index(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "only.pdf").write_bytes(_pdf("One testing transformer document."))
    conn = connect(tmp_path / "index.db")
    try:
        assert ingest_folder(conn, root)["indexed"] == 1
        remove_document(root, "only.pdf", delete_permanently=True)
        result = ingest_folder(conn, root)
        assert result["indexed"] == 0
        assert list_documents(conn)["count"] == 0
    finally:
        conn.close()
