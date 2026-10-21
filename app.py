"""Minimal Streamlit front-end for a live 30-minute technical review."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from syden_agent import model_catalog
from syden_agent.agent import ask, provider_error_diagnostic, safe_provider_error
from syden_agent.db import connect
from syden_agent.file_manager import folder_files, remove_document
from syden_agent.ingest import ingest_folder
from syden_agent.source_viewer import local_pdf_page, source_detail
from syden_agent.tools import extract_dates, list_documents, query_spreadsheet
from syden_agent.ui_format import display_safe_rows
from syden_agent.uploads import save_uploaded_file

load_dotenv()


@st.cache_data(ttl=900, show_spinner=False)
def _cached_model_catalog(provider: str, key_fingerprint: str,
                          _api_key: str) -> model_catalog.ModelCatalog:
    """Cache the account's model list without making it part of every UI rerun."""
    return model_catalog.discover_models(provider, _api_key)


st.set_page_config(page_title="SYDEN Document Agent", page_icon="📄", layout="wide")
st.title("Project Document Agent")
st.caption("PDFs + Excel + Word · Evidence-grounded answers · Read-only tool calling")
conn = connect(os.getenv("SYDEN_DB_PATH", ".local/syden_documents.db"))
PROVIDERS = {
    "gemini": ("Google Gemini", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.5-flash"),
    "groq": ("Groq", "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-20b"),
    "ollama_cloud": ("Ollama Cloud", "OLLAMA_API_KEY", "OLLAMA_MODEL", "gemma4:31b"),
    "openai": ("OpenAI", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4.1-mini"),
    "compatible": ("Other compatible API", "COMPATIBLE_API_KEY",
                   "COMPATIBLE_MODEL", ""),
}
CUSTOM_MODEL = "Other model ID (enter manually)"
with st.sidebar:
    st.subheader("AI model")
    provider_ids = list(PROVIDERS)
    configured_provider = os.getenv("LLM_PROVIDER", "ollama_cloud").strip().lower()
    provider = st.selectbox(
        "Provider", provider_ids,
        index=provider_ids.index(configured_provider) if configured_provider in provider_ids else 0,
        format_func=lambda value: PROVIDERS[value][0],
    )
    provider_label, api_key_var, model_var, tested_model = PROVIDERS[provider]
    configured_model = os.getenv(model_var, "").strip()
    api_key = os.getenv(api_key_var, "").strip()
    has_key = bool(api_key)
    discovered = None
    if provider in {"groq", "ollama_cloud"}:
        if st.button("Refresh models"):
            _cached_model_catalog.clear()
        fingerprint = hashlib.sha256(api_key.encode()).hexdigest() if api_key else "no-key"
        discovered = _cached_model_catalog(provider, fingerprint, api_key)
        if discovered.warning:
            st.warning(discovered.warning)
        if not discovered.models and has_key:
            st.warning("No compatible tool-calling models were listed for this provider. "
                       "You can enter a model ID manually after checking its capabilities.")
        model_options = [choice.id for choice in discovered.models]
        model_labels = {choice.id: f"{choice.name} ({choice.id})"
                        for choice in discovered.models}
        if configured_model and configured_model not in model_options:
            model_options.append(configured_model)
            model_labels[configured_model] = f"Configured: {configured_model} (not listed)"
    else:
        model_options = list(dict.fromkeys(
            candidate for candidate in (configured_model, tested_model) if candidate
        ))
        model_labels = {candidate: candidate for candidate in model_options}
    model_key = f"model_{provider}"
    previous_model = (st.session_state.get(model_key) or
                      st.session_state.get(f"_saved_{model_key}"))
    if (previous_model and previous_model != CUSTOM_MODEL
            and previous_model not in model_options):
        model_options.append(previous_model)
        model_labels[previous_model] = f"Previously selected: {previous_model} (not listed)"
    model_options.append(CUSTOM_MODEL)
    listed_models = {choice.id for choice in discovered.models} if discovered else set(model_options)
    default_model = (CUSTOM_MODEL if discovered and discovered.source == "live"
                     and not discovered.models else
                     configured_model if configured_model in listed_models else
                     tested_model if tested_model in listed_models else model_options[0])
    model_choice = st.selectbox("Model", model_options, key=model_key,
                                index=(model_options.index(previous_model)
                                       if previous_model in model_options else
                                       model_options.index(default_model)),
                                format_func=lambda value: model_labels.get(value, value))
    st.session_state[f"_saved_{model_key}"] = model_choice
    if model_choice == CUSTOM_MODEL:
        manual_key = f"custom_model_{provider}"
        selected_model = st.text_input(
            "Model ID", key=manual_key,
            value=st.session_state.get(f"_saved_{manual_key}", "")).strip()
        st.session_state[f"_saved_{manual_key}"] = selected_model
    else:
        selected_model = model_choice
    unsupported_model = bool(discovered and selected_model in discovered.unsupported)
    if unsupported_model:
        st.warning("This model is listed without the tool-calling capability SYDEN needs.")
    elif (discovered and selected_model and model_choice != CUSTOM_MODEL
          and selected_model not in {choice.id for choice in discovered.models}):
        st.warning("This model ID was not in the current compatible model list. "
                   "Verify tool calling before using it.")
    elif discovered and model_choice == CUSTOM_MODEL and selected_model:
        st.warning("Manual model ID: tool-calling support has not been confirmed.")
    if not has_key:
        st.info(f"Add {api_key_var} to your local .env to use this provider.")
    if provider == "compatible" and not os.getenv("COMPATIBLE_BASE_URL", "").strip():
        st.info("Other compatible APIs also need COMPATIBLE_BASE_URL in .env.")
    ready_to_ask = bool(has_key and selected_model and not unsupported_model and
                        (provider != "compatible" or
                         os.getenv("COMPATIBLE_BASE_URL", "").strip()))
    selection = (provider, selected_model)
    if st.session_state.get("_llm_selection") != selection:
        st.session_state.pop("last_answer", None)
        st.session_state.pop("open_source", None)
        st.session_state.pop("csv_export", None)
        st.session_state["_llm_selection"] = selection
    st.caption(f"Selected: {provider_label} / {selected_model or 'Choose a model'}")
    st.divider()
    st.subheader("Document folder")
    default_folder = ".local/demo_documents" if Path(".local/demo_documents").is_dir() else "documents"
    folder = st.text_input("Folder path on this computer", default_folder)
    target_folder = Path(folder).expanduser().resolve()
    if st.session_state.get("_selected_folder") != str(target_folder):
        st.session_state.pop("last_answer", None)
        st.session_state.pop("open_source", None)
        st.session_state.pop("csv_export", None)
        st.session_state["_selected_folder"] = str(target_folder)
    if st.button("Index folder", type="primary", use_container_width=True):
        with st.spinner("Reading documents..."):
            st.session_state["index_report"] = ingest_folder(conn, folder)
            st.session_state.pop("last_answer", None)
            st.session_state.pop("open_source", None)
            st.session_state.pop("csv_export", None)
    st.caption(f"Add files here to: {Path(folder).expanduser().resolve()}")
    revision = st.session_state.get("_document_upload_revision", 0)
    selected_files = st.file_uploader(
        "Select one or more PDF, Excel, or Word files",
        type=["pdf", "xlsx", "xlsm", "xls", "docx"],
        accept_multiple_files=True,
        key=f"document_upload_{revision}",
    )
    collisions = [selected.name for selected in selected_files
                  if (target_folder / selected.name).is_file()]
    replace_names: set[str] = set()
    confirmed = bool(selected_files and not collisions)
    if collisions:
        st.warning("Some selected filenames already exist in this folder. "
                   "Confirm whether to replace each existing document or keep both.")
        for index, filename in enumerate(dict.fromkeys(collisions)):
            decision = st.radio(
                f"'{filename}' already exists. Are you sure you want to replace it?",
                ["Keep both (rename the new file)", "Replace existing file"],
                index=0, key=f"replace_upload_{revision}_{index}",
            )
            if decision == "Replace existing file":
                replace_names.add(filename)
        confirmed = st.button("Confirm and import selected files",
                              type="primary", use_container_width=True)
        if st.button("Cancel upload", use_container_width=True):
            st.session_state["_document_upload_revision"] = revision + 1
            st.rerun()
    if confirmed:
        added: list[str] = []
        replaced: list[str] = []
        errors: list[str] = []
        max_bytes = int(os.getenv("SYDEN_MAX_FILE_MB", "100")) * 1024 * 1024
        with st.spinner("Saving and indexing selected documents..."):
            for selected in selected_files:
                try:
                    replacing = selected.name in replace_names
                    saved = save_uploaded_file(
                        folder, selected.name, selected.getbuffer(), max_bytes,
                        replace_existing=replacing,
                    )
                    (replaced if replacing else added).append(saved)
                except (OSError, ValueError) as exc:
                    errors.append(f"{selected.name}: {exc}")
            if added or replaced:
                st.session_state["index_report"] = ingest_folder(conn, folder)
                st.session_state.pop("last_answer", None)
                st.session_state.pop("csv_export", None)
        st.session_state["upload_feedback"] = {
            "added": added,
            "replaced": replaced,
            "errors": errors,
            "folder": str(target_folder),
        }
        # Reset file chooser so a rerun does not repeat a replacement.
        st.session_state["_document_upload_revision"] = revision + 1
        st.rerun()
    feedback = st.session_state.pop("upload_feedback", None)
    if feedback:
        if feedback["added"]:
            st.success(f"Added {len(feedback['added'])} file(s) in "
                       f"{feedback['folder']}: " + ", ".join(feedback["added"]))
        if feedback["replaced"]:
            st.success(f"Replaced {len(feedback['replaced'])} file(s) and refreshed the index: "
                       + ", ".join(feedback["replaced"]))
        if feedback["added"] or feedback["replaced"]:
            report = st.session_state["index_report"]
            if report.get("failed") or report.get("error"):
                st.warning("Some documents could not be indexed; inspect the report below.")
        for error in feedback["errors"]:
            st.error(error)
    if "index_report" in st.session_state:
        st.json(st.session_state["index_report"], expanded=False)
    st.subheader("Current documents")
    active_folder = conn.execute(
        "SELECT value FROM metadata WHERE key='active_folder'"
    ).fetchone()
    folder_is_indexed = bool(active_folder and
                             Path(active_folder["value"]).resolve() == target_folder)
    disk_files = folder_files(target_folder)
    indexed = list_documents(conn) if folder_is_indexed else {"documents": [], "count": 0}
    statuses = {doc["path"]: doc for doc in indexed["documents"]}
    st.caption(f"{len(disk_files)} file(s) in the selected folder; "
               f"{sum(statuses.get(name, {}).get('status') == 'ready' for name in disk_files)} ready.")
    if not folder_is_indexed:
        st.info("This folder isn't the active index yet. Click Index folder to use its documents.")
    if not disk_files:
        st.info("No supported documents in this folder. Select files above to add them.")
    else:
        with st.container(height=225, border=True):
            for name in disk_files:
                extension = Path(name).suffix.lower()
                symbol = ("📕" if extension == ".pdf" else "📘" if extension == ".docx"
                          else "📗")
                status = statuses.get(name, {}).get("status", "not indexed")
                st.text(f"{symbol} {name} · {status}")
        failed = [doc for doc in indexed["documents"]
                  if doc["status"] != "ready" or doc["error"]]
        if failed:
            st.warning(f"Coverage incomplete: {len(failed)} file(s) failed or have warnings.")
        with st.expander("Remove or delete a document", expanded=False):
            managed_file = st.selectbox(
                "Choose a file",
                options=disk_files,
                index=None,
                placeholder="Select a document",
                key=f"manage_file_{target_folder!s}",
            )
            action = st.radio(
                "What should happen to it?",
                ["Remove from AI (keep an archived copy)", "Permanently delete file"],
                key="manage_file_action",
            )
            if action.startswith("Remove"):
                st.caption("Moves the file outside the indexed folder so it won't "
                           "return when you index again. The copy can be restored later.")
            else:
                st.warning("Permanent deletion removes the file from disk, not just the AI.")
            agree = st.checkbox(
                f"I confirm this action for {managed_file}" if managed_file
                else "Select a document to confirm its removal",
                value=False,
                key=f"confirm_manage_{managed_file}_{action}",
                disabled=managed_file is None,
            )
            if st.button("Confirm document removal",
                         disabled=not (managed_file and agree),
                         use_container_width=True):
                try:
                    archived = remove_document(
                        target_folder, managed_file,
                        delete_permanently=action.startswith("Permanently"),
                    )
                except (OSError, ValueError) as exc:
                    st.error(f"Could not manage document: {exc}")
                else:
                    with st.spinner("Refreshing the document index..."):
                        st.session_state["index_report"] = ingest_folder(conn, folder)
                    st.session_state.pop("last_answer", None)
                    st.session_state.pop("csv_export", None)
                    st.session_state["manage_feedback"] = (
                        f"Removed {managed_file} from the AI; saved copy: {archived}"
                        if archived else f"Permanently deleted {managed_file}."
                    )
                    st.rerun()
    message = st.session_state.pop("manage_feedback", None)
    if message:
        st.success(message)
    with st.expander("Index details and diagnostics", expanded=False):
        st.json(indexed, expanded=False)

question = st.text_area("Ask a question about the indexed documents",
                        placeholder="List all total cost items above SAR 1 million across the BOQs")
st.caption("Questions are independent: include the filename, threshold, or item selection "
           "instead of referring to 'those items' from an earlier answer.")
if st.button("Ask agent", disabled=not question.strip() or not ready_to_ask or
             not folder_is_indexed,
             type="primary"):
    with st.spinner("Analyzing evidence..."):
        try:
            answer = ask(conn, question, provider=provider, model=selected_model)
        except Exception as exc:  # noqa: BLE001 - show provider errors in the UI
            st.session_state.pop("last_answer", None)
            st.error(safe_provider_error(exc, provider))
            st.caption("Provider diagnostic (status, code, request phase only)")
            st.json(provider_error_diagnostic(exc))
        else:
            st.session_state["last_answer"] = answer
            st.session_state.pop("csv_export", None)

if "last_answer" in st.session_state:
    answer = st.session_state["last_answer"]
    status_labels = {"deterministically_verified": "Deterministically calculated",
                     "evidence_linked": "AI answer with checked source references; facts not verified",
                     "unverified": "Unverified or insufficient"}
    inventory_answer = "document_inventory" in (answer.structured or {})
    checked_comparison = (answer.verification_status == "evidence_linked"
                          and "boq_subtotal" in (answer.structured or {})
                          and "contract_value" in (answer.structured or {}))
    status_label = ("Indexed file list checked locally" if inventory_answer else
                    "Python-checked amounts; source selection needs review"
                    if checked_comparison else
                    status_labels.get(answer.verification_status, "Unverified"))
    st.caption("Answer status: " + status_label)
    st.markdown(answer.text)
    st.subheader("Source references")
    candidate_sources = (answer.structured or {}).get("candidate_sources", [])
    precise_sources = [source for source in answer.sources
                       if not source.endswith(" | document")]
    if answer.sources:
        for index, source in enumerate(precise_sources):
            label, control = st.columns([5, 1])
            label.code(source)
            if control.button("Open source", key=f"source_{index}"):
                st.session_state["open_source"] = source
        if not precise_sources:
            if inventory_answer:
                st.caption("File names, formats, and counts come from the local index records.")
                for source in answer.sources:
                    st.code(source)
            else:
                st.info("Only document names were retrieved; no exact passage or row was cited.")
    else:
        st.info("No claim-supporting citations returned. Do not rely on unsupported claims.")
    if candidate_sources:
        st.caption("Retrieved locations for manual review; these do not verify the model's claim.")
        if len(candidate_sources) > 12:
            st.caption(f"Showing 12 of {len(candidate_sources)} candidate locations; "
                       "narrow the question to inspect the rest.")
        for index, source in enumerate(candidate_sources[:12]):
            label, control = st.columns([5, 1])
            label.code(source)
            if control.button("Open source", key=f"candidate_{index}"):
                st.session_state["open_source"] = source
    selected_source = st.session_state.get("open_source")
    if selected_source in [*precise_sources, *candidate_sources]:
        detail = source_detail(conn, selected_source)
        st.markdown("#### Indexed source location")
        st.code(selected_source)
        if "error" in detail:
            st.warning(detail["error"])
        else:
            evidence = detail["evidence"]
            if "row" in evidence:
                st.table([{"Cell": column, "Indexed value": value}
                          for column, value in evidence["row"].items()])
                if "value" in evidence:
                    st.caption("Cited cell value: " + str(evidence["value"].get("value")))
            else:
                if evidence.get("section"):
                    st.caption("Section: " + str(evidence["section"]))
                st.text(evidence.get("text", ""))
            if detail["kind"] == "pdf":
                location = local_pdf_page(conn, selected_source)
                if location:
                    pdf_path, page_number = location
                    try:
                        import pdfplumber

                        with pdfplumber.open(pdf_path) as pdf:
                            st.image(pdf.pages[page_number - 1].to_image(
                                resolution=100).original,
                                caption=f"Original PDF, page {page_number}")
                    except (OSError, IndexError, ValueError) as exc:
                        st.caption(f"Original page preview unavailable: {exc}")
    if answer.claims:
        with st.expander("Model claims and indexed sources"):
            for claim in answer.claims:
                st.write(f"{status_labels.get(claim['status'], 'Unverified')}: "
                         f"{claim['text']}")
                st.caption(claim["reason"])
                for support in claim.get("quotes", []):
                    st.caption(f"{support['citation']}: indexed text/cells: {support['quote']}")
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
