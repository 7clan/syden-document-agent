"""End-to-end deterministic acceptance check using only generated documents."""

from scripts.create_demo import create_demo
from syden_agent.db import connect
from syden_agent.ingest import ingest_folder
from syden_agent.tools import extract_dates, get_evidence, query_spreadsheet, search_documents


def test_demo_answers_have_exact_source_locations(tmp_path):
    folder = tmp_path / "demo"
    create_demo(folder)
    conn = connect(tmp_path / "index.db")
    assert ingest_folder(conn, folder)["indexed"] == 3
    costs = query_spreadsheet(conn, value=1_000_000, currency="SAR", operator="gt")
    assert costs["total_matches"] == 2
    assert costs["matched_amount_sum"] == "3750000"
    assert [item["citation"] for item in costs["matches"]] == [
        "BOQ.xlsx | Electrical BOQ!C2", "BOQ.xlsx | Electrical BOQ!C4"]
    assert get_evidence(conn, costs["matches"][0]["citation"])["value"]["value"] == 1_500_000

    scope = search_documents(conn, "install transformers commission", limit=5)
    pdf_hits = [result for result in scope["results"] if result["citation"].startswith("Contract.pdf")]
    assert pdf_hits
    assert "install two transformers" in get_evidence(conn, pdf_hits[0]["citation"])["text"]

    dates = extract_dates(conn)
    assert {row["date_text"] for row in dates["dates"]} == {
        "15 November 2026", "2026-12-01", "03/04/26"}
    assert next(row for row in dates["dates"] if row["date_text"] == "03/04/26")["ambiguous"]
