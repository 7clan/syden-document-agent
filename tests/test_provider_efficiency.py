"""Bounded compatible-provider retries and compact tool context."""
import json
from types import SimpleNamespace

import pytest

from syden_agent.agent import (
    ProviderRateLimitError,
    _model_tool_result,
    _rate_limited_create,
    _retry_after_seconds,
)


class TooManyRequests(Exception):
    status_code = 429

    def __init__(self, delay):
        super().__init__("Private provider response must not be displayed")
        self.response = SimpleNamespace(headers={"retry-after": str(delay)})


def test_retry_after_honored_once_with_bounded_wait(monkeypatch):
    waits = []
    monkeypatch.setattr("syden_agent.agent.time.sleep", waits.append)
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TooManyRequests(2.5)
        return "accepted"

    assert _rate_limited_create(create, {"model": "any-compatible-model"},
                                "groq", float("inf")) == "accepted"
    assert waits == [2.5]
    assert len(calls) == 2


def test_long_or_repeated_429_is_friendly_and_never_loops(monkeypatch):
    waits = []
    monkeypatch.setattr("syden_agent.agent.time.sleep", waits.append)
    for delay, expected_calls in ((11, 1), (1, 2)):
        calls = []

        def create(_calls=calls, _delay=delay, **_kwargs):
            _calls.append(1)
            raise TooManyRequests(_delay)

        with pytest.raises(ProviderRateLimitError) as error:
            _rate_limited_create(create, {}, "groq", float("inf"))
        assert f"approximately {delay} seconds" in str(error.value)
        assert "Private provider" not in str(error.value)
        assert len(calls) == expected_calls
    assert waits == [1.0]


def test_retry_after_ms_and_missing_header():
    error = TooManyRequests(1)
    error.response.headers = {"retry-after-ms": "1750"}
    assert _retry_after_seconds(error) == 1.75
    error.response.headers = {}
    assert _retry_after_seconds(error) is None


@pytest.mark.parametrize("provider,label", [
    ("groq", "Groq"), ("openai", "OpenAI"),
    ("ollama_cloud", "Ollama Cloud"), ("compatible", "Model provider"),
])
def test_compatible_provider_rate_messages_are_safe(provider, label):
    message = str(ProviderRateLimitError(provider, 10.2))
    assert message == f"{label} rate limit reached. Please retry in approximately 11 seconds."


def test_search_context_shrinks_and_duplicate_evidence_is_reused():
    passage = "The contractor will submit design drawings. " * 70
    citation = "Contract.pdf | page 1 | chunk 0"
    result = {"results": [{"citation": citation, "preview": passage, "score": 4}],
              "total_matches": 1}
    seen = set()
    compact = _model_tool_result("search_documents", result, False, seen)
    assert len(json.dumps(compact)) < len(json.dumps(result)) / 4
    assert compact["results"][0]["citation"] == citation
    assert compact["results"][0]["preview"] == passage[:360]
    assert result["results"][0]["preview"] == passage  # full local evidence remains
    again = _model_tool_result("search_documents", result, False, seen)
    assert again["results"] == []
    assert again["already_seen_results"] == 1
    reused = _model_tool_result("search_documents", result, True, seen)
    assert reused["reused"] is True
    assert "preview" not in json.dumps(reused)


def test_full_row_evidence_remains_available_for_verification():
    result = {"citation": "Schedule.xlsx | Milestones | row 2",
              "row": {"A": "M-01", "B": "Submit stamped drawings",
                      "C": "2026-11-20", "D": "Approved"}}
    assert _model_tool_result("get_evidence", result, False, set()) == result


def test_zero_boq_result_explains_nonfinancial_retrieval():
    result = _model_tool_result("query_spreadsheet", {"total_matches": 0,
                                "matches": []}, False, set())
    assert "milestones" in result["note"]


def test_compact_inspection_keeps_exact_row_citation():
    citation = "Schedule.xlsx | Milestones | row 2"
    inspected = {"sheets": [{"sheet": "Milestones", "preview": [
        {"row": 2, "citation": citation, "cells": {"A": "M-01",
         "B": "A" * 300}}]}]}
    compact = _model_tool_result("inspect_document", inspected, False, set())
    row = compact["sheets"][0]["preview"][0]
    assert row["citation"] == citation
    assert len(row["cells"]["B"]) == 180
