"""CLI supports rapid testing on any reviewer-provided document folder."""
from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from .agent import ask, provider_error_diagnostic, safe_provider_error
from .db import connect
from .ingest import ingest_folder
from .tools import extract_dates, list_documents, query_spreadsheet


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="SYDEN grounded document analysis agent")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("ingest", help="Index PDF, Word and Excel documents from a folder")
    add.add_argument("folder")
    commands.add_parser("list", help="Show indexed files and errors")
    boq = commands.add_parser("boq", help="Run a deterministic Excel/PDF BOQ amount query")
    boq.add_argument("--value", type=float, default=1_000_000)
    boq.add_argument("--operator", choices=["gt", "gte", "lt", "lte", "eq", "all"], default="gt")
    boq.add_argument("--currency", default="")
    boq.add_argument("--file", default="")
    boq.add_argument("--sheet", default="")
    boq.add_argument("--column-hint", default="total amount")
    boq.add_argument("--text-filter", default="")
    boq.add_argument("--limit", type=int, default=100)
    boq.add_argument("--offset", type=int, default=0)
    dates = commands.add_parser("dates", help="List candidate dates with pagination")
    dates.add_argument("--limit", type=int, default=100)
    dates.add_argument("--offset", type=int, default=0)
    smoke = commands.add_parser("smoke", help="Verify real provider tool calling using synthetic text")
    smoke.add_argument("--provider", choices=["gemini", "openai", "groq", "ollama_cloud",
                                               "compatible"])
    question = commands.add_parser("ask", help="Ask a question using LLM function calling")
    question.add_argument("question")
    question.add_argument("--provider", choices=["gemini", "openai", "groq",
                                                 "ollama_cloud", "compatible"])
    options = parser.parse_args()
    if getattr(options, "provider", None):
        os.environ["LLM_PROVIDER"] = options.provider
    conn = connect(":memory:" if options.command == "smoke" else
                   os.getenv("SYDEN_DB_PATH", ".local/syden_documents.db"))
    try:
        if options.command == "ingest":
            result = ingest_folder(conn, options.folder)
        elif options.command == "list":
            result = list_documents(conn)
        elif options.command == "boq":
            result = query_spreadsheet(conn, value=options.value, operator=options.operator,
                                       currency=options.currency, file=options.file,
                                       sheet=options.sheet, column_hint=options.column_hint,
                                       text_filter=options.text_filter,
                                       limit=options.limit, offset=options.offset)
        elif options.command == "dates":
            result = extract_dates(conn, limit=options.limit, offset=options.offset)
        elif options.command == "smoke":
            # An isolated, nonconfidential corpus tests actual provider function calls.
            conn.execute("INSERT INTO documents(path,kind,status) VALUES('smoke.pdf','pdf','ready')")
            conn.execute("INSERT INTO passages(document_id,page,chunk,text) "
                         "VALUES(1,1,0,'The synthetic project code is ORCHID-7429.')")
            conn.commit()
            try:
                answer = ask(conn, "What is the synthetic project code in smoke.pdf? "
                             "Use search_documents to find and cite it. Copy its exact characters "
                             "as plain ASCII; do not change the hyphen.")
                result = {"success": bool(any(call["name"] in {
                                          "search_documents", "get_evidence", "inspect_document"}
                                          and call.get("ok") for call in answer.tool_calls)
                                          and answer.verification_status != "unverified"
                                          and answer.sources and
                                          "ORCHID-7429" in answer.text and
                                          "could not be verified" not in answer.text),
                          "provider": os.getenv("LLM_PROVIDER", "gemini"),
                          "answer": answer.text, "sources": answer.sources,
                          "verification_status": answer.verification_status,
                          "tool_calls": answer.tool_calls}
            except Exception as exc:  # noqa: BLE001 - report hosted API failures cleanly
                result = {"success": False, "error": safe_provider_error(
                    exc, os.getenv("LLM_PROVIDER", "gemini")),
                    "diagnostic": provider_error_diagnostic(exc)}
        else:
            try:
                answer = ask(conn, options.question)
                result = {"answer": answer.text, "sources": answer.sources,
                          "verification_status": answer.verification_status,
                          "claims": answer.claims, "structured": answer.structured,
                          "tool_calls": answer.tool_calls}
            except Exception as exc:  # noqa: BLE001 - CLI should report provider failures cleanly
                result = {"error": safe_provider_error(
                    exc, os.getenv("LLM_PROVIDER", "gemini")),
                    "diagnostic": provider_error_diagnostic(exc)}
        # JSON escapes keep CLI output valid on Windows consoles with legacy code pages.
        print(json.dumps(result, ensure_ascii=True, indent=2))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
