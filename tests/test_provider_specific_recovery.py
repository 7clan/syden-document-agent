"""Provider quirks must not change Gemma or authenticate failed requests."""
import sys
from types import SimpleNamespace

import pytest

from syden_agent.agent import (
    OLLAMA_GPT_OSS_20B_TOOLS,
    ProviderRateLimitError,
    _ask_gemini,
    _ask_openai,
    provider_error_diagnostic,
)
from syden_agent.db import connect

CITE = "Memo.pdf | page 1 | chunk 0"
ANSWER = ('{"answer":"ARBOR-17","insufficient":false,"claims":'
          '[{"text":"The code is ARBOR-17","supports":'
          '[{"citation":"Memo.pdf | page 1 | chunk 0"}]}]}')


def _index():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Memo.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,1,0,'The code is ARBOR-17.')")
    return conn


def _tool(name, arguments):
    return SimpleNamespace(tool_calls=[SimpleNamespace(
        id="call_1", function=SimpleNamespace(name=name, arguments=arguments))],
        content=None, model_dump=lambda exclude_none: {"role": "assistant", "tool_calls": []})


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
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-only")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-only")
    monkeypatch.setattr("syden_agent.agent.time.sleep", lambda _: None)
    return requests


def _final():
    return SimpleNamespace(tool_calls=None, content=ANSWER)


class ServerError(Exception):
    status_code = 500


def test_server_error_diagnostic_is_specific_and_sanitized():
    error = ServerError("private response contents")
    error._syden_phase = "tool"
    assert provider_error_diagnostic(error) == {
        "http_status": 500, "code": "server_error", "phase": "tool"}


def test_ollama_gpt_oss_20b_request_receives_tool_reminder(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [
        _tool("search_documents", '{"query":"ARBOR-17"}'), _final(),
    ])
    answer = _ask_openai(conn, "What is the code?", 3, provider="ollama_cloud",
                         model_override="gpt-oss:20b")
    assert answer.sources == [CITE]
    assert OLLAMA_GPT_OSS_20B_TOOLS in requests[0]["messages"][0]["content"]
    assert OLLAMA_GPT_OSS_20B_TOOLS in requests[1]["messages"][0]["content"]


def test_ollama_gpt_server_error_retries_once_with_compact_evidence(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [
        _tool("search_documents", '{"query":"ARBOR-17"}'),
        ServerError("private provider response"), _final(),
    ])
    answer = _ask_openai(conn, "What is the code?", 3, provider="ollama_cloud",
                         model_override="gpt-oss:20b-cloud")
    assert answer.sources == [CITE]
    assert answer.verification_status == "evidence_linked"
    assert len(requests) == 3
    assert requests[2]["tool_choice"] == "none"
    assert "tools" not in requests[2]
    assert len(requests[2]["messages"]) <= 4
    assert CITE in str(requests[2]["messages"])
    assert "private provider response" not in str(requests[2])
    assert any(call["name"] == "provider_transient_recovery" and
               call["mode"] == "final" for call in answer.tool_calls)


def test_ollama_gpt_first_tool_error_keeps_function_calling(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [
        ServerError("private"), _tool("search_documents", '{"query":"ARBOR-17"}'),
        _final(),
    ])
    answer = _ask_openai(conn, "What is the code?", 3, provider="ollama_cloud",
                         model_override="gpt-oss:20b-cloud")
    assert answer.sources == [CITE]
    assert requests[1]["tools"]
    assert any(call["name"] == "provider_transient_recovery" and
               call["mode"] == "tool" for call in answer.tool_calls)


def test_gemma_keeps_existing_full_request_retry(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [
        ServerError("private"), _tool("search_documents", '{"query":"ARBOR-17"}'),
        _final(),
    ])
    answer = _ask_openai(conn, "What is the code?", 3, provider="ollama_cloud",
                         model_override="gemma4:31b")
    assert answer.sources == [CITE]
    assert requests[0] == requests[1]
    assert not any(call["name"] == "provider_transient_recovery"
                   for call in answer.tool_calls)


def test_groq_gpt_empty_no_arg_call_is_repaired_and_audited(monkeypatch):
    conn = _index()
    requests = _client(monkeypatch, [
        _tool("list_documents", '{"":""}'),
        _tool("search_documents", '{"query":"ARBOR-17"}'), _final(),
    ])
    answer = _ask_openai(conn, "What is the code?", 3, provider="groq",
                         model_override="openai/gpt-oss-20b")
    assert len(requests) == 3
    assert answer.sources == [CITE]
    assert answer.verification_status == "evidence_linked"
    assert any(call["name"] == "tool_argument_repair" and
               call["original_args"] == {"": ""} for call in answer.tool_calls)
    assert next(call for call in answer.tool_calls if call["name"] == "list_documents")[
        "ok"] is True


