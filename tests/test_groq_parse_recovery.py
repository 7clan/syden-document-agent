"""Groq parse failures get one safe retry without authenticating failed output."""
import sys
from types import SimpleNamespace

import pytest

from syden_agent.agent import (
    ProviderOutputParseError,
    _ask_openai,
    safe_provider_error,
)
from syden_agent.db import connect

CITE = "Memo.pdf | page 1 | chunk 0"
FINAL = ('{"answer":"Code ARBOR-17","insufficient":false,"claims":['
         '{"text":"The code is ARBOR-17","supports":[{"citation":"'
         + CITE + '"}]}]}')


def _index():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Memo.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,1,0,'The code is ARBOR-17.')")
    return conn


def _tool(arguments='{"query":"ARBOR-17"}'):
    return SimpleNamespace(tool_calls=[SimpleNamespace(
        id="call_1", function=SimpleNamespace(name="search_documents",
                                               arguments=arguments))],
        content=None, model_dump=lambda exclude_none: {"role": "assistant", "tool_calls": []})


def _final(content=FINAL):
    return SimpleNamespace(tool_calls=None, content=content)


class FakeAPIError(Exception):
    def __init__(self, status, code):
        super().__init__("raw secret failed_generation planning text")
        self.status_code = status
        self.body = {"code": code, "failed_generation": "raw secret planning text"}


def _client(monkeypatch, responses):
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(choices=[SimpleNamespace(message=item)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_: client))
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-only")
    return requests


def test_tool_phase_parse_failure_retries_once_with_real_tool_call(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [FakeAPIError(400, "output_parse_failed"),
                                   _tool(), _final()])
    answer = _ask_openai(conn, "What is the code?", 3, provider="groq",
                         model_override="openai/gpt-oss-20b")
    assert answer.sources == [CITE]
    assert answer.verification_status == "evidence_linked"
    assert len(requests) == 3
    assert requests[1]["tools"]
    assert len(requests[1]["messages"]) == 4
    assert not any("failed_generation" in str(message)
                   for message in requests[1]["messages"])
    assert any(call["name"] == "provider_parse_recovery" and call["mode"] == "tool"
               for call in answer.tool_calls)


def test_tool_capable_continuation_failure_recovers_as_strict_final(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [_tool(), FakeAPIError(400, "output_parse_failed"),
                                   _final()])
    answer = _ask_openai(conn, "What is the code?", 3, provider="groq",
                         model_override="openai/gpt-oss-20b")
    assert answer.sources == [CITE]
    assert requests[1]["tools"]
    assert "tools" not in requests[2]
    assert requests[2]["tool_choice"] == "none"
    assert requests[2]["response_format"]["json_schema"]["strict"] is True
    assert len(requests[2]["messages"]) == 4
    assert any(call["name"] == "provider_parse_recovery" and call["mode"] == "final"
               for call in answer.tool_calls)


def test_tool_free_final_parse_failure_gets_one_compact_retry(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [_tool(), FakeAPIError(400, "output_parse_failed"),
                                   _final()])
    answer = _ask_openai(conn, "What is the code?", 1, provider="groq",
                         model_override="openai/gpt-oss-20b")
    assert answer.sources == [CITE]
    assert len(requests) == 3
    assert all("tools" not in request for request in requests[1:])
    assert all(request["response_format"]["json_schema"]["strict"]
               for request in requests[1:])
    assert len(requests[2]["messages"]) <= 4


def test_malformed_final_response_gets_compact_strict_json_retry(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [_tool(), _final("not JSON planning text"), _final()])
    answer = _ask_openai(conn, "What is the code?", 4, provider="groq",
                         model_override="openai/gpt-oss-20b")
    assert answer.sources == [CITE]
    assert "tools" not in requests[2]
    assert requests[2]["response_format"]["type"] == "json_schema"
    assert "not JSON planning text" not in str(requests[2]["messages"])
    assert len(requests[2]["messages"]) <= 4


