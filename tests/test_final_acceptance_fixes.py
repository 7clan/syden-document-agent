"""General regressions found during the six-document acceptance run."""
from __future__ import annotations

import json
from types import SimpleNamespace

from google import genai
from google.genai import types

from syden_agent.agent import (
    _ask_gemini,
    _checked_financial_comparison,
    _financial_comparison_context,
    _matching_sheet_context,
    _source_linked_answer,
    _verified_numeric_answer,
)
from syden_agent.db import connect


def _row(conn, document_id, sheet, number, values):
    cells = {chr(65 + index): {"value": value}
             for index, value in enumerate(values)}
    conn.execute("INSERT INTO sheet_rows(document_id,sheet,row_num,cells_json) "
                 "VALUES(?,?,?,?)", (document_id, sheet, number, json.dumps(cells)))


def _financial_index():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Terms.pdf','pdf','ready'),"
                 "(2,'Costs.xlsx','xlsx','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES(1,2,0,?)",
                 (("The original signed contract value is SAR 2,000,000. "
                   "The selected-items BOQ is not the complete contract sum."),))
    for sheet, entries in {
        "Base Costs": [("A-01", 600_000), ("A-02", 300_000)],
        "Approved Variation": [("V-01", 100_000)],
    }.items():
        _row(conn, 2, sheet, 1, ["Item Code", "Approved Amount (SAR)"])
        for number, (identifier, amount) in enumerate(entries, 2):
            _row(conn, 2, sheet, number, [identifier, amount])
    return conn


def test_cross_document_amounts_are_retrieved_separately():
    conn = _financial_index()
    question = "Does the selected-items BOQ subtotal equal the contract sum?"
    context, citations, incomplete = _financial_comparison_context(conn, question)
    assert not incomplete
    assert "Costs.xlsx | Base Costs: SAR 900000" in context
    assert "Costs.xlsx | Approved Variation: SAR 100000" in context
    assert "original signed contract value is SAR 2,000,000" in context
    assert "Terms.pdf | page 2 | chunk 0" in citations
    assert "Costs.xlsx | Base Costs!B2" in citations
    assert "Costs.xlsx | Base Costs!B3" in citations
    assert "Costs.xlsx | Approved Variation!B2" in citations


def test_financial_comparison_checks_original_values_in_code():
    conn = _financial_index()
    question = "Does the selected-items BOQ subtotal equal the contract sum?"
    answer = _checked_financial_comparison(conn, question,
                                           [{"name": "list_documents", "ok": True}])
    assert answer is not None
    assert answer.structured == {"boq_subtotal": "900000", "contract_value": "2000000",
                                 "currency": "SAR", "boq_sheet": "Base Costs"}
    assert answer.text.startswith("No.")
    assert "Costs.xlsx | Base Costs!B2" in answer.sources
    assert "Costs.xlsx | Base Costs!B3" in answer.sources
    assert "Costs.xlsx | Approved Variation!B2" not in answer.sources
    assert "Terms.pdf | page 2 | chunk 0" in answer.sources
    assert answer.tool_calls[-1]["origin"] == "application"
    assert answer.tool_calls[-1]["arithmetic_checked"] is True


def test_financial_comparison_abstains_if_base_sheet_is_ambiguous():
    conn = _financial_index()
    _row(conn, 2, "Other Base", 1, ["Item", "Approved Amount (SAR)"])
    _row(conn, 2, "Other Base", 2, ["B-01", 75_000])
    assert _checked_financial_comparison(
        conn, "Does the BOQ subtotal equal the contract sum?",
        [{"name": "list_documents", "ok": True}]) is None


def test_original_value_comparator_does_not_answer_revised_sum_question():
    assert _checked_financial_comparison(
        _financial_index(), "Does the BOQ subtotal equal the revised contract sum?",
        [{"name": "list_documents", "ok": True}]) is None


def test_original_comparison_with_revised_amount_checks_all_operands():
    conn = _financial_index()
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES(1,3,0,?)",
                 (("Approved variation V3. Approved price increase: SAR 100,000. "
                   "Revised contract sum: SAR 2,100,000."),))
    answer = _checked_financial_comparison(
        conn, "Does the selected-items subtotal equal the original contract sum? "
              "Also give the V3 increase and revised contract sum.",
        [{"name": "list_documents", "ok": True}])
    assert answer is not None
    assert answer.structured["boq_subtotal"] == "900000"
    assert answer.structured["price_increase"] == "100000"
    assert answer.structured["revised_contract_sum"] == "2100000"
    assert "Terms.pdf | page 3 | chunk 0" in answer.sources


def test_generic_cost_item_phrase_does_not_select_an_item_code():
    conn = _financial_index()
    answer = _verified_numeric_answer(
        conn, "List every cost item strictly above SAR 250,000 in Costs.xlsx.",
        {"file": "Costs.xlsx", "sheet": "Base Costs", "operator": "gt", "value": 250000},
        [{"name": "query_spreadsheet", "ok": True}])
    assert answer.verification_status == "deterministically_verified"
    assert answer.structured["total_matches"] == 2
    assert answer.structured["matched_amount_sums"] == {"SAR": "900000"}


def test_matching_sheet_context_includes_each_row_and_location():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Timeline.xlsx','xlsx','ready')")
    for number, status in enumerate(["Approved", "Proposed", "Not approved"], 2):
        _row(conn, 1, "Milestones", number, [f"G-{number}", status])
    context, citations, incomplete = _matching_sheet_context(
        conn, "Which milestones are approved or proposed?")
    assert not incomplete
    assert len(citations) == 3
    assert "Timeline.xlsx | Milestones | row 4: A: G-4 | B: Not approved" in context


