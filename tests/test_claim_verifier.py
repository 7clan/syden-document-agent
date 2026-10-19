"""Independent evidence-first claim tests using unfamiliar synthetic statements."""
from __future__ import annotations

import json

from syden_agent.agent import _final_answer
from syden_agent.claim_verifier import validate_claims
from syden_agent.db import connect


def _index(*passages):
    conn = connect(":memory:")
    citations = []
    for index, (name, text) in enumerate(passages, 1):
        conn.execute("INSERT INTO documents(id,path,kind,status) VALUES(?,?,?,?)",
                     (index, name, "pdf", "ready"))
        conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES(?,?,?,?)",
                     (index, 1, 0, text))
        citations.append(f"{name} | page 1 | chunk 0")
    conn.commit()
    return conn, citations


def _draft(claims, *, insufficient=False, answer="Summary"):
    return json.dumps({"answer": answer, "insufficient": insufficient,
                       "claims": claims})


def _claim(text, *supports):
    return {"text": text, "supports": [
        {"citation": citation, "quote": quote} for citation, quote in supports]}


def test_paraphrase_and_spelled_out_numbers_are_evidence_linked_without_extra_call():
    source = "Four circuits passed and two circuits require retesting."
    conn, [cite] = _index(("Inspection.pdf", source))
    answer = _final_answer(
        conn, _draft([_claim("4 circuits passed inspection; 2 need another test.",
                             (cite, source))]), [cite],
        [{"name": "search_documents", "ok": True}], structured_mode=True)
    assert answer.verification_status == "evidence_linked"
    assert "4 circuits passed" in answer.text
    assert answer.sources == [cite]
    assert len(answer.tool_calls) == 2  # Retrieval and local validation only.


def test_exact_source_text_is_deterministically_verified():
    source = "The vendor shall submit revised drawings by 20 May 2027."
    conn, [cite] = _index(("Terms.pdf", source))
    result = validate_claims(conn, _draft([_claim(source, (cite, source))]), [cite])
    assert result["status"] == "deterministically_verified"
    misleading = validate_claims(conn, _draft([_claim(source, (cite, source))],
                                          answer="All 100 vendors were approved."), [cite])
    assert "100 vendors" not in misleading["answer"]


def test_word_paragraph_and_excel_row_support_use_real_index_locations():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Minutes.docx','docx','ready'),(2,'Register.xlsx','xlsx','ready')")
    conn.execute("INSERT INTO word_blocks(document_id,ordinal,kind,location,section,text) "
                 "VALUES(1,1,'paragraph','paragraph 1','','The committee proposed a pump test.')")
    conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                 "VALUES(2,'Checks',2,?)", (json.dumps({
                     "A": {"value": "Pumps"}, "B": {"value": "accepted"},
                     "C": {"value": 4}}),))
    word = "Minutes.docx | paragraph 1"
    excel = "Register.xlsx | Checks!C2"
    result = validate_claims(conn, _draft([
        _claim("A pump test was proposed.",
               (word, "The committee proposed a pump test.")),
        _claim("Four pumps were accepted.", (excel, "Pumps accepted 4")),
    ]), [word, excel])
    assert result["status"] == "evidence_linked"
    assert result["sources"] == [word, excel]


def test_pdf_line_wrap_is_allowed_in_an_exact_quote():
    conn, [cite] = _index(("Report.pdf", "The transformer was inspected\n"
                          + "and passed the factory test. The re-\ninspection was complete."))
    result = validate_claims(conn, _draft([
        _claim("The transformer passed the factory test.",
               (cite, "The transformer was inspected and passed the factory test.")),
    ]), [cite])
    assert result["status"] == "evidence_linked"
    hyphenated = validate_claims(conn, _draft([
        _claim("The reinspection was complete.",
               (cite, "The reinspection was complete.")),
    ]), [cite])
    assert hyphenated["status"] == "deterministically_verified"


def test_equivalent_date_formats_match_but_changed_date_fails():
    source = "Submission of drawings is due Nov 15, 2026."
    conn, [cite] = _index(("Schedule.pdf", source))
    correct = validate_claims(conn, _draft([
        _claim("Drawing submission is due 2026-11-15.", (cite, source)),
    ]), [cite])
    wrong = validate_claims(conn, _draft([
        _claim("Drawing submission is due 2026-11-16.", (cite, source)),
    ]), [cite])
    assert correct["status"] == "evidence_linked"
    assert wrong["status"] == "unverified"


def test_incorrect_amount_currency_date_identifier_and_invented_quote_are_rejected():
    source = "Invoice INV-42 records USD 4,500 payable on 20 May 2027."
    conn, [cite] = _index(("Invoice.pdf", source))
    claims = [
        _claim("Invoice INV-42 records USD 5,500.", (cite, source)),
        _claim("Invoice INV-42 records EUR 4,500.", (cite, source)),
        _claim("Invoice INV-43 records USD 4,500.", (cite, source)),
        _claim("Payment is due on 21 May 2027.", (cite, source)),
        _claim("Invoice INV-42 was paid.", (cite, "Invoice INV-42 was paid.")),
    ]
    result = validate_claims(conn, _draft(claims), [cite])
    assert result["status"] == "unverified"
    assert all(item["status"] == "unverified" for item in result["claims"])
    assert "paid" not in result["answer"].lower()


