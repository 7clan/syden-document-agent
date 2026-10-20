"""Search excerpts and final answers receive authentic, bounded indexed evidence."""
import json
import sys
from types import SimpleNamespace

from syden_agent.agent import (
    NON_GEMMA_EVIDENCE_CHECK,
    SYSTEM,
    _ask_openai,
    _source_linked_answer,
    provider_error_diagnostic,
    safe_provider_error,
)
from syden_agent.db import connect

CITE = "02_Approved_Change_Order_CO07.pdf | page 1 | chunk 0"
AMOUNT = "SAR 7,070,000"
QUESTION = "What is the revised contract sum in 02_Approved_Change_Order_CO07.pdf?"
CORRECT = json.dumps({"answer": f"The revised sum is {AMOUNT}.",
                      "insufficient": False, "claims": [{
                          "text": f"The revised contract sum is {AMOUNT}.",
                          "supports": [{"citation": CITE}]}]})
FALSE_ABSENCE = json.dumps({"answer": "No revised contract sum was found.",
                            "insufficient": True, "claims": []})


def _documents():
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) "
                 "VALUES('01_Main_Contract.pdf','pdf','ready')")
    conn.execute("INSERT INTO documents(path,kind,status) "
                 "VALUES('02_Approved_Change_Order_CO07.pdf','pdf','ready')")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES(1,1,0,?)",
                 ("The original contract sum is SAR 6,750,000.",))
    text = ("Approved change order CO-07. " +
            "Administrative routing and signatures. " * 45 +
            f"The revised contract sum is {AMOUNT}.")
    conn.execute("INSERT INTO passages(document_id,page,chunk,text) VALUES(2,1,0,?)",
                 (text,))
    return conn


def _tool(name, args):
    return SimpleNamespace(tool_calls=[SimpleNamespace(
        id=f"call_{name}", function=SimpleNamespace(name=name,
                                                    arguments=json.dumps(args)))],
        content=None, model_dump=lambda exclude_none: {"role": "assistant", "tool_calls": []})


def _final(text):
    return SimpleNamespace(tool_calls=None, content=text)


def _client(monkeypatch, responses):
    requests = []

    def create(**kwargs):
        requests.append({**kwargs, "messages": [message.copy()
                                                 for message in kwargs["messages"]]})
        return SimpleNamespace(choices=[SimpleNamespace(message=responses.pop(0))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_: client))
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-only")
    return requests


def test_identical_documents_reach_gemma_and_gpt_oss_without_get_evidence(monkeypatch):
    searches = [
        _tool("search_documents", {"query": "change order", "file":
                                    "02_Approved_Change_Order_CO07.pdf"}),
        _tool("search_documents", {"query": "revised contract sum", "file":
                                    "02_Approved_Change_Order_CO07.pdf"}),
    ]
    gpt_requests = _client(monkeypatch, [*searches, _final(FALSE_ABSENCE),
                                         _final(CORRECT)])
    gpt_answer = _ask_openai(_documents(), QUESTION, 5, provider="ollama_cloud",
                             model_override="gpt-oss:120b")
    assert gpt_answer.verification_status == "evidence_linked"
    assert gpt_answer.sources == [CITE]
    assert [call["name"] for call in gpt_answer.tool_calls if call["name"] in
            {"search_documents", "get_evidence"}] == ["search_documents"] * 2
    assert any(call["name"] == "evidence_retry" for call in gpt_answer.tool_calls)
    first_handoff = gpt_requests[1]["messages"][-1]["content"]
    assert CITE in first_handoff and AMOUNT in first_handoff
    second_tool_result = next(message for message in gpt_requests[2]["messages"]
                              if message.get("role") == "tool" and AMOUNT in message["content"])
    assert CITE in second_tool_result["content"]
    assert AMOUNT in str(gpt_requests[-1]["messages"])
    assert gpt_requests[0]["messages"][0]["content"] == SYSTEM + NON_GEMMA_EVIDENCE_CHECK
    assert gpt_requests[-1]["messages"][0]["content"] == SYSTEM + NON_GEMMA_EVIDENCE_CHECK

    gemma_requests = _client(monkeypatch, [searches[0],
                                          _tool("get_evidence", {"citation": CITE}),
                                          _final(CORRECT)])
    gemma_answer = _ask_openai(_documents(), QUESTION, 5, provider="ollama_cloud",
                               model_override="gemma4:31b")
    assert gemma_answer.sources == [CITE]
    assert [call["name"] for call in gemma_answer.tool_calls if call["name"] in
            {"search_documents", "get_evidence"}] == ["search_documents", "get_evidence"]
    assert AMOUNT in gemma_requests[1]["messages"][-1]["content"]
    assert AMOUNT in str(gemma_requests[-1]["messages"])
    assert gemma_requests[0]["messages"][0]["content"] == SYSTEM
    assert gemma_requests[-1]["messages"][0]["content"] == SYSTEM