def test_wrong_model_comparison_with_real_sources_is_not_deterministic():
    conn = _financial_index()
    citations = ["Costs.xlsx | Base Costs!B2", "Terms.pdf | page 2 | chunk 0"]
    claim = "The BOQ subtotal is SAR 600,000, so it equals the contract sum."
    payload = json.dumps({"answer": claim, "insufficient": False,
                          "claims": [{"text": claim, "supports": [
                              {"citation": cite} for cite in citations]}]})
    answer = _source_linked_answer(conn, payload, citations,
                                   [{"name": "inspect_document", "ok": True}],
                                   "Does the BOQ subtotal equal the contract sum?")
    assert answer.verification_status == "evidence_linked"
    assert answer.verification_status != "deterministically_verified"
    assert "SAR 600,000" not in answer.text
    assert answer.structured["boq_subtotal"] == "900000"


def _gemini_tool(name, args):
    return SimpleNamespace(function_calls=[SimpleNamespace(
        name=name, args=args, id="call_1")],
        candidates=[SimpleNamespace(content=types.Content(
            role="model", parts=[types.Part.from_text(text="Searching")]))])


def _fake_gemini(monkeypatch, responses):
    requests = []

    def generate_content(**kwargs):
        requests.append(kwargs)
        return responses.pop(0)

    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(genai, "Client", lambda **_kwargs: client)
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-only")
    return requests


def test_gemini_missing_numeric_tool_uses_labeled_application_fallback(monkeypatch):
    conn = _financial_index()
    _fake_gemini(monkeypatch, [_gemini_tool("list_documents", {})])
    answer = _ask_gemini(conn, "Does item A-02 exceed SAR 1,000,000?", 1)
    assert answer.text.startswith("No. Item A-02 is SAR 300000")
    assert answer.sources == ["Costs.xlsx | Base Costs!B3"]
    assert answer.verification_status == "deterministically_verified"
    assert any(call["name"] == "host_numeric_fallback" and
               call["origin"] == "application" for call in answer.tool_calls)
    assert not any(call["name"] == "query_spreadsheet" for call in answer.tool_calls)


def test_gemini_numeric_fallback_does_not_repeat_provider_requests(monkeypatch):
    conn = _financial_index()
    requests = _fake_gemini(monkeypatch, [
        _gemini_tool("list_documents", {}),
        SimpleNamespace(function_calls=[], text="{}"),
    ])
    answer = _ask_gemini(conn, "Does item A-02 exceed SAR 1,000,000?", 4)
    assert answer.structured["total_matches"] == 1
    assert len(requests) == 2
    assert answer.tool_calls[-1]["name"] == "host_numeric_fallback"


def test_numeric_fallback_abstains_when_multiple_tables_need_scope():
    conn = _financial_index()
    answer = _source_linked_answer(
        conn, "", [], [{"name": "list_documents", "ok": True}],
        "List signed Base Costs items above SAR 50,000; exclude approved variation.")
    assert answer.verification_status == "unverified"
    assert not answer.sources
    assert "no total is reported" in answer.text
    assert answer.tool_calls[-1]["name"] == "host_numeric_fallback"
    assert answer.tool_calls[-1]["ok"] is False


def test_numeric_fallback_still_checks_single_table():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Costs.xlsx','xlsx','ready')")
    _row(conn, 1, "Base", 1, ["Item Code", "Amount (SAR)"])
    _row(conn, 1, "Base", 2, ["A-01", 1_250_000])
    answer = _source_linked_answer(
        conn, "", [], [{"name": "list_documents", "ok": True}],
        "List all BOQ cost items above SAR 1 million.")
    assert answer.verification_status == "deterministically_verified"
    assert answer.sources == ["Costs.xlsx | Base!B2"]


def test_gemini_empty_tool_budget_answer_gets_one_compact_json_recovery(monkeypatch):
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Timeline.xlsx','xlsx','ready')")
    _row(conn, 1, "Gates", 1, ["ID", "Date", "Classification"])
    _row(conn, 1, "Gates", 2, ["G-01", "2028-02-14", "Contractual"])
    _row(conn, 1, "Gates", 3, ["G-02", "2028-03-21", "Proposal"])
    cite = "Timeline.xlsx | Gates | row 2"
    final = json.dumps({"answer": "G-01 is contractual.", "insufficient": False,
                        "claims": [{"text": "G-01 is contractual.",
                                    "supports": [{"citation": cite}]}]})
    requests = _fake_gemini(monkeypatch, [
        _gemini_tool("inspect_document", {"file": "Timeline.xlsx"}),
        SimpleNamespace(function_calls=[], text=""),
        SimpleNamespace(function_calls=[], text=final),
    ])
    answer = _ask_gemini(conn, "Which gates are contractual or proposed?", 1)
    assert answer.verification_status == "evidence_linked"
    assert answer.sources == [cite]
    assert [call["name"] for call in answer.tool_calls if call["name"].startswith("gemini_")] == [
        "gemini_tool_budget_final", "gemini_format_recovery"]
    assert len(requests) == 3
    assert len(requests[1]["contents"]) == len(requests[2]["contents"]) == 1
    assert requests[2]["config"].response_mime_type == "application/json"
    assert "G-01" in requests[2]["contents"][0].parts[0].text


def test_gemini_recovery_does_not_invent_an_answer(monkeypatch):
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(id,path,kind,status) "
                 "VALUES(1,'Memo.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,1,0,'A proposed date appears here.')")
    requests = _fake_gemini(monkeypatch, [
        _gemini_tool("search_documents", {"query": "proposed date"}),
        SimpleNamespace(function_calls=[], text=""),
        SimpleNamespace(function_calls=[], text=""),
    ])
    answer = _ask_gemini(conn, "What is the proposed date?", 1)
    assert answer.verification_status == "unverified"
    assert answer.sources == []
    assert len(requests) == 3
