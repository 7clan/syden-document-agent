"""The active answer path checks citations without rejecting model prose."""
from __future__ import annotations

import json

from syden_agent.agent import _question_date_context, _source_linked_answer
from syden_agent.db import connect


def _sources():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Fresh.xls','xls','ready'),(2,'Terms.pdf','pdf','ready')")
    rows = {
        4: ["G-01", "Final commissioning", "2028-02-14", "Contractual", "Approved"],
        5: ["G-02", "Optional antenna trial", "2028-03-21", "Planning", "Not approved"],
    }
    for number, values in rows.items():
        cells = {chr(65 + index): {"value": value}
                 for index, value in enumerate(values)}
        conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                     "VALUES(1,'Gates',?,?)", (number, json.dumps(cells)))
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(2,1,0,'The architect handed drawings to the contractor.')")
    return conn


def _draft(claim, *citations, quote=""):
    return json.dumps({"answer": claim, "insufficient": False, "claims": [{
        "text": claim, "supports": [{"citation": citation, "quote": quote}
                                    for citation in citations],
    }]})


def test_correct_grouped_xls_dates_survive_without_semantic_rejection():
    conn = _sources()
    first, second = "Fresh.xls | Gates | row 4", "Fresh.xls | Gates | row 5"
    claim = "G-01 is due 2028-02-14 and G-02 is due 2028-03-21."
    answer = _source_linked_answer(conn, _draft(claim, first, second),
                                   [first, second], [{"name": "get_evidence", "ok": True}])
    assert claim in answer.text
    assert answer.sources == [first, second]
    assert answer.verification_status == "evidence_linked"
    assert answer.claims[0]["quotes"][0]["quote"].startswith("A: G-01")
    assert answer.tool_calls[-1]["name"] == "source_linking"


def test_model_quote_is_ignored_in_favor_of_original_indexed_text():
    conn = _sources()
    citation = "Terms.pdf | page 1 | chunk 0"
    answer = _source_linked_answer(
        conn, _draft("The contractor received drawings.", citation,
                     quote="The contractor approved drawings."), [citation],
        [{"name": "search_documents", "ok": True}])
    assert answer.verification_status == "evidence_linked"
    assert answer.claims[0]["quotes"][0]["quote"] == (
        "The architect handed drawings to the contractor.")


def test_unretrieved_or_fabricated_reference_is_flagged_but_claim_is_visible():
    conn = _sources()
    citation = "Terms.pdf | page 1 | chunk 0"
    claim = "The contractor received drawings."
    for observed in ([], ["Invented.pdf | page 1 | chunk 0"]):
        answer = _source_linked_answer(conn, _draft(claim, citation), observed,
                                       [{"name": "search_documents", "ok": True}])
        assert claim in answer.text
        assert answer.sources == []
        assert answer.verification_status == "unverified"
        assert "source reference unavailable" in answer.text


def test_source_linking_does_not_claim_to_verify_wrong_interpretation():
    conn = _sources()
    citation = "Terms.pdf | page 1 | chunk 0"
    wrong = "The contractor handed drawings to the architect."
    answer = _source_linked_answer(conn, _draft(wrong, citation), [citation],
                                   [{"name": "get_evidence", "ok": True}])
    assert wrong in answer.text
    assert answer.claims[0]["status"] == "evidence_linked"
    assert answer.claims[0]["reason"] == (
        "Retrieved source; model interpretation was not checked")


def test_numeric_questions_still_use_deterministic_spreadsheet_result():
    conn = _sources()
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(3,'Prices.xlsx','xlsx','ready')")
    for number, values in {1: ["Item", "Total Amount (SAR)"],
                           2: ["Panel", 1_250_000],
                           3: ["Relay", 1_000_000]}.items():
        cells = {chr(65 + index): {"value": value}
                 for index, value in enumerate(values)}
        conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                     "VALUES(3,'BOQ',?,?)", (number, json.dumps(cells)))
    answer = _source_linked_answer(
        conn, "This model text is not used for totals.", [],
        [{"name": "query_spreadsheet", "ok": True}],
        "List BOQ cost items above SAR 1,000,000 in Prices.xlsx",
        {"file": "Prices.xlsx", "currency": "SAR", "operator": "gt", "value": 1_000_000})
    assert answer.verification_status == "deterministically_verified"
    assert answer.structured["matched_amount_sum"] == "1250000"
    assert answer.sources == ["Prices.xlsx | BOQ!B2"]


def test_date_claim_cannot_borrow_unrelated_retrieved_citations():
    conn = _sources()
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(3,'Decision.docx','docx','ready')")
    conn.execute("INSERT INTO word_blocks(document_id,ordinal,kind,location,section,text) "
                 "VALUES(3,1,'paragraph','paragraph 1','',"
                 "'The proposed 15 October 2029 handover was not approved.')")
    contract = "Fresh.xls | Gates | row 4"
    decision = "Decision.docx | paragraph 1"
    claim = "The proposed 15 October 2029 handover was not approved."
    wrong = _source_linked_answer(conn, _draft(claim, contract), [contract, decision],
                                  [{"name": "search_documents", "ok": True}])
    assert wrong.claims[0]["status"] == "unverified"
    assert wrong.claims[0]["reason"] == "Claimed date absent from cited passages"
    assert wrong.sources == [contract]  # Still inspectable, never silently rewritten.
    correct = _source_linked_answer(conn, _draft(claim, decision), [contract, decision],
                                    [{"name": "search_documents", "ok": True}])
    assert correct.claims[0]["status"] == "evidence_linked"


def test_question_date_lookup_finds_decision_in_other_document():
    conn = _sources()
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(3,'Inspection.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES"
                 "(3,1,0,'The proposed 15 October 2029 handover was not approved.')")
    context, citations = _question_date_context(
        conn, "Did the change order approve 15 October 2029?", set())
    assert citations == ["Inspection.pdf | page 1 | chunk 0"]
    assert "not approved" in context


def test_date_status_question_hands_off_other_file_rows_without_inventing_status():
    conn = _sources()
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES"
                 "(2,2,0,'The binding final handover deadline is 14 February 2028.')")
    question = ("What is the contractual handover date? Distinguish it from "
                "planning or proposed dates in other files.")
    context, citations = _question_date_context(conn, question, set())
    assert "Fresh.xls | Gates!C5" in citations
    assert "2028-03-21" in context
    assert "Planning" in context
    assert "Not approved" in context
    assert "Terms.pdf | page 2 | chunk 0" not in citations
    assert _question_date_context(conn, "Did the deadline change?", set()) == ("", [])


def test_date_anchor_accepts_source_iso_and_claim_month_name():
    conn = _sources()
    citation = "Fresh.xls | Gates | row 4"
    claim = "Final commissioning is due 14 February 2028."
    answer = _source_linked_answer(conn, _draft(claim, citation), [citation],
                                   [{"name": "inspect_document", "ok": True}])
    assert answer.claims[0]["status"] == "evidence_linked"
