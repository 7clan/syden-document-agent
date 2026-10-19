"""Domain-independent entailment checks: unseen prose, numbers and source integrity."""
from __future__ import annotations

import json

from syden_agent.agent import _final_answer
from syden_agent.db import connect
from syden_agent.semantic_verifier import (
    parse_judgement,
    verification_request,
    verify_judgement,
)


def _source(citation_text: str):
    conn = connect(":memory:")
    conn.execute(
        "INSERT INTO documents(path,kind,status) VALUES('Independent_Report.pdf','pdf','ready')"
    )
    conn.execute(
        "INSERT INTO passages(document_id,page,chunk,text) VALUES(1,1,0,?)",
        (citation_text,),
    )
    return conn, "Independent_Report.pdf | page 1 | chunk 0"


def _judge(cite, quote, supported=True, complete=True):
    return {
        "supported": supported,
        "complete": complete,
        "supporting_quotes": [{"citation": cite, "quote": quote}],
    }


def test_semantic_fallback_accepts_different_wording_with_literal_source_proof():
    source = "Two independent samples failed the laboratory quality control check."
    conn, cite = _source(source)
    try:
        proposed = "The lab's quality checks failed for 2 independent samples."
        answer = _final_answer(
            conn, proposed, [cite], [{"name": "search_documents", "ok": True}],
            "How many samples failed QC?",
            semantic_checker=lambda _q, _a, _e: _judge(cite, source),
        )
        assert answer.text == proposed
        assert answer.sources == [cite]
        assert any(x["name"] == "semantic_verification" and x["ok"]
                   for x in answer.tool_calls)
    finally:
        conn.close()


def test_invented_number_rejected_even_if_external_semantic_judge_approves():
    source = "The original invoice contains four pallets and an agreed fee of USD 4,500."
    conn, cite = _source(source)
    try:
        answer = _final_answer(
            conn, "The invoice includes 5 pallets costing USD 4,500.",
            [cite], [{"name": "get_evidence", "ok": True}],
            "What is included?",
            semantic_checker=lambda _q, _a, _e: _judge(cite, source),
        )
        assert "could not be verified" in answer.text
        assert any(x["name"] == "answer_verification" and not x["ok"]
                   for x in answer.tool_calls)
    finally:
        conn.close()


def test_invented_quote_and_document_level_only_are_never_verified():
    cite = "Independent_Report.pdf | page 1 | chunk 0"
    actual = {cite: "Shipment shall be delivered on 22 June 2027."}
    claim = "Delivery is scheduled for 22 June 2027."
    assert verify_judgement(
        _judge(cite, "Shipment was delivered on 22 June 2027."),
        actual, claim,
    ) == (False, [])
    assert verify_judgement(
        _judge("Independent_Report.pdf | document", actual[cite]),
        actual, claim,
    ) == (False, [])


def test_numbers_must_occur_in_selected_quote_not_anywhere_else_in_document():
    cite = "Independent_Report.pdf | page 1 | chunk 0"
    actual = {
        cite: "The approved batch contains 40 parts. The rejected batch contains 90 parts."
    }
    claim = "The approved batch contains 90 parts."
    assert verify_judgement(
        _judge(cite, "The approved batch contains 40 parts."),
        actual, claim,
    ) == (False, [])


def test_semantic_verification_rejects_uncertain_and_incomplete_verdicts():
    cite = "Independent_Report.pdf | page 1 | chunk 0"
    evidence = {cite: "The committee denied the budget request."}
    claim = "The budget request was approved."
    assert verify_judgement(
        _judge(cite, evidence[cite], supported=False),
        evidence, claim,
    ) == (False, [])
    assert verify_judgement(
        _judge(cite, evidence[cite], complete=False),
        evidence, claim,
    ) == (False, [])
    assert verify_judgement("This seems fine.", evidence, claim) == (False, [])


def test_multiple_source_quotes_can_support_combined_but_valid_paraphrase():
    a = "Change.pdf | page 1 | chunk 0"
    b = "Contract.pdf | page 3 | chunk 0"
    evidence = {
        a: "The variation authorizes 3 additional distribution boards.",
        b: "The original completion deadline remains 31 March 2027.",
    }
    verdict = {
        "supported": True, "complete": True, "supporting_quotes": [
            {"citation": a, "quote": evidence[a]},
            {"citation": b, "quote": evidence[b]},
        ],
    }
    approved, citations = verify_judgement(
        verdict, evidence,
        "Three additional distribution boards were authorized, with "
        "the deadline unchanged at 31 March 2027.",
    )
    assert approved
    assert citations == [a, b]


def test_json_wire_protocol_and_request_include_only_supplied_sources():
    cite = "A.pdf | page 1 | chunk 0"
    verdict = _judge(cite, "The answer comes from this sentence.")
    assert parse_judgement(json.dumps(verdict)) == verdict
    request = json.loads(verification_request(
        "What happened?", "The answer comes from this sentence.",
        {cite: "The answer comes from this sentence."},
    ))
    assert request["indexed_evidence"] == [
        {"citation": cite, "text": "The answer comes from this sentence."}
    ]
