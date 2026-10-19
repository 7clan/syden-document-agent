"""Regress contract and inspection questions against wrapped PDF text."""
from __future__ import annotations

from syden_agent.agent import _final_answer, _source_clauses, _supported_prose, ask
from syden_agent.db import connect
from syden_agent.tools import search_documents


def _evidence(pages):
    conn = connect(":memory:")
    conn.execute(
        "INSERT INTO documents(path,kind,status) VALUES('01_Main_Contract.pdf','pdf','ready')"
    )
    citations = []
    for page, value in enumerate(pages, start=1):
        conn.execute(
            "INSERT INTO passages(document_id,page,chunk,text) VALUES(1,?,?,?)",
            (page, 0, value),
        )
        citations.append(f"01_Main_Contract.pdf | page {page} | chunk 0")
    conn.commit()
    return conn, citations


def test_pdf_visual_line_wrap_is_one_verifiable_source_clause():
    text = (
        "2. Contract scope of work\n"
        "(cid:127) Supply and install three (3) 500 kVA distribution transformers in Building A.\n"
        "(cid:127) Commission switchgear panels SG-01 and SG-02.\n"
        "3. Explicit exclusions\n"
        "(cid:127) Civil excavation and trench backfilling are excluded from the contractor scope.\n"
        "Phase 2 battery storage is an optional proposal. There is no authorization to purchase\n"
        "or install the battery system without a separately signed change order."
    )
    clauses = _source_clauses(text)
    assert any("supply and install three" in part.lower() for part in clauses)
    assert any("Civil excavation" in part and "excluded" in part for part in clauses)
    assert any("There is no authorization to purchase or install" in part
               and "separately signed change order" in part for part in clauses)


def test_contract_value_fallback_displays_value_not_pdf_title():
    p1 = ("MAIN CONTRACT | NORTH HARBOR\nUPGRADE\n"
          "This document is entirely fictional and created for testing.\n"
          "1. Contract scope\n(cid:127) Install three transformers.")
    p2 = ("MAIN CONTRACT | NH-26-041 (CONTINUED)\n"
          "5. Completion and acceptance\n"
          "The contractual deadline is 31 March 2027.\n"
          "6. Contract sum\n"
          "The original signed contract value is SAR 6,750,000. "
          "This amount includes elements not separately itemized\n"
          "in the selected-items BOQ.\n"
          "7. Variations\n"
          "Approved change orders may revise the value.")
    conn, citations = _evidence([p1, p2])
    try:
        wrong = _final_answer(
            conn, "Original contract value SAR 7,000,000.", citations,
            [{"name": "get_evidence", "ok": True}],
            "What is the original contract value?",
        )
        assert "Verified source excerpts" in wrong.text
        assert "SAR 6,750,000" in wrong.text
        assert "entirely fictional" not in wrong.text
        assert wrong.tool_calls[-1]["ok"] is False

        correct = _final_answer(
            conn, "The original signed contract value is SAR 6,750,000.",
            [citations[1]], [{"name": "get_evidence", "ok": True}],
            "What is the original contract value?",
        )
        assert correct.text == "The original signed contract value is SAR 6,750,000."
    finally:
        conn.close()


def test_exclusion_fallback_prioritizes_actual_exclusion_clauses():
    p1 = (
        "MAIN CONTRACT | NORTH HARBOR LOGISTICS SUBSTATION\n"
        "UPGRADE\n"
        "Fictional project ID NH-26-041.\n"
        "2. Contract scope of work\n"
        "(cid:127) Supply and install three transformers.\n"
        "3. Explicit exclusions\n"
        "(cid:127) Civil excavation and trench backfilling are excluded from contractor scope.\n"
        "(cid:127) Procurement of a diesel generator is excluded.\n"
        "(cid:127) Roof waterproofing is excluded."
    )
    conn, citations = _evidence([p1])
    try:
        result = _final_answer(
            conn, "The contractor shall construct a new airport.",
            citations, [{"name": "get_evidence", "ok": True}],
            "Which activities are explicitly excluded from the contract?",
        )
        assert "Civil excavation and trench backfilling" in result.text
        assert "Procurement of a diesel generator" in result.text
        assert "Roof waterproofing" in result.text
        assert "Fictional project ID" not in result.text
    finally:
        conn.close()


