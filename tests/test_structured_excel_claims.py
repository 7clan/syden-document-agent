"""Workbook row evidence is checked by cell, independent of model prose order."""
import json

from syden_agent.agent import _final_answer
from syden_agent.claim_verifier import validate_claims
from syden_agent.db import connect
from syden_agent.tools import inspect_document, query_spreadsheet


def _sheet():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Unfamiliar.xlsx','xlsx','ready')")
    rows = [
        ["Gate ID", "Work package", "Target day", "Type", "Decision"],
        ["M-01", "Submit stamped IFC drawings", "2026-11-20", "Contractual deadline", "Approved"],
        ["M-02", "Building B cable tray inspection", "2026-11-30", "Planning target only", "Not approved"],
        ["M-03", "Alternative handover date", "2027-04-05", "Proposal only", "Not contractual"],
    ]
    for number, values in enumerate(rows, 1):
        cells = {chr(65 + index): {"value": value} for index, value in enumerate(values)}
        conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                     "VALUES(1,'Delivery Gates',?,?)", (number, json.dumps(cells)))
    return conn, "Unfamiliar.xlsx | Delivery Gates | row 2", "Unfamiliar.xlsx | Delivery Gates | row 3"


def _check(conn, claim, citation, quote=""):
    raw = json.dumps({"answer": claim, "insufficient": False, "claims": [
        {"text": claim, "supports": [{"citation": citation, "quote": quote}]}]})
    return validate_claims(conn, raw, [citation])


def test_multi_column_interpretation_and_noncontiguous_quote_are_evidence_linked():
    conn, first, _ = _sheet()
    result = _check(conn, "M-01 is an approved contractual deadline to submit stamped "
                    "IFC drawings on 20 November 2026.", first,
                    "M-01: approved submission of stamped IFC drawings, due 2026-11-20")
    assert result["status"] == "evidence_linked"
    assert result["sources"] == [first]
    assert result["claims"][0]["quotes"][0]["quote"].startswith("M-01 Submit stamped")


def test_swapped_date_approval_and_description_are_rejected_per_row():
    conn, first, second = _sheet()
    wrong = [
        ("M-01 is due 2026-11-30.", first),
        ("M-02 was approved.", second),
        ("M-02 was accepted.", second),
        ("M-01 was rejected.", first),
        ("M-01 is pending approval.", first),
        ("M-01 is for Building B cable tray inspection.", first),
        ("M-01 is a planning target only.", first),
        ("M-02 is a contractual deadline.", second),
    ]
    for claim, citation in wrong:
        assert _check(conn, claim, citation)["status"] == "unverified", claim
    assert _check(conn, "M-01 is due 2026-11-20.", second)["status"] == "unverified"
    assert _check(conn, "M-03 was approved.",
                  "Unfamiliar.xlsx | Delivery Gates | row 4")["status"] == "unverified"


def test_fabricated_structured_quote_and_citation_fail():
    conn, first, _ = _sheet()
    wrong_quote = _check(conn, "M-01 is approved.", first, "M-01: not approved")
    assert wrong_quote["status"] == "unverified"
    assert _check(conn, "M-01 is approved.",
                  "Unfamiliar.xlsx | Delivery Gates | row 90")["status"] == "unverified"


def test_zero_financial_matches_do_not_erase_retrieved_milestone():
    conn, first, _ = _sheet()
    financial = query_spreadsheet(conn, file="Unfamiliar.xlsx", sheet="Delivery Gates",
                                  operator="all")
    assert financial["total_matches"] == 0
    claim = "M-01 is approved and due 2026-11-20."
    raw = json.dumps({"answer": claim, "insufficient": False, "claims": [
        {"text": claim, "supports": [{"citation": first, "quote": ""}]}]})
    answer = _final_answer(conn, raw, [first], [
        {"name": "query_spreadsheet", "ok": True,
         "result_preview": json.dumps({"total_matches": financial["total_matches"]})},
        {"name": "get_evidence", "ok": True}],
        "What is the approval and target day for M-01?", structured_mode=True)
    assert answer.verification_status == "evidence_linked"
    assert answer.sources == [first]
    assert "incomplete" not in answer.text.lower()