def test_persistent_false_absence_is_unverified_with_inspectable_candidates(monkeypatch):
    _client(monkeypatch, [_tool("search_documents", {"query": "revised sum", "file":
                                                 "02_Approved_Change_Order_CO07.pdf"}),
                          _final(FALSE_ABSENCE), _final(FALSE_ABSENCE)])
    answer = _ask_openai(_documents(), QUESTION, 4, provider="ollama_cloud",
                         model_override="gpt-oss:120b")
    assert answer.verification_status == "unverified"
    assert answer.sources == []
    assert answer.structured["candidate_sources"] == [CITE]
    assert "absence conclusion was not established" in answer.text


def test_false_absence_claim_with_real_citation_is_never_fact_verified():
    claim = json.dumps({"answer": "There is no revised contract sum.",
                        "insufficient": False, "claims": [{
                            "text": "The change order contains no revised contract sum.",
                            "supports": [{"citation": CITE}]}]})
    answer = _source_linked_answer(_documents(), claim, [CITE],
                                   [{"name": "search_documents", "ok": True}], QUESTION)
    assert answer.verification_status == "evidence_linked"
    assert answer.verification_status != "deterministically_verified"
    assert answer.claims[0]["reason"] == (
        "Retrieved source; model interpretation was not checked")
    assert AMOUNT in answer.claims[0]["quotes"][0]["quote"]


def test_safe_provider_diagnostic_has_status_code_and_phase_without_body(monkeypatch):
    class ProviderError(Exception):
        def __init__(self):
            self.status_code = 400
            self.body = {"error": {"code": "tool_use_failed", "failed_generation":
                                   "PRIVATE MODEL REASONING"}}

        def __str__(self):
            return "PRIVATE MODEL REASONING"

    def fail(**_kwargs):
        raise ProviderError()

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fail)))
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=lambda **_: client))
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-only")
    try:
        _ask_openai(_documents(), QUESTION, 2, provider="groq",
                    model_override="openai/gpt-oss-120b")
    except ProviderError as exc:
        assert provider_error_diagnostic(exc) == {
            "http_status": 400, "code": "tool_use_failed", "phase": "tool"}
        message = safe_provider_error(exc, "groq")
        assert "HTTP 400, code: tool_use_failed" in message
        assert "PRIVATE" not in message
    else:
        raise AssertionError("Expected the safe provider error")

    calls = []

    def fail_after_search(**_kwargs):
        calls.append(1)
        if len(calls) == 1:
            return SimpleNamespace(choices=[SimpleNamespace(message=_tool(
                "search_documents", {"query": "revised sum", "file":
                                     "02_Approved_Change_Order_CO07.pdf"}))])
        raise ProviderError()

    client.chat.completions.create = fail_after_search
    try:
        _ask_openai(_documents(), QUESTION, 1, provider="groq",
                    model_override="openai/gpt-oss-120b")
    except ProviderError as exc:
        assert provider_error_diagnostic(exc)["phase"] == "final"
    else:
        raise AssertionError("Expected the safe provider error")