def test_groq_rate_limit_after_tool_keeps_python_boq_result(monkeypatch, tmp_path):
    from openpyxl import Workbook

    from syden_agent.ingest import ingest_folder

    class Groq429(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "40"})

    book = Workbook()
    sheet = book.active
    sheet.title = "Base"
    sheet.append(["Item", "Amount (SAR)"])
    sheet.append(["A", 1_250_000])
    sheet.append(["B", 1_000_000])
    book.save(tmp_path / "Costs.xlsx")
    conn = connect(":memory:")
    ingest_folder(conn, tmp_path)
    requests = _client(monkeypatch, [
        _tool("query_spreadsheet", '{"file":"Costs.xlsx","sheet":"Base",'
              '"operator":"all"}'), Groq429("private quota response"),
    ])
    answer = _ask_openai(conn, "List every Base cost item strictly above "
                         "SAR 1 million in Costs.xlsx", 3, provider="groq",
                         model_override="openai/gpt-oss-20b")
    assert len(requests) == 2
    assert answer.verification_status == "deterministically_verified"
    assert answer.sources == ["Costs.xlsx | Base!B2"]
    assert "1250000" in answer.text
    assert any(call["name"] == "provider_limit_deterministic_completion" and
               call["origin"] == "application" for call in answer.tool_calls)


def test_groq_rate_limit_never_invents_prose_answer(monkeypatch):
    class Groq429(Exception):
        status_code = 429
        response = SimpleNamespace(headers={"retry-after": "40"})

    conn = _index()
    _client(monkeypatch, [_tool("search_documents", '{"query":"ARBOR-17"}'),
                          Groq429("private quota response")])
    with pytest.raises(ProviderRateLimitError):
        _ask_openai(conn, "What is the code?", 3, provider="groq",
                    model_override="openai/gpt-oss-20b")


def test_gemini_rate_limit_is_bounded_and_phase_specific(monkeypatch):
    from google import genai

    class Gemini429(Exception):
        code = 429
        status = "RESOURCE_EXHAUSTED"
        response = SimpleNamespace(headers={"retry-after": "37"})

    options = []

    def fake_client(**kwargs):
        options.append(kwargs["http_options"])
        return SimpleNamespace(models=SimpleNamespace(generate_content=lambda **_: (
            _ for _ in ()).throw(Gemini429("private provider response"))))

    monkeypatch.setattr(genai, "Client", fake_client)
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-only")
    with pytest.raises(ProviderRateLimitError) as captured:
        _ask_gemini(_index(), "What is the code?", 3,
                    model_override="gemini-2.5-flash")
    assert options[0].retry_options.attempts == 2
    assert "37 seconds" in str(captured.value)
    assert "private provider response" not in str(captured.value)
    assert provider_error_diagnostic(captured.value) == {
        "http_status": 429, "code": "rate_limit", "phase": "tool"}


def test_slow_gemini_numeric_request_completes_from_indexed_cells(monkeypatch, tmp_path):
    from google import genai
    from google.genai import types
    from openpyxl import Workbook

    from syden_agent.ingest import ingest_folder

    book = Workbook()
    sheet = book.active
    sheet.title = "Base"
    sheet.append(["Item", "Amount (SAR)"])
    sheet.append(["A", 1_250_000])
    sheet.append(["B", 1_000_000])
    book.save(tmp_path / "Costs.xlsx")
    conn = connect(":memory:")
    ingest_folder(conn, tmp_path)
    clock = {"now": 0.0}
    monkeypatch.setattr("syden_agent.agent.time.monotonic", lambda: clock["now"])

    def generate_content(**_):
        clock["now"] = 80.0
        return SimpleNamespace(
            function_calls=[SimpleNamespace(name="query_spreadsheet", id="tool_1",
                                            args={"file": "Costs.xlsx", "sheet": "Base",
                                                  "operator": "all"})],
            candidates=[SimpleNamespace(content=types.Content(
                role="model", parts=[types.Part.from_text(text="tool call")]))])

    monkeypatch.setattr(genai, "Client", lambda **_: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)))
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-only")
    answer = _ask_gemini(conn, "List every Base cost item strictly above SAR 1 million "
                         "in Costs.xlsx", 3, model_override="gemini-3.5-flash-lite")
    assert answer.verification_status == "deterministically_verified"
    assert answer.sources == ["Costs.xlsx | Base!B2"]
    assert "1250000" in answer.text
    assert any(call["name"] == "provider_budget_deterministic_completion" and
               call["origin"] == "application" for call in answer.tool_calls)
