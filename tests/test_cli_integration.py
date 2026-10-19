"""The CLI can ingest and query a synthetic folder without a cloud model."""
from __future__ import annotations

import json
import sys

from openpyxl import Workbook

from syden_agent.cli import main


def test_cli_ingest_boq_dates_and_list(tmp_path, monkeypatch, capsys):
    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ SAR"
    sheet.append(["Item", "Total Amount (SAR)", "Due"])
    sheet.append(["Transformer", 1_500_000, "2026-11-15"])
    book.save(tmp_path / "BOQ.xlsx")
    monkeypatch.setenv("SYDEN_DB_PATH", str(tmp_path / "index.db"))

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["syden-agent", *args])
        main()
        return json.loads(capsys.readouterr().out)

    assert run("ingest", str(tmp_path))["indexed"] == 1
    assert run("list")["documents"][0]["path"] == "BOQ.xlsx"
    result = run("boq", "--value", "1000000", "--currency", "SAR")
    assert result["total_matches"] == 1
    assert result["matches"][0]["citation"] == "BOQ.xlsx | BOQ SAR!B2"
    assert run("dates", "--limit", "1")["dates"][0]["normalized_date"] == "2026-11-15"
