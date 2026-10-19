"""Minimal Streamlit front-end for a live 30-minute technical review."""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from syden_agent.agent import ask
from syden_agent.db import connect
from syden_agent.ingest import ingest_folder
from syden_agent.tools import extract_dates, list_documents, query_spreadsheet
from syden_agent.ui_format import display_safe_rows
from syden_agent.uploads import save_uploaded_file

load_dotenv()
st.set_page_config(page_title="SYDEN Document Agent", page_icon="📄", layout="wide")
st.title("Project Document Agent")
st.caption("PDFs + Excel + Word · Evidence-grounded answers · Read-only tool calling")
conn = connect(os.getenv("SYDEN_DB_PATH", ".local/syden_documents.db"))
PROVIDERS = {
    "gemini": ("Google Gemini", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.5-flash"),
    "groq": ("Groq", "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-20b"),
    "ollama_cloud": ("Ollama Cloud", "OLLAMA_API_KEY", "OLLAMA_MODEL", "gpt-oss:20b-cloud"),
    "openai": ("OpenAI", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4.1-mini"),
    "compatible": ("Other compatible API", "COMPATIBLE_API_KEY",
                   "COMPATIBLE_MODEL", ""),
}
CUSTOM_MODEL = "Other model ID (enter manually)"
with st.sidebar:
    st.subheader("AI model")
    provider_ids = list(PROVIDERS)
    configured_provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    provider = st.selectbox(
        "Provider", provider_ids,
        index=provider_ids.index(configured_provider) if configured_provider in provider_ids else 0,
        format_func=lambda value: PROVIDERS[value][0],
    )
    provider_label, api_key_var, model_var, tested_model = PROVIDERS[provider]
    configured_model = os.getenv(model_var, "").strip()
    model_options = list(dict.fromkeys(
        candidate for candidate in (configured_model, tested_model) if candidate
    ))
    model_options.append(CUSTOM_MODEL)
    model_choice = st.selectbox("Model", model_options, key=f"model_{provider}")
    selected_model = (st.text_input("Model ID", key=f"custom_model_{provider}").strip()
                      if model_choice == CUSTOM_MODEL else model_choice)
    has_key = bool(os.getenv(api_key_var, "").strip())
    if not has_key:
        st.info(f"Add {api_key_var} to your local .env to use this provider.")
    if provider == "compatible" and not os.getenv("COMPATIBLE_BASE_URL", "").strip():
        st.info("Other compatible APIs also need COMPATIBLE_BASE_URL in .env.")
    ready_to_ask = bool(has_key and selected_model and
                        (provider != "compatible" or
                         os.getenv("COMPATIBLE_BASE_URL", "").strip()))
    selection = (provider, selected_model)
    if st.session_state.get("_llm_selection") != selection:
        st.session_state.pop("last_answer", None)
        st.session_state.pop("csv_export", None)
        st.session_state["_llm_selection"] = selection
    st.caption(f"Selected: {provider_label} / {selected_model or 'Choose a model'}")
    st.divider()
    st.subheader("Document folder")
    default_folder = ".local/demo_documents" if Path(".local/demo_documents").is_dir() else "documents"
    folder = st.text_input("Folder path on this computer", default_folder)
    if st.button("Index folder", type="primary", use_container_width=True):
        with st.spinner("Reading documents..."):
            st.session_state["index_report"] = ingest_folder(conn, folder)
            st.session_state.pop("last_answer", None)
            st.session_state.pop("csv_export", None)
    st.caption("Add downloaded files without moving them manually:")
    revision = st.session_state.get("_document_upload_revision", 0)
    selected_files = st.file_uploader(
        "Choose PDF, Excel, or Word files",
        type=["pdf", "xlsx", "xlsm", "xls", "docx"],
        accept_multiple_files=True,
        key=f"document_upload_{revision}",
    )
    if st.button("Add selected files and index", disabled=not selected_files,
                 use_container_width=True):
        added: list[str] = []
        errors: list[str] = []
        max_bytes = int(os.getenv("SYDEN_MAX_FILE_MB", "100")) * 1024 * 1024
        with st.spinner("Saving and indexing selected documents..."):
            for selected in selected_files:
                try:
                    saved = save_uploaded_file(
                        folder, selected.name, selected.getbuffer(), max_bytes,
                    )
                    added.append(saved)
                except (OSError, ValueError) as exc:
                    errors.append(f"{selected.name}: {exc}")
            if added:
                st.session_state["index_report"] = ingest_folder(conn, folder)
                st.session_state.pop("last_answer", None)
                st.session_state.pop("csv_export", None)
                # Clear the file chooser so the same selection is not added again.
                st.session_state["_document_upload_revision"] = revision + 1
        if added:
            st.success(f"Saved {len(added)} file(s) to {Path(folder).expanduser().resolve()}: "
                       + ", ".join(added))
            report = st.session_state["index_report"]
            if report.get("failed") or report.get("error"):
                st.warning("Some documents could not be indexed; inspect the report below.")
        for error in errors:
            st.error(error)
    if "index_report" in st.session_state:
        st.json(st.session_state["index_report"], expanded=False)
    st.subheader("Indexed files")
    document_status = list_documents(conn)
    failed = [doc for doc in document_status["documents"]
              if doc["status"] != "ready" or doc["error"]]
    if failed:
        st.warning(f"Coverage incomplete: {len(failed)} file(s) failed or have unreadable pages.")
    st.json(document_status, expanded=False)

question = st.text_area("Ask a question about the indexed documents",
                        placeholder="List all total cost items above SAR 1 million across the BOQs")
if st.button("Ask agent", disabled=not question.strip() or not ready_to_ask,
             type="primary"):
    with st.spinner("Analyzing evidence..."):
        try:
            answer = ask(conn, question, provider=provider, model=selected_model)
        except Exception as exc:  # noqa: BLE001 - show provider errors in the UI
            st.error(f"Agent error: {exc}")
        else:
            st.session_state["last_answer"] = answer
            st.session_state.pop("csv_export", None)

if "last_answer" in st.session_state:
    answer = st.session_state["last_answer"]
    st.markdown(answer.text)
    st.subheader("Verified source references")
    if answer.sources:
        for source in answer.sources:
            st.code(source)
    else:
        st.info("No verified citations returned. Do not rely on unsupported claims.")
    with st.expander("Tool calls / audit trail"):
        st.json(answer.tool_calls)

    if answer.structured and "dates" in answer.structured:
        st.subheader("Candidate dates and related context")
        date_total = answer.structured["total_matches"]
        date_pages = max(1, (date_total + 99) // 100)
        date_page = st.number_input("Date page", min_value=1, max_value=date_pages,
                                    value=1, step=1)
        date_result = (answer.structured if date_page == 1 else
                       extract_dates(conn, limit=100, offset=(date_page - 1) * 100))
        st.caption(f"Showing {len(date_result['dates'])} of {date_total} candidate dates; "
                   "ambiguous dates are not assigned a definite deadline.")
        st.dataframe(display_safe_rows(date_result["dates"]), use_container_width=True)

    spreadsheet_calls = [call for call in answer.tool_calls
                         if call["name"] == "query_spreadsheet" and call.get("ok", True)]
    if spreadsheet_calls:
        args = (answer.structured or {}).get("verified_args") or {
            key: value for key, value in spreadsheet_calls[-1]["args"].items()
            if key not in {"limit", "offset"}}
        st.subheader("Spreadsheet matches")
        page_size = 100
        first = query_spreadsheet(conn, **args, limit=page_size)
        if "error" in first:
            st.warning(first["error"])
        else:
            total = first["total_matches"]
            page_count = max(1, (total + page_size - 1) // page_size)
            page = st.number_input("Page", min_value=1, max_value=page_count,
                                   value=1, step=1)
            current = first if page == 1 else query_spreadsheet(
                conn, **args, limit=page_size, offset=(page - 1) * page_size)
            st.caption(f"Showing {current['returned']} of {total} matches; "
                       f"page {page} of {page_count}. Amount totals: "
                       f"{current['matched_amount_sums']}")
            if current["warnings"]:
                st.warning("; ".join(current["warnings"]))
            st.dataframe([{"citation": item["citation"], "amount": item["amount_exact"],
                           "currency": item["currency"], **item["values"]}
                          for item in current["matches"]], use_container_width=True)
            if st.button("Prepare complete CSV export"):
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=[
                    "citation", "amount", "currency", "row_values_json"])
                writer.writeheader()
                for offset in range(0, total, 500):
                    batch = query_spreadsheet(conn, **args, limit=500, offset=offset)
                    for item in batch["matches"]:
                        writer.writerow({"citation": item["citation"],
                                         "amount": item["amount_exact"],
                                         "currency": item["currency"],
                                         "row_values_json": json.dumps(
                                             item["values"], ensure_ascii=False)})
                st.session_state["csv_export"] = output.getvalue().encode("utf-8-sig")
            if "csv_export" in st.session_state:
                st.download_button("Download all matches as CSV",
                                   st.session_state["csv_export"],
                                   file_name="syden_spreadsheet_matches.csv",
                                   mime="text/csv")