def test_negation_approval_and_authentic_quote_with_wrong_conclusion_fail():
    source = "The proposed change was not approved; excavation remains excluded."
    conn, [cite] = _index(("Variation.pdf", source))
    result = validate_claims(conn, _draft([
        _claim("The change was approved.", (cite, source)),
        _claim("Excavation is included.", (cite, source)),
    ]), [cite])
    assert all(item["status"] == "unverified" for item in result["claims"])


def test_conflicting_documents_and_multiple_passages():
    conn, (a, b) = _index(
        ("Memo_A.pdf", "The change was approved on 14 June 2027."),
        ("Memo_B.pdf", "The change was rejected on 15 June 2027."),
    )
    conflict = validate_claims(conn, _draft([
        _claim("The change was approved.",
               (a, "The change was approved on 14 June 2027."),
               (b, "The change was rejected on 15 June 2027.")),
    ]), [a, b])
    assert conflict["status"] == "unverified"
    assert "conflicting" in conflict["claims"][0]["reason"].lower()
    separate = validate_claims(conn, _draft([
        _claim("Memo A approved the change.",
               (a, "The change was approved on 14 June 2027.")),
        _claim("Memo B rejected the change.",
               (b, "The change was rejected on 15 June 2027.")),
    ]), [a, b])
    assert separate["status"] == "evidence_linked"
    assert separate["sources"] == [a, b]


def test_cherry_picked_quote_cannot_hide_retrieved_identifier_conflict():
    conn, (a, b) = _index(
        ("Approval.pdf", "Change CO-07 was approved."),
        ("Revision.pdf", "Change CO-07 was rejected."),
    )
    result = validate_claims(conn, _draft([
        _claim("Change CO-07 was approved.", (a, "Change CO-07 was approved.")),
    ]), [a, b])
    assert result["status"] == "unverified"
    assert b in result["claims"][0]["reason"]


def test_fabricated_citation_irrelevant_citation_and_wrong_named_file_fail():
    conn, (a, b) = _index(
        ("A.pdf", "The switchboard was inspected."),
        ("B.pdf", "The roof coating was renewed."),
    )
    missing = "Made_up.pdf | page 1 | chunk 0"
    result = validate_claims(conn, _draft([
        _claim("The switchboard was inspected.", (missing, "The switchboard was inspected.")),
        _claim("The switchboard was inspected.", (b, "The roof coating was renewed.")),
        _claim("The switchboard was inspected.", (a, "The switchboard was inspected.")),
    ]), [a, b])
    assert [item["status"] for item in result["claims"]] == [
        "unverified", "unverified", "deterministically_verified"]
    named = validate_claims(conn, _draft([
        _claim("The roof coating was renewed.", (b, "The roof coating was renewed.")),
    ]), [a, b], "What does A.pdf say?")
    assert named["status"] == "unverified"


def test_malformed_absent_and_incomplete_retrieval_fail_safely():
    source = "The handover register records three open defects."
    conn, [cite] = _index(("Register.pdf", source))
    malformed = _final_answer(conn, "The register has zero defects.", [cite],
                              [{"name": "search_documents", "ok": True}],
                              structured_mode=True)
    assert malformed.verification_status == "unverified"
    assert "zero defects" not in malformed.text
    absent = validate_claims(conn, _draft([], insufficient=True), [cite])
    assert absent["status"] == "unverified"
    partial = _final_answer(
        conn, _draft([_claim(source, (cite, source))]), [cite],
        [{"name": "search_documents", "ok": True, "truncated": True},
         {"name": "get_evidence", "ok": False}], structured_mode=True)
    assert partial.verification_status == "evidence_linked"
    assert "Retrieval was incomplete" in partial.text


def test_claim_statuses_bound_false_acceptance_and_paraphrase_rejection():
    conn, [cite] = _index(("Report.pdf", "Seven pumps passed acceptance testing."))
    cases = [
        ("7 pumps passed acceptance tests.", "evidence_linked"),
        ("8 pumps passed acceptance tests.", "unverified"),
        ("Seven pumps failed acceptance testing.", "unverified"),
    ]
    outcomes = [validate_claims(conn, _draft([_claim(text, (cite,
                "Seven pumps passed acceptance testing."))]), [cite])["status"]
                for text, _ in cases]
    assert outcomes == [expected for _, expected in cases]
    false_acceptances = sum(expected == "unverified" and actual != "unverified"
                            for actual, (_, expected) in zip(outcomes, cases, strict=True))
    false_rejections = sum(expected != "unverified" and actual == "unverified"
                           for actual, (_, expected) in zip(outcomes, cases, strict=True))
    assert (false_acceptances, false_rejections) == (0, 0)
    # A paraphrase is retained, while contradictory pass/fail wording is rejected.
    assert sum(status == "deterministically_verified" for status in outcomes) == 0
