"""Tests the deterministic agent contract without making provider API requests."""

import sys
from types import SimpleNamespace

from syden_agent.agent import (
    NON_GEMMA_EVIDENCE_CHECK,
    OLLAMA_GPT_OSS_20B_TOOLS,
    SYSTEM,
    _ask_gemini,
    _ask_openai,
    _collect_citations,
    _compact_recovery_messages,
    _compatible_config,
    _execute,
    _final_answer,
    _needs_numeric_query,
    _system_prompt,
)
from syden_agent.db import connect
from syden_agent.tools import TOOL_SCHEMAS, TOOLS, _num


def test_document_tools_are_allowlisted():
    conn = connect(":memory:")
    assert "error" in _execute(conn, "run_shell", {"command": "dir"})
    assert "documents" in _execute(conn, "list_documents", {})
    assert "error" in _execute(conn, "query_spreadsheet", {"operator": "DROP TABLE"})


def test_extra_evidence_instruction_excludes_gemma_and_survives_compact_recovery():
    assert _system_prompt("gemma4:31b") == SYSTEM
    assert _system_prompt("gemma4:31b-cloud") == SYSTEM
    for model in ("gemini-2.5-flash", "openai/gpt-oss-20b", "gpt-oss:120b", "gpt-4.1-mini"):
        prompt = _system_prompt(model)
        assert prompt == SYSTEM + NON_GEMMA_EVIDENCE_CHECK
        assert "each claim's own cited passage" in prompt
    conn = connect(":memory:")
    recovered = _compact_recovery_messages(
        conn, "What does this document say?", [], _system_prompt("openai/gpt-oss-20b"))
    assert recovered[0]["content"] == SYSTEM + NON_GEMMA_EVIDENCE_CHECK


def test_ollama_gpt_oss_20b_tool_reminder_is_scoped_and_compact():
    base = SYSTEM + NON_GEMMA_EVIDENCE_CHECK
    for model in ("gpt-oss:20b", "gpt-oss:20b-cloud"):
        assert _system_prompt(model, "ollama_cloud") == base + OLLAMA_GPT_OSS_20B_TOOLS
    assert _system_prompt("gpt-oss:120b", "ollama_cloud") == base
    assert _system_prompt("openai/gpt-oss-20b", "groq") == base
    assert _system_prompt("gemma4:31b", "ollama_cloud") == SYSTEM
    assert all(name in OLLAMA_GPT_OSS_20B_TOOLS for name in TOOLS)
    assert len(OLLAMA_GPT_OSS_20B_TOOLS.split()) < 100


def test_currency_numbers():
    assert str(_num("SAR 1,250,000.50")) == "1250000.50"
    assert str(_num("(5,000)")) == "-5000"
    assert _num("N/A") is None


def test_collect_citations_from_real_tool_results():
    data = {"matches": [{"citation": "contract.pdf | page 1 | chunk 0"}]}
    assert _collect_citations(data) == ["contract.pdf | page 1 | chunk 0"]


