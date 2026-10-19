"""Regression cases from the bounded live investigation, using fictional evidence."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from syden_agent.agent import (
    _ask_openai,
    _cached_tool,
    _final_answer,
    _verified_numeric_answer,
    ask,
)
from syden_agent.claim_verifier import question_parts, validate_claims
from syden_agent.db import connect
from syden_agent.tools import query_spreadsheet


def _index(*items):
    conn = connect(":memory:")
    citations = []
    for number, (name, kind, source) in enumerate(items, 1):
        conn.execute("INSERT INTO documents(id,path,kind,status) VALUES(?,?,?,'ready')",
                     (number, name, kind))
        if kind == "docx":
            conn.execute("INSERT INTO word_blocks(document_id,ordinal,kind,location,section,text) "
                         "VALUES(?,1,'paragraph','paragraph 1','',?)", (number, source))
            citations.append(f"{name} | paragraph 1")
        else:
            conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES(?,1,0,?)",
                         (number, source))
            citations.append(f"{name} | page 1 | chunk 0")
    conn.commit()
    return conn, citations


def _draft(*claims):
    return json.dumps({"answer": "Summary", "insufficient": False, "claims": claims})


def _claim(text, cite, quote="", part=None):
    result = {"text": text, "supports": [{"citation": cite, "quote": quote}]}
    if part is not None:
        result["question_part"] = part
    return result


def test_local_spans_accept_atomic_count_but_reject_wrong_count_and_fake_quote():
    source = "Four circuits passed and two circuits require retesting."
    conn, [cite] = _index(("QA.pdf", "pdf", source))
    result = validate_claims(conn, _draft(
        _claim("Four circuits passed inspection.", cite, source),
        _claim("Two circuits require retesting.", cite),
        _claim("Five circuits passed inspection.", cite, source),
        _claim("Four circuits passed inspection.", cite, "Five circuits passed."),
    ), [cite])
    assert [item["status"] for item in result["claims"]] == [
        "evidence_linked", "deterministically_verified", "unverified", "unverified"]
    assert result["claims"][0]["quotes"][0]["quote"] == source
    assert result["claims"][0]["quotes"][0]["start"] == 0


def test_filename_scope_is_per_question_part():
    conn, (pdf, word) = _index(
        ("Notice.pdf", "pdf", "LR-09 is proposed and has not been approved."),
        ("Scope.docx", "docx", "The contractor shall install four fire doors."),
    )
    question = ("What is the status of LR-09, and what shall the contractor install "
                "according to Scope.docx?")
    result = validate_claims(conn, _draft(
        _claim("LR-09 is proposed and has not been approved.", pdf,
               "LR-09 is proposed and has not been approved.", 0),
        _claim("The contractor shall install four fire doors.", word,
               "The contractor shall install four fire doors.", 1),
        _claim("LR-09 is proposed and has not been approved.", pdf,
               "LR-09 is proposed and has not been approved.", 1),
    ), [pdf, word], question)
    assert [item["status"] for item in result["claims"]] == [
        "deterministically_verified", "deterministically_verified", "unverified"]


def test_introductory_file_scope_carries_to_following_count_parts():
    question = ("According to QA.pdf, how many circuits passed inspection, "
                "and how many require retesting?")
    assert len(question_parts(question)) == 2
    conn, (qa, other) = _index(
        ("QA.pdf", "pdf", "Four circuits passed and two require retesting."),
        ("Other.pdf", "pdf", "Nine circuits passed."),
    )
    result = validate_claims(conn, _draft(
        _claim("Two require retesting.", qa, "two require retesting.", 1),
        _claim("Nine circuits passed.", other, "Nine circuits passed.", 1),
    ), [qa, other], question)
    assert [item["status"] for item in result["claims"]] == [
        "deterministically_verified", "unverified"]


def test_status_and_amount_can_use_separate_lines_of_one_cited_page():
    source = ("CO-07 status: approved.\nOriginal sum: SAR 6,750,000.\n"
              "Revised contract sum including CO-07: SAR 7,070,000.")
    conn, [cite] = _index(("Change.pdf", "pdf", source))
    result = validate_claims(conn, _draft(_claim(
        "After approved CO-07, the revised contract sum is SAR 7,070,000.",
        cite, "Revised contract sum including CO-07: SAR 7,070,000.")), [cite])
    assert result["status"] == "evidence_linked"
    assert result["sources"] == [cite]


def test_typographic_identifier_hyphen_does_not_become_a_fake_number():
    source = "Revised contract sum including CO-07: SAR 7,070,000."
    conn, [cite] = _index(("Change.pdf", "pdf", source))
    result = validate_claims(conn, _draft(_claim(
        "The revised contract sum after CO‑07 is SAR 7,070,000.", cite, source)), [cite])
    assert result["status"] == "evidence_linked"


def test_wrong_record_quantity_and_decision_are_rejected():
    source = "Pump A has four units and Pump B has eight units. PO-15 was rejected."
    conn, [cite] = _index(("Register.pdf", "pdf", source))
    result = validate_claims(conn, _draft(
        _claim("Pump A has eight units.", cite, source),
        _claim("PO-15 was approved.", cite, source),
    ), [cite])
    assert all(item["status"] == "unverified" for item in result["claims"])


def test_recovered_error_and_bounded_search_do_not_downgrade_supported_fact():
    source = "The revised sum is SAR 7,070,000."
    conn, [cite] = _index(("Change.pdf", "pdf", source))
    answer = _final_answer(conn, _draft(_claim(source, cite, source)), [cite], [
        {"name": "list_documents", "ok": False},
        {"name": "list_documents", "ok": True},
        {"name": "search_documents", "ok": True, "truncated": True},
    ], "What is the revised sum?", structured_mode=True)
    assert answer.verification_status == "deterministically_verified"
    assert "Retrieval was incomplete" not in answer.text
    exhaustive = _final_answer(conn, _draft(_claim(source, cite, source)), [cite], [
        {"name": "search_documents", "ok": True, "truncated": True},
    ], "List all revised sums", structured_mode=True)
    assert exhaustive.verification_status == "evidence_linked"


def test_failed_local_tool_call_can_recover_on_retry(monkeypatch):
    from syden_agent import agent

    responses = [{"error": "transient failure"}, {"documents": []}]
    monkeypatch.setattr(agent, "_execute", lambda *_: responses.pop(0))
    conn = connect(":memory:")
    cache = {}
    first, repeated_first = _cached_tool(conn, "list_documents", {}, cache)
    second, repeated_second = _cached_tool(conn, "list_documents", {}, cache)
    assert first == {"error": "transient failure"}
    assert second == {"documents": []}
    assert not repeated_first and not repeated_second


def test_ambiguous_singular_contract_requests_clarification_before_provider():
    conn, _ = _index(("Main_Contract.pdf", "pdf", "Scope A."),
                     ("Other_Contract.pdf", "pdf", "Scope B."))
    answer = ask(conn, "Summarize the scope in the contract.")
    assert "Please name the document" in answer.text
    assert "Main_Contract.pdf" in answer.text
    assert "Other_Contract.pdf" in answer.text
    assert not answer.tool_calls


def test_unrelated_financial_pdf_does_not_make_boq_incomplete():
    conn, _ = _index(("Change_Notice.pdf", "pdf", "Approved increase: SAR 900,000."))
    conn.execute("INSERT INTO pdf_boq_rows(document_id,page,table_num,row_num,cells_json,method) "
                 "VALUES(1,1,1,0,?,'text_lines'),(1,1,1,1,?,'text_lines')", (
                     json.dumps({"A": {"value": "Item"}, "B": {"value": "Amount"}}),
                     json.dumps({"A": {"value": "Approved increase"},
                                 "B": {"value": 900000}})))
    result = query_spreadsheet(conn, operator="all", value=0)
    assert result["warnings"] == []
    assert not result["incomplete"]
    assert not result["matches"]


def test_multiple_workbook_subtotals_are_separate():
    conn = connect(":memory:")
    for number, name, amount in ((1, "East_BOQ.xlsx", 1250000),
                                 (2, "West_BOQ.xlsx", 1500000)):
        conn.execute("INSERT INTO documents(id,path,kind,status) VALUES(?,?,'xlsx','ready')",
                     (number, name))
        for row_number, values in ((1, {"A": "Item", "B": "Amount (SAR)"}),
                                   (2, {"A": f"ITEM-{number}", "B": amount})):
            cells = {col: {"value": value} for col, value in values.items()}
            conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                         "VALUES(?,?,?,?)", (number, "BOQ", row_number, json.dumps(cells)))
    result = query_spreadsheet(conn, operator="all", value=0, currency="SAR")
    assert result["matched_amount_sums"] == {"SAR": "2750000"}
    assert result["matched_amount_sums_by_file"] == {
        "East_BOQ.xlsx": {"SAR": "1250000"},
        "West_BOQ.xlsx": {"SAR": "1500000"},
    }
    answer = _verified_numeric_answer(conn, "What are all BOQ costs?", {
        "operator": "all", "value": 0, "currency": "SAR"}, [])
    assert "East_BOQ.xlsx" in answer.text and "West_BOQ.xlsx" in answer.text
    assert "2750000" in answer.text


def test_repeated_provider_searches_stop_after_one_reminder(monkeypatch):
    conn, _ = _index(("Memo.pdf", "pdf", "The fictional code is ARBOR-17."))
    attempts = []

    def create(**kwargs):
        attempts.append(kwargs)
        call = SimpleNamespace(id=f"call_{len(attempts)}", function=SimpleNamespace(
            name="search_documents", arguments='{"query":"ARBOR-17"}'))
        message = SimpleNamespace(tool_calls=[call], content=None,
                                  model_dump=lambda exclude_none: {
                                      "role": "assistant", "tool_calls": []})
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_: client))
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-only")
    answer = _ask_openai(conn, "What is the fictional code?", 6)
    assert len(attempts) == 3
    assert "repeated" in answer.text.lower()
    assert [item.get("reused") for item in answer.tool_calls] == [False, True, True]


def test_malformed_compatible_json_gets_one_generation_retry(monkeypatch):
    conn, [cite] = _index(("Memo.pdf", "pdf", "The fictional code is ARBOR-17."))
    calls = []
    responses = [
        SimpleNamespace(tool_calls=[SimpleNamespace(id="one", function=SimpleNamespace(
            name="search_documents", arguments='{"query":"ARBOR-17"}'))],
            content=None, model_dump=lambda exclude_none: {"role": "assistant", "tool_calls": []}),
        SimpleNamespace(tool_calls=None, content='{"answer":"ARBOR-17","claims":[bad]}'),
        SimpleNamespace(tool_calls=None, content=_draft(_claim(
            "The fictional code is ARBOR-17.", cite,
            "The fictional code is ARBOR-17."))),
    ]

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=responses.pop(0))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_: client))
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-only")
    monkeypatch.setenv("OLLAMA_MODEL", "mock-model")
    answer = _ask_openai(conn, "What is the fictional code?", 4, provider="ollama_cloud")
    assert answer.verification_status == "deterministically_verified"
    assert len(calls) == 3
    assert calls[-1]["tool_choice"] == "none"
    assert any(item["name"] == "format_retry" for item in answer.tool_calls)


def test_false_acceptance_and_rejection_counts_for_comparable_facts():
    source = "Batch Q-17 passed with 4 circuits. Batch Q-18 failed with 2 circuits."
    conn, [cite] = _index(("Checks.pdf", "pdf", source))
    cases = [
        ("Batch Q-17 passed with four circuits.", True),
        ("Batch Q-18 failed with two circuits.", True),
        ("Batch Q-17 passed with five circuits.", False),
        ("Batch Q-18 passed with two circuits.", False),
    ]
    outcomes = [validate_claims(conn, _draft(_claim(text, cite, source)), [cite])[
        "status"] != "unverified" for text, _ in cases]
    assert sum(actual and not expected for actual, (_, expected) in zip(
        outcomes, cases, strict=True)) == 0
    assert sum(not actual and expected for actual, (_, expected) in zip(
        outcomes, cases, strict=True)) == 0


def test_role_reversal_remains_only_evidence_linked_not_proven():
    source = "The consultant shall coordinate with the vendor on commissioning."
    conn, [cite] = _index(("Scope.pdf", "pdf", source))
    result = validate_claims(conn, _draft(_claim(
        "The vendor shall coordinate with the consultant on commissioning.",
        cite, source)), [cite])
    assert result["status"] == "evidence_linked"
    assert "not independently proven" in result["claims"][0]["reason"]
