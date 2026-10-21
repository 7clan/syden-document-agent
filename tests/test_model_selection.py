"""Provider/model selection must not mutate the process environment."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from syden_agent import agent, model_catalog
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
    connection.execute("INSERT INTO metadata(key,value) VALUES('active_folder',?)",
                       (str(tmp_path),))
    connection.commit()
    connection.close()

    monkeypatch.setenv("SYDEN_DB_PATH", str(db_file))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-not-a-real-key")
    monkeypatch.setenv("GROQ_MODEL", "my-configured-groq-model")
    monkeypatch.setattr(model_catalog, "discover_models", lambda provider, key:
                        model_catalog.ModelCatalog((
                            model_catalog.ModelOption("openai/gpt-oss-20b", "GPT-OSS 20B", True),
                            model_catalog.ModelOption("openai/gpt-oss-120b", "GPT-OSS 120B", True))))
    calls = []

    def mock_answer(connection, question, max_rounds=8, *, provider=None, model=None):
        calls.append((question, provider, model))
        return Answer("Synthetic result", ["Demo.pdf | document"], [])

    monkeypatch.setattr(agent, "ask", mock_answer)
    app = Path(__file__).resolve().parents[1] / "app.py"
    page = AppTest.from_file(app, default_timeout=10).run()
    assert not page.exception
    next(field for field in page.sidebar.text_input
         if field.label == "Folder path on this computer").set_value(str(tmp_path)).run()

    page.sidebar.selectbox[0].set_value("groq").run()
    assert not page.exception
    assert page.sidebar.selectbox[1].value == "openai/gpt-oss-20b"
    assert any("my-configured-groq-model" in option
               for option in page.sidebar.selectbox[1].options)
    page.sidebar.selectbox[1].set_value("my-configured-groq-model").run()
    assert any("not in the current compatible model list" in warning.value
               for warning in page.sidebar.warning)
    page.sidebar.selectbox[1].set_value("openai/gpt-oss-20b").run()
    page.text_area[0].set_value("Summarize this document").run()
    ask_button = next(button for button in page.button if button.label == "Ask agent")
    assert not ask_button.disabled, "Groq Ask button should be enabled with a configured key"
    ask_button.click().run()
    assert not page.exception
    assert calls == [("Summarize this document", "groq", "openai/gpt-oss-20b")]

    page.sidebar.selectbox[1].set_value("openai/gpt-oss-120b").run()
    assert not page.exception
    # Switching models clears the previously generated answer instead of relabeling it.
    assert "last_answer" not in page.session_state
    next(button for button in page.button if button.label == "Ask agent").click().run()
    assert calls[-1] == ("Summarize this document", "groq", "openai/gpt-oss-120b")


def test_streamlit_catalog_cache_refresh_persistence_and_manual_warning(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    db_file = tmp_path / "selector-cache.db"
    connection = connect(db_file)
    connection.execute("INSERT INTO documents(path,kind,status) VALUES('Demo.pdf','pdf','ready')")
    connection.commit()
    connection.close()
    monkeypatch.setenv("SYDEN_DB_PATH", str(db_file))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-groq")
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-ollama")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    calls = []

    def fake_discover(provider, _key):
        calls.append(provider)
        if provider == "groq":
            return model_catalog.ModelCatalog((
                model_catalog.ModelOption("openai/gpt-oss-20b", "GPT-OSS 20B", True),
                model_catalog.ModelOption("openai/gpt-oss-120b", "GPT-OSS 120B", True)),
                unsupported=("whisper-large-v3",))
        return model_catalog.ModelCatalog((
            model_catalog.ModelOption("gpt-oss:20b", "GPT-OSS 20B", True),
            model_catalog.ModelOption("beam", "Beam", True)))

    monkeypatch.setattr(model_catalog, "discover_models", fake_discover)
    app = Path(__file__).resolve().parents[1] / "app.py"
    page = AppTest.from_file(app, default_timeout=10).run()
    page.sidebar.selectbox[0].set_value("groq").run()
    assert calls == ["groq"]
    page.run()
    assert calls == ["groq"]
    page.sidebar.selectbox[1].set_value("openai/gpt-oss-120b").run()
    page.sidebar.selectbox[0].set_value("ollama_cloud").run()
    assert calls == ["groq", "ollama_cloud"]
    assert page.sidebar.selectbox[1].value == "gpt-oss:20b"
    page.sidebar.selectbox[0].set_value("groq").run()
    assert page.sidebar.selectbox[1].value == "openai/gpt-oss-120b"
    assert calls == ["groq", "ollama_cloud"]
    next(button for button in page.sidebar.button
         if button.label == "Refresh models").click().run()
    assert calls.count("groq") == 2
    page.sidebar.selectbox[1].set_value("Other model ID (enter manually)").run()
    next(field for field in page.sidebar.text_input
         if field.label == "Model ID").set_value("whisper-large-v3").run()
    assert any("without the tool-calling capability" in warning.value
               for warning in page.sidebar.warning)
    assert next(button for button in page.button if button.label == "Ask agent").disabled


def test_gemma_is_initial_ollama_selection_but_user_can_change_it(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("SYDEN_DB_PATH", str(tmp_path / "gemma-default.db"))
    monkeypatch.setenv("LLM_PROVIDER", "ollama_cloud")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:31b")
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-ollama")
    monkeypatch.setattr(model_catalog, "discover_models", lambda provider, key:
                        model_catalog.ModelCatalog((
                            model_catalog.ModelOption("gpt-oss:20b", "GPT-OSS 20B", True),
                            model_catalog.ModelOption("gemma4:31b", "Gemma 4 31B", True))))
    app = Path(__file__).resolve().parents[1] / "app.py"
    page = AppTest.from_file(app, default_timeout=10).run()
    assert page.sidebar.selectbox[0].value == "ollama_cloud"
    assert page.sidebar.selectbox[1].value == "gemma4:31b"
    page.sidebar.selectbox[1].set_value("gpt-oss:20b").run()
    page.run()
    assert page.sidebar.selectbox[1].value == "gpt-oss:20b"


def test_streamlit_empty_live_catalog_reports_no_compatible_models(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    db_file = tmp_path / "empty-models.db"
    connection = connect(db_file)
    connection.execute("INSERT INTO documents(path,kind,status) VALUES('Demo.pdf','pdf','ready')")
    connection.commit()
    connection.close()
    monkeypatch.setenv("SYDEN_DB_PATH", str(db_file))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-groq-empty")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.setattr(model_catalog, "discover_models",
                        lambda provider, key: model_catalog.ModelCatalog(()))
    app = Path(__file__).resolve().parents[1] / "app.py"
    page = AppTest.from_file(app, default_timeout=10).run()
    page.sidebar.selectbox[0].set_value("groq").run()
    assert not page.exception
    assert any("No compatible tool-calling models" in warning.value
               for warning in page.sidebar.warning)
    assert page.sidebar.selectbox[1].value == "Other model ID (enter manually)"
    assert next(button for button in page.button if button.label == "Ask agent").disabled


def test_streamlit_model_listing_failure_shows_fallback_ids(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    db_file = tmp_path / "fallback-models.db"
    connection = connect(db_file)
    connection.execute("INSERT INTO documents(path,kind,status) VALUES('Demo.pdf','pdf','ready')")
    connection.commit()
    connection.close()
    monkeypatch.setenv("SYDEN_DB_PATH", str(db_file))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("OLLAMA_API_KEY", "synthetic-ollama-fallback")
    monkeypatch.setattr(model_catalog, "discover_models",
                        lambda provider, key: model_catalog.fallback_catalog(
                            provider, "Model listing unavailable. Showing fallback IDs."))
    app = Path(__file__).resolve().parents[1] / "app.py"
    page = AppTest.from_file(app, default_timeout=10).run()
    page.sidebar.selectbox[0].set_value("ollama_cloud").run()
    assert not page.exception
    assert page.sidebar.selectbox[1].value == "gemma4:31b"
    assert any("Model listing unavailable" in warning.value
               for warning in page.sidebar.warning)
    assert any("nemotron-3-ultra" in option
               for option in page.sidebar.selectbox[1].options)


def test_streamlit_never_shows_provider_failed_generation(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    db_file = tmp_path / "safe-errors.db"
    connection = connect(db_file)
    connection.execute("INSERT INTO documents(path,kind,status) VALUES('Demo.pdf','pdf','ready')")
    connection.execute("INSERT INTO metadata(key,value) VALUES('active_folder',?)",
                       (str(tmp_path),))
    connection.commit()
    connection.close()
    monkeypatch.setenv("SYDEN_DB_PATH", str(db_file))
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-groq-error")
    monkeypatch.setattr(model_catalog, "discover_models", lambda provider, key:
                        model_catalog.ModelCatalog((model_catalog.ModelOption(
                            "openai/gpt-oss-20b", "GPT-OSS 20B", True),)))

    class RawProviderError(Exception):
        def __init__(self):
            self.status_code = 400
            self.body = {"code": "output_parse_failed",
                         "failed_generation": "PRIVATE PLANNING TEXT"}

        def __str__(self):
            return "PRIVATE PLANNING TEXT"

    def fail(*_args, **_kwargs):
        raise RawProviderError()

    monkeypatch.setattr(agent, "ask", fail)
    app = Path(__file__).resolve().parents[1] / "app.py"
    page = AppTest.from_file(app, default_timeout=10).run()
    next(field for field in page.sidebar.text_input
         if field.label == "Folder path on this computer").set_value(str(tmp_path)).run()
    page.sidebar.selectbox[0].set_value("groq").run()
    page.text_area[0].set_value("What does the document say?").run()
    next(button for button in page.button if button.label == "Ask agent").click().run()
    assert not page.exception
    assert any("Groq rejected the unknown request" in error.value for error in page.error)
    assert any("code: output_parse_failed" in error.value for error in page.error)
    assert not any("PRIVATE PLANNING TEXT" in error.value for error in page.error)