def test_hosted_llama_provider_configuration(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-not-real")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    key, model, url = _compatible_config("groq")
    assert key == "test-only-not-real"
    assert model == "openai/gpt-oss-20b"
    assert url == "https://api.groq.com/openai/v1"


def test_other_llama_host_requires_configuration(monkeypatch):
    import pytest

    monkeypatch.setenv("COMPATIBLE_API_KEY", "test-only-not-real")
    monkeypatch.setenv("COMPATIBLE_MODEL", "some-provider-model")
    monkeypatch.delenv("COMPATIBLE_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="COMPATIBLE_BASE_URL"):
        _compatible_config("compatible")


def test_ollama_cloud_has_separate_credentials_and_requires_model(monkeypatch):
    import pytest

    monkeypatch.setenv("OLLAMA_API_KEY", "test-only-not-real")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    with pytest.raises(ValueError, match="OLLAMA_MODEL"):
        _compatible_config("ollama_cloud")
    monkeypatch.setenv("OLLAMA_MODEL", "candidate-model")
    key, model, url = _compatible_config("ollama_cloud")
    assert (key, model, url) == ("test-only-not-real", "candidate-model", "https://ollama.com/v1")


def test_agent_rejects_provider_text_without_verified_evidence():
    conn = connect(":memory:")
    no_call = _final_answer(conn, "Invented answer", [], [])
    assert "Invented answer" not in no_call.text
    invalid_cite = _final_answer(conn, "Invented answer", ["fake.pdf | page 1 | chunk 0"],
                                 [{"name": "search_documents"}])
    assert "Invented answer" not in invalid_cite.text
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('real.pdf','pdf','ready')")
    cite = "real.pdf | document"
    valid = _final_answer(conn, "Indexed real.pdf", [cite], [{"name": "list_documents"}])
    assert valid.sources == [cite]


def test_compatible_provider_tool_loop_uses_real_dispatch_with_mocked_api(monkeypatch):
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('smoke.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,1,0,'Synthetic code ORCHID-7429')")
    messages_seen = []
    requests_seen = []
    tool_message = SimpleNamespace(
        tool_calls=[SimpleNamespace(id="call_1", function=SimpleNamespace(
            name="search_documents", arguments='{"query":"ORCHID-7429"}'))],
        content=None,
        model_dump=lambda exclude_none: {"role": "assistant", "tool_calls": []},
    )
    final_message = SimpleNamespace(tool_calls=None, content=(
        '{"answer":"The code is ORCHID-7429.","insufficient":false,'
        '"claims":[{"text":"Synthetic code ORCHID-7429",'
        '"supports":[{"citation":"smoke.pdf | page 1 | chunk 0",'
        '"quote":"Synthetic code ORCHID-7429"}]}]}'
    ))
    responses = [SimpleNamespace(choices=[SimpleNamespace(message=tool_message)]),
                 SimpleNamespace(choices=[SimpleNamespace(message=final_message)])]

    def create(**kwargs):
        requests_seen.append(kwargs)
        messages_seen.append(kwargs["messages"][:])
        return responses.pop(0)

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **kwargs: fake_client))
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-real")
    answer = _ask_openai(conn, "What is the synthetic code?", 3)
    assert "Synthetic code ORCHID-7429" in answer.text
    assert answer.sources == ["smoke.pdf | page 1 | chunk 0"]
    assert answer.verification_status == "evidence_linked"
    assert answer.tool_calls[0]["name"] == "search_documents"
    assert messages_seen[1][-2]["role"] == "tool"
    assert messages_seen[1][-1]["role"] == "user"
    assert "Synthetic code ORCHID-7429" in messages_seen[1][-1]["content"]
    assert len(messages_seen) == 2  # No verification-only request.
    assert requests_seen[0]["response_format"]["type"] == "json_schema"
    assert requests_seen[0]["messages"][0]["content"] == _system_prompt("gpt-4.1-mini")


def test_gemini_sdk_accepts_local_tool_declarations():
    from google.genai import types

    declarations = [types.FunctionDeclaration(name=tool["name"],
                    description=tool["description"],
                    parameters_json_schema=tool["parameters"]) for tool in TOOL_SCHEMAS]
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    assert len(config.tools[0].function_declarations) == len(TOOL_SCHEMAS)


def test_gemini_tool_loop_returns_structured_claim_without_verification_call(monkeypatch):
    from google import genai
    from google.genai import types

    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('smoke.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,1,0,'Synthetic code ORCHID-7429')")
    cite = "smoke.pdf | page 1 | chunk 0"
    first = SimpleNamespace(
        function_calls=[SimpleNamespace(name="search_documents",
                                        args={"query": "ORCHID-7429"}, id="call_1")],
        candidates=[SimpleNamespace(content=types.Content(
            role="model", parts=[types.Part.from_text(text="Searching")]))],
    )
    final = SimpleNamespace(function_calls=[], text=(
        '{"answer":"Synthetic code ORCHID-7429","insufficient":false,'
        '"claims":[{"text":"Synthetic code ORCHID-7429",'
        '"supports":[{"citation":"smoke.pdf | page 1 | chunk 0",'
        '"quote":"Synthetic code ORCHID-7429"}]}]}'
    ))
    responses = [first, final]
    requests = []

    def generate_content(**kwargs):
        requests.append(kwargs)
        return responses.pop(0)

    fake = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    monkeypatch.setattr(genai, "Client", lambda **_kwargs: fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-not-real")
    def legacy_verifier(*_args):
        raise AssertionError("legacy verifier called")

    monkeypatch.setattr("syden_agent.agent.validate_claims", legacy_verifier)
    answer = _ask_gemini(conn, "What is the synthetic code?", 3)
    assert answer.sources == [cite]
    assert answer.verification_status == "evidence_linked"
    assert len(requests) == 2
    assert answer.tool_calls[-1]["name"] == "source_linking"
    assert requests[0]["config"].system_instruction == _system_prompt("gemini-2.5-flash")


def test_gemini_tool_budget_still_generates_answer(monkeypatch):
    from google import genai
    from google.genai import types

    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Memo.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,1,0,'The fictional milestone is ARBOR-17.')")
    citation = "Memo.pdf | page 1 | chunk 0"
    tool = SimpleNamespace(function_calls=[SimpleNamespace(
        name="search_documents", args={"query": "ARBOR-17"}, id="one")],
        candidates=[SimpleNamespace(content=types.Content(
            role="model", parts=[types.Part.from_text(text="Searching")]))])
    final = SimpleNamespace(function_calls=[], text=(
        '{"answer":"The milestone is ARBOR-17","insufficient":false,'
        '"claims":[{"text":"The milestone is ARBOR-17",'
        '"supports":[{"citation":"Memo.pdf | page 1 | chunk 0"}]}]}'))
    requests = []

    def generate_content(**kwargs):
        requests.append(kwargs)
        return [tool, final][len(requests) - 1]

    monkeypatch.setattr(genai, "Client", lambda **_: SimpleNamespace(models=SimpleNamespace(
        generate_content=generate_content)))
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-only")
    answer = _ask_gemini(conn, "What is the milestone?", 1)
    assert answer.sources == [citation]
    assert answer.verification_status == "evidence_linked"
    assert len(requests) == 2
    assert requests[0]["config"].tools
    assert not requests[1]["config"].tools


def test_ollama_tool_budget_still_generates_answer(monkeypatch):
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Memo.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,1,0,'The fictional milestone is ARBOR-17.')")
    tool = SimpleNamespace(tool_calls=[SimpleNamespace(id="one", function=SimpleNamespace(
        name="search_documents", arguments='{"query":"ARBOR-17"}'))],
        content=None, model_dump=lambda exclude_none: {"role": "assistant", "tool_calls": []})
    final = SimpleNamespace(tool_calls=None, content=(
        '{"answer":"The milestone is ARBOR-17","insufficient":false,'
        '"claims":[{"text":"The milestone is ARBOR-17",'
        '"supports":[{"citation":"Memo.pdf | page 1 | chunk 0"}]}]}'))
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=[tool, final][
            len(requests) - 1])])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_: client))
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-only")
    monkeypatch.setenv("OLLAMA_MODEL", "mock-model")
    answer = _ask_openai(conn, "What is the milestone?", 1, provider="ollama_cloud")
    assert answer.verification_status == "evidence_linked"
    assert len(requests) == 2
    assert requests[-1]["tool_choice"] == "none"
    assert "tools" not in requests[-1]


