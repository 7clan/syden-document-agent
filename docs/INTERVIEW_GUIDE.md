# SYDEN interview walkthrough

This is preparation for explaining the repository. The required short personal
account of development is [DEVELOPMENT_NOTE.md](DEVELOPMENT_NOTE.md).

## Explain the application in 30 seconds

"SYDEN indexes a selected folder of project PDFs, Excel workbooks and Word
documents into local SQLite, retaining the original page, paragraph, sheet,
row and cell locations. An LLM uses real read-only function calls to search
and inspect that index. Python performs BOQ comparisons and totals. The UI
shows the answer, original cited evidence and tool audit. Source-linked prose
is inspectable but is not guaranteed semantically correct."

## Follow one question through the code

1. [app.py](../app.py) selects the folder and model. **Index folder** calls
   `ingest_folder`; **Ask agent** calls `ask`. It displays source links,
   status and the tool audit.
2. [ingest.py](../src/syden_agent/ingest.py) discovers supported files,
   parses each independently and records source locations. Switching folders
   clears the old corpus. Corrupt files receive a failed status while valid
   files remain usable.
3. [db.py](../src/syden_agent/db.py) creates the SQLite tables for documents,
   PDF passages and BOQ rows, Excel sheet rows, and Word blocks. The index is
   local and can be rebuilt from the original files.
4. [agent.py](../src/syden_agent/agent.py) sends the question and tool schemas
   to the selected provider. When the model calls a tool, Python validates its
   name and arguments and executes an allowlisted read-only function. The
   model then receives bounded original evidence and writes a structured
   answer. Calls and provider errors are recorded in the audit.
5. [tools.py](../src/syden_agent/tools.py) defines `list_documents`,
   `inspect_document`, `search_documents`, `extract_dates`, `get_evidence`,
   and the `query_spreadsheet` tool wrapper. `get_evidence` resolves a cited
   location against the actual index.
6. [spreadsheet.py](../src/syden_agent/spreadsheet.py) identifies BOQ amount
   columns, handles repeated headers and currencies, filters with strict or
   inclusive comparisons, and sums with `Decimal`. It preserves original
   cell citations and reports missing or ambiguous values.
7. The UI calls [source_viewer.py](../src/syden_agent/source_viewer.py) so a
   reviewer can open the indexed passage or cells behind a citation.

## Other files worth knowing

| File | Why it exists |
| --- | --- |
| [cli.py](../src/syden_agent/cli.py) | Command-line fallback: `ingest`, `list`, `boq`, `dates`, `ask`, and a live provider `smoke` check. |
| [model_catalog.py](../src/syden_agent/model_catalog.py) | Discovers compatible Groq and Ollama models, labels them and supplies fallbacks for the Streamlit selector. |
| [uploads.py](../src/syden_agent/uploads.py) and [file_manager.py](../src/syden_agent/file_manager.py) | Safely save browser uploads and remove or archive selected documents. |
| [ui_format.py](../src/syden_agent/ui_format.py) | Formats date and spreadsheet rows for display without changing indexed values. |
| [claim_verifier.py](../src/syden_agent/claim_verifier.py) and [semantic_verifier.py](../src/syden_agent/semantic_verifier.py) | Older verification experiments remain for offline regressions. The current provider answer path uses source linking instead of these semantic verdicts; no second verification-only LLM request is mandatory. |
| [pyproject.toml](../pyproject.toml) and [.env.example](../.env.example) | Dependencies, CLI entry point, test configuration and documented provider settings. Real keys belong only in local `.env`. |
| [scripts/create_demo.py](../scripts/create_demo.py) | Creates a fictional demonstration folder. |
| [scripts/package_submission.py](../scripts/package_submission.py) | Creates an allowlisted source-only archive under `.local/submission`. |
| [tests](../tests) and [ci.yml](../.github/workflows/ci.yml) | Offline synthetic regression suite and GitHub Actions pytest/Ruff gate. The live provider tests are separately documented because they depend on external quotas. |

## Design choices to defend

- **Why real function calling?** The provider selects a declared tool and
  supplies arguments. Python runs only the allowlisted document operation;
  model-generated SQL, code and shell commands are never executed.
- **Why SQLite and lexical search?** A local, portable index preserves source
  metadata without requiring a remote database or embedding service. Lexical
  search is transparent but can miss paraphrases and unusual layouts.
- **Why Python for Excel math?** A model can misread a unit rate or mix
  currencies. The query uses the stored cells and `Decimal`, applies the
  requested threshold, and returns exact cell references. Formula results
  without a saved cache are unknown, never calculated or assumed to be zero.
- **What does a citation prove?** `get_evidence` proves that the location exists
  in the index and was retrieved. It does not prove that the model interpreted
  the passage correctly. The UI labels prose as source-linked and lets the
  reviewer inspect it; checked BOQ totals get a separate deterministic label.
- **Why Gemma by default?** It gave the most consistent complete answers in
  small fictional live tests. Other providers remain selectable. Groq's free
  account hit token-per-minute limits and a final JSON error; Gemini sometimes
  hit quota and once expanded a named-contract question using BOQ-only facts.
  These are observed results, not a claim that Gemma is universally best.

## Five-minute live demonstration

1. Run `python -m streamlit run app.py`. Choose Ollama Cloud / `gemma4:31b`.
2. Set **Document folder** to the reviewer-provided folder, click **Index
   folder**, and inspect the ready/failed count. The local synthetic folder
   `.local/interview_tests/final_interview_3` is available only on this development computer.
3. Ask a contract-scope question. Open a PDF source and show the original page.
4. Ask for BOQ items strictly above SAR 1 million. Show the selected amount
   column, exact cells, sum and the tool audit.
5. Ask for dates and deliverables. Distinguish contractual, planning and
   proposed dates from the original evidence.

If the browser is unavailable, run `syden-agent ingest "<folder>"`, then
`syden-agent ask "<question>"` in PowerShell. If a model returns 429 or 500,
show the sanitized provider status and retry later or select another configured
provider. An unanswered provider request is never described as a passing answer.

## What the final fictional test established

In the seven-file, three-phase 21 October test, Gemma returned all expected
core facts and the exact BOQ total, though its scope answer included extra BOQ
quantities. Gemini gave the exact BOQ result but also treated BOQ-only rows as
contract scope; its hardest request hit 429 twice. Groq's first scope request
failed final JSON validation, its retry answered; its BOQ result was completed
by a clearly logged Python fallback after a provider limit, and its hardest
request hit 429 twice. See [TEST_PLAN.md](TEST_PLAN.md) for the source-checked
matrix. These results show both the working path and its factuality limits.