def test_unrecoverable_parse_error_is_sanitized_and_retry_is_bounded(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [FakeAPIError(400, "output_parse_failed"),
                                   FakeAPIError(400, "output_parse_failed")])
    with pytest.raises(ProviderOutputParseError) as captured:
        _ask_openai(conn, "What is the code?", 6, provider="groq",
                    model_override="openai/gpt-oss-20b")
    assert len(requests) == 2
    assert "raw secret" not in str(captured.value)
    assert "raw secret" not in safe_provider_error(captured.value, "groq")


def test_other_http_400_and_429_are_not_output_parse_retries(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [FakeAPIError(400, "model_not_found")])
    with pytest.raises(FakeAPIError) as captured:
        _ask_openai(conn, "What is the code?", 6, provider="groq",
                    model_override="openai/gpt-oss-20b")
    assert len(requests) == 1
    assert safe_provider_error(captured.value, "groq") == (
        "Groq rejected the request (HTTP 400). Check the model ID and tool support.")
    assert "rate limit" in safe_provider_error(FakeAPIError(429, "rate_limit"),
                                               "groq").lower()
    assert "raw secret" not in safe_provider_error(
        ValueError("raw secret failed_generation planning text"), "groq")


def test_malformed_tool_arguments_never_execute_and_never_create_evidence(monkeypatch):
    conn = _index()
    _client(monkeypatch, [_tool("{broken"), _final()])
    answer = _ask_openai(conn, "What is the code?", 3, provider="groq",
                         model_override="openai/gpt-oss-20b")
    assert answer.sources == []
    assert answer.verification_status == "unverified"
    assert answer.tool_calls[0]["ok"] is False
    assert "Malformed tool arguments JSON" in answer.tool_calls[0]["result_preview"]


def test_groq_tool_result_keeps_deterministic_boq_amounts(monkeypatch, tmp_path):
    from openpyxl import Workbook

    from syden_agent.ingest import ingest_folder

    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ"
    sheet.append(["Item", "Total Amount (SAR)"])
    sheet.append(["Transformer", 1_250_000])
    sheet.append(["Boundary item", 1_000_000])
    sheet.append(["Switchgear", 1_500_000])
    book.save(tmp_path / "DemoBOQ.xlsx")
    conn = connect(":memory:")
    ingest_folder(conn, tmp_path)
    tool = SimpleNamespace(tool_calls=[SimpleNamespace(
        id="boq_call", function=SimpleNamespace(name="query_spreadsheet",
            arguments='{"operator":"gt","value":1000000,"file":"DemoBOQ.xlsx",'
                      '"currency":"SAR"}'))],
        content=None, model_dump=lambda exclude_none: {"role": "assistant", "tool_calls": []})
    _client(monkeypatch, [tool, _final('{}')])
    answer = _ask_openai(conn, "List all BOQ cost items above SAR 1 million in "
                         "DemoBOQ.xlsx", 3, provider="groq",
                         model_override="openai/gpt-oss-20b")
    assert answer.verification_status == "deterministically_verified"
    assert "2750000" in answer.text
    assert "DemoBOQ.xlsx | BOQ!B2" in answer.sources
    assert "DemoBOQ.xlsx | BOQ!B4" in answer.sources
    assert "DemoBOQ.xlsx | BOQ!B3" not in answer.sources


def test_groq_simple_contract_question_keeps_citation(monkeypatch):
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Contract.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,2,0,'Contractor shall install switchgear panels.')")
    tool = SimpleNamespace(tool_calls=[SimpleNamespace(
        id="contract_call", function=SimpleNamespace(name="search_documents",
            arguments='{"query":"install switchgear","file":"Contract.pdf"}'))],
        content=None, model_dump=lambda exclude_none: {"role": "assistant", "tool_calls": []})
    final = _final('{"answer":"Install switchgear","insufficient":false,"claims":['
                   '{"text":"The contractor shall install switchgear panels.",'
                   '"supports":[{"citation":"Contract.pdf | page 2 | chunk 0"}]}]}')
    _client(monkeypatch, [tool, final])
    answer = _ask_openai(conn, "Summarize the scope in Contract.pdf", 3,
                         provider="groq", model_override="openai/gpt-oss-20b")
    assert answer.verification_status == "evidence_linked"
    assert answer.sources == ["Contract.pdf | page 2 | chunk 0"]