def test_empty_final_answer_does_not_present_retrieval_hits_as_sources(monkeypatch):
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Memo.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,1,0,'A source passage without an answer.')")
    tool = SimpleNamespace(tool_calls=[SimpleNamespace(id="one", function=SimpleNamespace(
        name="search_documents", arguments='{"query":"source passage"}'))],
        content=None, model_dump=lambda exclude_none: {"role": "assistant", "tool_calls": []})
    final = SimpleNamespace(tool_calls=None, content="")
    responses = [tool, final]

    def create(**_kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=responses.pop(0))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_: client))
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-only")
    monkeypatch.setenv("OLLAMA_MODEL", "mock-model")
    answer = _ask_openai(conn, "What does it say?", 1, provider="ollama_cloud")
    assert answer.verification_status == "unverified"
    assert answer.sources == []
    assert "returned no answer" in answer.text


def test_openai_unsupported_native_schema_retries_with_instructed_json(monkeypatch):
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('note.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                 "VALUES(1,1,0,'The test result was accepted.')")
    tool_message = SimpleNamespace(
        tool_calls=[SimpleNamespace(id="one", function=SimpleNamespace(
            name="search_documents", arguments='{"query":"test result"}'))],
        content=None, model_dump=lambda exclude_none: {"role": "assistant", "tool_calls": []},
    )
    final_message = SimpleNamespace(tool_calls=None, content=(
        '{"answer":"Accepted","insufficient":false,"claims":[{'
        '"text":"The test result was accepted.","supports":[{'
        '"citation":"note.pdf | page 1 | chunk 0",'
        '"quote":"The test result was accepted."}]}]}'
    ))
    responses = [tool_message, final_message]
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        if "response_format" in kwargs:
            raise ValueError("response_format json_schema is not supported")
        return SimpleNamespace(choices=[SimpleNamespace(message=responses.pop(0))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_kw: fake))
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-real")
    answer = _ask_openai(conn, "Was the test result accepted?", 3)
    assert answer.verification_status == "evidence_linked"
    assert len(requests) == 3
    assert "response_format" not in requests[1]
    assert any(item["name"] == "structured_output_fallback" for item in answer.tool_calls)


def test_boq_threshold_questions_require_numeric_tool():
    assert _needs_numeric_query("List all BOQ cost items above SAR 1 million")
    assert not _needs_numeric_query("Summarize the scope of work in the contract")
