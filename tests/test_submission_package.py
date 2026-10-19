"""A distributable source archive must not leak credentials or generated documents."""
from __future__ import annotations

from zipfile import ZipFile

from scripts.package_submission import package


def test_source_package_uses_allowlist(tmp_path):
    archive_path = package(tmp_path / "submission.zip")
    with ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "README.md" in names
        assert "app.py" in names
        assert "pyproject.toml" in names
        assert ".env.example" in names
        assert "tests/test_audit_regressions.py" in names
        assert ".env" not in names
        assert not any(".egg-info/" in name for name in names)
        assert not any(name.startswith((".local/", "documents/", "uploads/"))
                       or name.endswith((".db", ".sqlite", ".pdf", ".xlsx", ".xls", ".docx"))
                       for name in names)
