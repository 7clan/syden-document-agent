"""Regression cases for provider file filters and narrowly grounded references."""
from __future__ import annotations

from syden_agent.agent import _final_answer
from syden_agent.db import connect
from syden_agent.tools import TOOL_SCHEMAS, search_documents


def _docs():
    conn = connect(":memory:")
    for doc in ("01_Main_Contract.pdf", "Contract.pdf", "06_QA_Inspection_Report.pdf"):
        conn.execute(
            "INSERT INTO documents(path,kind,status) VALUES(?,'pdf','ready')", (doc,),
        )
    conn.execute(
        "INSERT INTO passages(document_id,page,chunk,text) VALUES(1,2,0,?)",
        ("The original signed contract value is SAR 6,750,000.",),
    )
    conn.execute(
        "INSERT INTO passages(document_id,page,chunk,text) VALUES(2,1,0,?)",
        ("Contract scope of work: Install two transformers.",),
    )
    conn.execute(
        "INSERT INTO passages(document_id,page,chunk,text) VALUES(3,1,0,?)",
        ("Six control circuits were checked. Four circuits passed.",),
    )
    conn.commit()
    return conn


def test_optional_exact_filename_filter_is_in_provider_schema():
    schema = next(item for item in TOOL_SCHEMAS if item["name"] == "search_documents")
    assert "file" in schema["parameters"]["properties"]
    assert "query" in schema["parameters"]["required"]


def test_exact_file_search_does_not_mix_unrelated_projects():
    conn = _docs()
    try:
        broad = search_documents(conn, "contract")["results"]
        assert len(broad) >= 2
        exact = search_documents(
            conn, "contract", file="01_Main_Contract.pdf", limit=10,
        )["results"]
        assert len(exact) == 1
        assert exact[0]["citation"] == "01_Main_Contract.pdf | page 2 | chunk 0"
        assert search_documents(conn, "contract", file="other.pdf")["results"] == []
    finally:
        conn.close()


def test_model_inspected_contract_citation_preferred_over_other_search_hits():
    conn = _docs()
    contract_cite = "01_Main_Contract.pdf | page 2 | chunk 0"
    other_cite = "Contract.pdf | page 1 | chunk 0"
    qa_cite = "06_QA_Inspection_Report.pdf | page 1 | chunk 0"
    trace = [
        {"name": "search_documents", "ok": True, "args": {"query": "contract value"}},
        {"name": "get_evidence", "ok": True, "args": {"citation": contract_cite}},
    ]
    try:
        response = "The original signed contract value is SAR 6,750,000."
        for provider in ("groq", "ollama_cloud", "gemini"):
            answer = _final_answer(
                conn, response, [contract_cite, other_cite, qa_cite],
                trace, "What is the original contract value?", provider=provider,
            )
            assert answer.text == response
            assert answer.sources == [contract_cite]
    finally:
        conn.close()


def test_model_without_get_evidence_still_chooses_matching_single_clause():
    conn = _docs()
    cites = [
        "Contract.pdf | page 1 | chunk 0",
        "06_QA_Inspection_Report.pdf | page 1 | chunk 0",
        "01_Main_Contract.pdf | page 2 | chunk 0",
    ]
    try:
        answer = _final_answer(
            conn, "The original signed contract value is SAR 6,750,000.",
            cites, [{"name": "search_documents", "ok": True}],
            "What is the original contract value?", provider="groq",
        )
        assert answer.sources == ["01_Main_Contract.pdf | page 2 | chunk 0"]
    finally:
        conn.close()