def test_inspection_exposes_copyable_row_citations():
    conn, first, _ = _sheet()
    preview = inspect_document(conn, "Unfamiliar.xlsx")
    row = preview["sheets"][0]["preview"][1]
    assert row["citation"] == first
    assert row["cells"]["C"] == "2026-11-20"


def test_reordered_columns_and_repeated_header_still_check_approval():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'RemotePlan.xls','xls','ready')")
    rows = {
        4: ["Decision", "Due", "Gate", "Activity", "Category"],
        5: ["Not approved", "2027-06-12", "G-17", "Factory witness test", "Proposal"],
        9: ["Decision", "Due", "Gate", "Activity", "Category"],
        10: ["Approved", "2027-07-01", "G-18", "Site handover", "Deadline"],
    }
    for number, values in rows.items():
        cells = {chr(65 + index): {"value": value} for index, value in enumerate(values)}
        conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                     "VALUES(1,'Control',?,?)", (number, json.dumps(cells)))
    first, second = "RemotePlan.xls | Control | row 5", "RemotePlan.xls | Control | row 10"
    assert _check(conn, "G-17 is a proposal for a factory witness test due "
                  "12 June 2027 and is not approved.", first)["status"] == "evidence_linked"
    assert _check(conn, "G-17 was approved.", first)["status"] == "unverified"
    assert _check(conn, "G-18 handover is due 2027-06-12.", second)["status"] == "unverified"


def test_word_quotes_still_require_real_contiguous_source_text():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Terms.docx','docx','ready')")
    conn.execute("INSERT INTO word_blocks(document_id,ordinal,kind,location,section,text) "
                 "VALUES(1,1,'paragraph','paragraph 1','',"
                 "'The client approved the handover plan.')")
    citation = "Terms.docx | paragraph 1"
    assert _check(conn, "The client approved the handover plan.", citation,
                  "The client rejected the handover plan.")["status"] == "unverified"


def test_grouped_milestone_claims_bind_ids_to_their_own_cited_rows():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Project Schedule.xlsx','xlsx','ready')")
    rows = [
        ["ID", "Activity", "Date", "Classification", "Approval"],
        ["M-01", "Drawings", "2026-11-20", "Contractual deadline", "Approved"],
        ["M-02", "Factory report", "2026-12-10", "Contractual deadline", "Approved"],
        ["M-03", "Handover", "2027-03-31", "Contractual completion", "Approved"],
        ["M-04", "Cable tray inspection", "2026-11-30", "Planning target only", "Not contractual"],
        ["M-05", "Alternative completion", "2027-04-05", "Proposal only", "Not approved"],
    ]
    for number, values in enumerate(rows, 1):
        cells = {chr(65 + index): {"value": value} for index, value in enumerate(values)}
        conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                     "VALUES(1,'Milestones',?,?)", (number, json.dumps(cells)))

    def cites(*numbers):
        return [f"Project Schedule.xlsx | Milestones | row {number}" for number in numbers]

    def grouped(text, citations):
        raw = json.dumps({"answer": text, "insufficient": False, "claims": [
            {"text": text, "supports": [{"citation": cite, "quote": ""}
                                         for cite in citations]}]})
        return validate_claims(conn, raw, citations)

    accepted = grouped("The contractual milestones are M-01, M-02 and M-03.", cites(2, 3, 4))
    assert accepted["status"] == "evidence_linked"
    assert accepted["sources"] == cites(2, 3, 4)
    assert grouped("The unapproved planning dates are M-04 and M-05.",
                   cites(5, 6))["status"] == "evidence_linked"
    assert grouped("The contractual milestones are M-01, M-02 and M-03.",
                   cites(2, 3, 5))["status"] == "unverified"
    assert grouped("The contractual milestones are M-01, M-02 and M-03.",
                   cites(2, 3))["status"] == "unverified"
    assert grouped("M-01 is due 2026-12-10 and M-02 is due 2026-11-20.",
                   cites(2, 3))["status"] == "unverified"
