"""Provider/model selection must not mutate the process environment."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from syden_agent import agent
from syden_agent.agent import Answer, _compatible_config
from syden_agent.db import connect


def test_compatible_provider_accepts_per_request_model_override(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-not-a-real-key")
    monkeypatch.setenv("GROQ_MODEL", "configured-model")
    key, model, base = _compatible_config("groq", model_override="selected-model")
    assert key == "synthetic-not-a-real-key"
    assert model == "selected-model"
    assert base == "https://api.groq.com/openai/v1"
    assert os.environ["GROQ_MODEL"] == "configured-model"


def test_ask_routes_provider_and_model_without_mutating_env(monkeypatch):
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Demo.pdf','pdf','ready')")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    calls = []

    def mock_openai(connection, question, rounds, provider="openai", model_override=None):
        calls.append((question, provider, model_override))
        return Answer("Grounded synthetic result", [], [])

    monkeypatch.setattr(agent, "_ask_openai", mock_openai)
    answer = agent.ask(conn, "Read this document", provider="groq", model="gpt-oss-test")
    assert answer.text == "Grounded synthetic result"
    assert calls == [("Read this document", "groq", "gpt-oss-test")]
    assert os.environ["LLM_PROVIDER"] == "gemini"
    with pytest.raises(ValueError, match="Model ID cannot be empty"):
        agent.ask(conn, "Read this document", provider="groq", model="  ")
    conn.close()


def test_gemini_model_override_without_key_leak(monkeypatch):
    conn = connect(":memory:")
    conn.execute("INSERT INTO documents(path,kind,status) VALUES('Demo.pdf','pdf','ready')")
    calls = []

    def mock_gemini(connection, question, rounds, model_override=None):
        calls.append(model_override)
        return Answer("Synthetic Gemini result", [], [])

    monkeypatch.setattr(agent, "_ask_gemini", mock_gemini)
    result = agent.ask(conn, "Read this document", provider="gemini", model="gemini-alt")
    assert result.text == "Synthetic Gemini result"
    assert calls == ["gemini-alt"]
    conn.close()


def test_streamlit_selector_switches_provider_and_model(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    db_file = tmp_path / "selector.db"
    connection = connect(db_file)
    connection.execute("INSERT INTO documents(path,kind,status) VALUES('Demo.pdf','pdf','ready')")
    connection.commit()
    connection.close()

    monkeypatch.setenv("SYDEN_DB_PATH", str(db_file))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-not-a-real-key")
    monkeypatch.setenv("GROQ_MODEL", "my-configured-groq-model")
    calls = []

    def mock_answer(connection, question, max_rounds=8, *, provider=None, model=None):
        calls.append((question, provider, model))
        return Answer("Synthetic result", ["Demo.pdf | document"], [])

    monkeypatch.setattr(agent, "ask", mock_answer)
    app = Path(__file__).resolve().parents[1] / "app.py"
    page = AppTest.from_file(app, default_timeout=10).run()
    assert not page.exception

    page.sidebar.selectbox[0].set_value("groq").run()
    assert not page.exception
    assert page.sidebar.selectbox[1].value == "my-configured-groq-model"
    page.text_area[0].set_value("Summarize this document").run()
    ask_button = next(button for button in page.button if button.label == "Ask agent")
    assert not ask_button.disabled, "Groq Ask button should be enabled with a configured key"
    ask_button.click().run()
    assert not page.exception
    assert calls == [("Summarize this document", "groq", "my-configured-groq-model")]

    page.sidebar.selectbox[1].set_value("openai/gpt-oss-20b").run()
    assert not page.exception
    # Switching models clears the previously generated answer instead of relabeling it.
    assert "last_answer" not in page.session_state
    next(button for button in page.button if button.label == "Ask agent").click().run()
    assert calls[-1] == ("Summarize this document", "groq", "openai/gpt-oss-20b")