def test_qa_pass_counts_visible_in_relevant_fallback():
    conn = connect(":memory:")
    conn.execute(
        "INSERT INTO documents(path,kind,status) VALUES('06_QA.pdf','pdf','ready')"
    )
    conn.execute(
        "INSERT INTO passages(document_id,page,chunk,text) VALUES(1,1,0,?)",
        (("QUALITY INSPECTION RECORD | QIR-18\n"
         "Field inspection dated 18 October 2026.\n"
         "1. Inspection summary\n"
         "Six control circuits were checked during the preliminary field inspection. Four circuits\n"
         "passed and two circuits require retesting.\n"
         "2. Circuit results\nC-01 PASS Continuity confirmed\nC-02 PASS Continuity confirmed\n"
         "C-05 RETEST Insulation resistance below threshold\n"
         "C-06 RETEST Label discrepancy unresolved"),),
    )
    cite = "06_QA.pdf | page 1 | chunk 0"
    try:
        result = _final_answer(
            conn, "Nine circuits passed.",
            [cite], [{"name": "get_evidence", "ok": True}],
            "How many circuits passed inspection and how many require retesting?",
        )
        assert "Four circuits passed and two circuits require retesting" in result.text
        assert "QUALITY INSPECTION RECORD" not in result.text
    finally:
        conn.close()


def test_wrong_quantities_and_actions_remain_unverified_after_wrap_normalization():
    conn, citations = _evidence([
        ("2. Contract scope of work\n"
         "(cid:127) Supply and install three (3) 500 kVA transformers in Building A.\n"
         "(cid:127) Civil excavation and trench backfilling are excluded.")
    ])
    try:
        for wrong in (
            "Supply and install four (4) 500 kVA transformers in Building A.",
            "Civil excavation and trench backfilling are included.",
            "The contract requires building a hospital.",
        ):
            assert not _supported_prose(conn, wrong, citations), wrong
    finally:
        conn.close()



def test_contract_sum_paraphrase_and_grounded_sources_footer_pass():
    conn, citations = _evidence([
        "1. Parties and project\nThe fictional client appoints a contractor.",
        ("6. Contract sum\n"
         "The original signed contract value is SAR 6,750,000. "
         "This amount includes elements not separately itemized\n"
         "in the selected-items BOQ."),
    ])
    cite = citations[1]
    try:
        groq = (
            "**Original contract value**\n\n"
            "The main contract states that the original signed contract sum is "
            f"**SAR\u202f6,750,000**【{cite}】."
        )
        ans = _final_answer(
            conn, groq, [cite], [{"name": "get_evidence", "ok": True}],
            "What is the original contract value?", provider="groq",
        )
        assert ans.text == groq.replace(f"【{cite}】", "")
        assert ans.sources == [cite]

        gemini = (
            "The original signed contract value is **SAR 6,750,000**.\n\n"
            f"Sources:\n- \`{cite}\`"
        )
        ans = _final_answer(
            conn, gemini, [cite], [{"name": "get_evidence", "ok": True}],
            "What is the original contract value?", provider="gemini",
        )
        assert ans.text == gemini
        assert ans.sources == [cite]
        for incorrect in (
            gemini.replace("6,750,000", "6,850,000"),
            gemini.replace(cite, "NONEXISTENT.pdf | page 3 | chunk 4"),
        ):
            failed = _final_answer(
                conn, incorrect, [cite], [{"name": "get_evidence", "ok": True}],
                "What is the original contract value?", provider="gemini",
            )
            assert "Verified source excerpts" in failed.text
    finally:
        conn.close()



def test_exact_contract_value_search_prioritizes_correct_pdf_page():
    conn, citations = _evidence([
        "MAIN CONTRACT | NORTH HARBOR\nAll values are fictional for testing.",
        ("6. Contract sum\n"
         "The original signed contract value is SAR 6,750,000."),
    ])
    try:
        matches = search_documents(conn, "contract value")["results"]
        assert matches[0]["citation"] == citations[1]
    finally:
        conn.close()


def test_unresolved_those_items_followup_does_not_guess_boq_filter():
    conn, _ = _evidence(["The original contract is SAR 6,750,000."])
    try:
        result = ask(conn, "What is the total amount of those items?", provider="gemini")
        assert "Each question is independent" in result.text
        assert "strictly above SAR 1,000,000" in result.text
        assert result.sources == []
        assert result.tool_calls == []
    finally:
        conn.close()
