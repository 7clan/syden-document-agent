# SYDEN Document Agent

A source-aware AI document assistant for project contracts and Bills of Quantities (BOQs).
It indexes text PDFs, Excel workbooks and Word documents, implements deterministic
read-only tools, and has provider adapters for Gemini, OpenAI, Groq, and Ollama Cloud.
Live tests used fictional documents; results and limitations are described below.
Source-linked model prose still needs human review.

## Features

- Index a local folder of PDF, `.xlsx`, `.xlsm`, legacy `.xls`, and `.docx` files; nested directories supported.
- Extract text by PDF page or Word paragraph/table row, and spreadsheet rows by exact workbook/sheet/cell metadata.
- Query Excel and extracted PDF BOQ amounts via Python rather than asking an LLM to calculate them.
- Report missing formula caches, conflicting or unknown currencies, and uncertain PDF text-line extraction.
- Mark numeric and date answers incomplete when a document failed indexing or has unreadable pages.
- Store data in a local SQLite database and report per-file corruption/unsupported formats.
- Six read-only tools: `list_documents`, `inspect_document`, `search_documents`, `query_spreadsheet`,
  `extract_dates`, `get_evidence`.
- Ollama Cloud (Gemma 4 31B by default), Gemini, OpenAI, or Groq tool-calling loop, with source citations and an audit trace.
- Streamlit interface plus command-line invocation; offline `pytest` tests.

## Requirements

- Python 3.11 or newer, VS Code (optional), internet access for a cloud LLM.
- Ollama Cloud API key for the default Gemma model, or a Gemini API key from
  [Google AI Studio](https://aistudio.google.com/apikey), or an OpenAI API key.
  The Gemini free tier is limited and availability depends on account/model; see
  [official pricing](https://ai.google.dev/gemini-api/docs/pricing). Alternatively use a
  [Groq API key](https://console.groq.com/keys) for an account-accessible compatible model. Provider credentials are
  separate from any ChatGPT/Codex subscription.
- **Privacy:** Google warns that data from the free tier may be used to improve their products;
  do not send real confidential employer documents to a free-tier model without permission.
  Confirm the processing terms of any LLM provider with the document owner.

## Quick start — Windows PowerShell

```powershell
git clone https://github.com/7clan/syden-document-agent.git
cd syden-document-agent
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[openai,dev]"
Copy-Item .env.example .env
# Open .env and add OLLAMA_API_KEY for the default Gemma model; never commit it.
New-Item -ItemType Directory -Force documents | Out-Null
# Copy your TEST documents into documents/ (they will not be committed).
syden-agent ingest "documents"
syden-agent list
syden-agent boq --value 1000000 --currency SAR  # deterministic query without an API call
syden-agent dates --limit 100 --offset 0         # paginated date candidates
syden-agent ask "List all cost items above SAR 1 million in the BOQs"
syden-agent smoke  # tests real provider function calling with synthetic, nonconfidential text
python -m streamlit run app.py
```

### Add downloaded documents in the browser (PDF, Excel, Word)

Keep the existing **Document folder** path field for folders already on disk. Or use the
new multi-file chooser beneath it to add downloaded files without moving them yourself:

1. In Streamlit, set **Folder path on this computer** to `documents` for a clean corpus,
   or keep `.local/demo_documents` to add to the demonstration corpus.
2. Click **Choose PDF, Excel, or Word files**, select one or many files from Downloads
   (Ctrl-click or Shift-click in the Windows file picker), and confirm with **Open**.
3. The app automatically saves the selected files into
   that folder, indexes them, and lists them under **Indexed files**; no second button is needed.
4. Ask the agent questions normally; no file path is required in the question.

Supported uploads: `.pdf`, `.xlsx`, `.xlsm`, `.xls`, and `.docx`.
If a selected file has the **same full filename and extension** as one already in
the selected folder, the app asks whether to **Keep both (rename new file)** or
**Replace existing file**. The default is Keep both, which creates names such
as `Contract (2).pdf`. A replacement happens **only after selecting Replace and
clicking Confirm**, and the index is refreshed so old document content is no
longer searchable. `mohammad.pdf` and `mohammad.xlsx` are distinct files and
never overwrite one another. If no filenames collide, upload remains automatic
after clicking **Open** in the browser file picker.

Unsupported and oversized uploads are refused; files that cannot be read are
reported by the indexer. Selecting a file in a browser is necessary for access
to your local Downloads: typing only its filename cannot grant browser access
to that local file. The old **Index folder** button still works.

### See, remove, or delete indexed documents

The sidebar's **Current documents** section displays every supported file in the
selected folder, including subfolders, with an index status (ready, failed, or
not indexed). This is more readable than the expandable JSON diagnostics.
**Index folder** remains available for files copied manually into the folder.
Selecting files through the browser upload saves them to disk and **automatically
runs indexing** without pressing the Index folder button.

Open **Remove or delete a document**, choose an exact filename, then select:

- **Remove from AI (keep an archived copy):** Move the file to a sibling folder
  named `<active-folder-name>_removed` outside the indexed folder. This is
  reversible by moving it back and clicking Index folder.
- **Permanently delete file:** Delete the selected disk file, not just its
  index entry. This cannot be undone by the application.

Both actions require a separate confirmation checkbox and button. After a
successful action, the index is refreshed automatically. Files with the same
basename but different extensions are managed independently.

### Source-linked AI answers

The live Gemini, Groq, Ollama Cloud and OpenAI paths return model-written claims with
source citations. Python checks that each cited location was actually retrieved and
still exists in the local index. The interface shows the model's wording beside the
original PDF/Word text or Excel cells. Model-supplied quotations are ignored; displayed
source text comes from the index.

Each passage-level source reference has an **Open source** button. It opens the
exact indexed PDF page and chunk, Word paragraph or table row, or Excel row or
cell. For local PDFs, the panel also renders the original page when the file is
still present in the indexed folder. The citation remains visible beside the
source content. This helps a reviewer check a model's interpretation; it is
not an automatic fact-verification verdict.

The active path **does not run the old claim verifier**. It does not judge model
prose or approval status through broad semantic rules, so correct grouped Excel
answers are no longer removed by per-row semantic checks. It does check that
explicit dates in a claim occur somewhere in its cited passages, accepting
equivalent unambiguous date formats. A valid citation establishes
provenance, not factual correctness: a model can still misunderstand a passage or
associate a short cell value with the wrong row. Such answers are labeled **AI answer
with checked source references; facts not verified**. An invalid or unobserved
citation is flagged, and its model claim remains visible as **unverified** so the
user can inspect the problem. Malformed model output is also unverified.

Financial BOQ filtering, strict thresholds and totals still come from Python's
read-only `query_spreadsheet` tool. Its exact source cells and arithmetic are
checked independently and labeled **deterministically calculated** when coverage
is complete. If a model retrieves documents but omits the required numeric tool,
the application runs a read-only deterministic fallback and labels that action
as application initiated in the audit trace. Candidate date extraction likewise
remains a tool result. For explicit requests to list all dates, the application
runs `extract_dates` once if the model omits it, and labels that fallback as
application initiated. Nearby text does not automatically prove a contractual obligation.

For a BOQ-subtotal-versus-contract comparison, the application retrieves each
worksheet total separately and an explicit original contract value from indexed
PDF text. If one base worksheet and one contract value are unambiguous, Python
compares those operands and cites the original amount cells and PDF passage.
This answer is labeled **evidence-linked** because identifying the intended
worksheet and contract clause still depends on document wording. If the operands
cannot be selected reliably, the application does not label model arithmetic as
deterministically verified. Small matching worksheets, such as milestone registers,
are supplied with all their indexed rows when they fit the context budget; larger
tables are marked incomplete.

The model still calls read-only document tools before answering. Repeated calls
are cached and bounded. Every new search returns its query-relevant excerpt,
even when an earlier search found the same citation. After search or inspection,
the agent also hands the next model request bounded original text resolved from
the index, up to 12,000 characters across the question. This makes source text
available even when a model never calls `get_evidence`; it does not establish
complete coverage of long documents. The audit records citation IDs and the size
of this handoff, not its text. A model that reports insufficient evidence after
retrieving sources
gets at most one answer retry with indexed evidence; if it still reports absence,
the answer remains unverified and the retrieved locations are shown for review.
If it uses the entire tool-round budget, one final
generation request with tools disabled asks it to answer from the evidence already
retrieved, or state that evidence is insufficient. For prose questions, a provider
that returns no answer shows no source references, since search hits alone do not
support a claim. Deterministic numeric and date queries can still return their
own checked source references.
A question naming a specific date also gets a bounded, application-initiated lookup
for indexed passages containing that date after the model's first document tool call.
Its audit event is labeled `host_date_context`; it is not represented as a model
function call. This improves cross-document evidence delivery without proving
the model's interpretation of an approval decision.
A provider may receive one formatting retry for malformed
JSON, but there is no second model request just to judge the answer. The legacy
`claim_verifier.py` and `semantic_verifier.py` remain for older offline regression
experiments; neither filters claims in the live provider path. For ambiguous
requests such as "the contract" when multiple contracts are indexed, name the
file. Cross-workbook BOQ sums remain separated by file and currency.

A structured response now needs only a claim and retrieved citation:

```json
{"answer":"Four circuits passed; two need retesting.","insufficient":false,
 "claims":[{"text":"Four circuits passed.","supports":[
   {"citation":"Report.pdf | page 1 | chunk 0"}]}]}
```

Groq and other compatible providers retry one HTTP 429 only when its `retry-after`
delay fits the bounded request budget; otherwise the app displays a wait message.
Groq HTTP 400 `output_parse_failed` is handled separately. The agent makes at
most one compact recovery request without including the provider's unparsed
generation. If a tool-capable request fails before useful evidence is retrieved,
the retry still uses real function calling. If evidence is already available,
the retry requests a final answer with tools disabled. GPT-OSS 20B/120B and
Qwen 3.8 27B use Groq's strict JSON schema on these tool-free final requests.
An unrecoverable parsing failure produces a short error without the provider's
`failed_generation` text. No failed output is treated as source evidence.
Provider failures show a safe diagnostic containing only HTTP status, a sanitized
error code, and the request phase (`tool` or `final`). Provider response bodies,
keys, and model reasoning are never copied into that diagnostic.
Ollama Cloud may not enforce structured output, so its JSON formatting still
needs live checking with the selected model.

### Choose a provider and model in Streamlit

Gemma 4 keeps the established system prompt. Other models receive one compact
additional instruction to inspect original evidence, use deterministic numeric
tools, keep approval and planning statuses distinct, and check each claim against
its own cited passage or row. This does not add another model request or certify
semantic correctness. Provider-specific prompt rules are added only when repeated
live errors show they are needed; HTTP 429, HTTP 500, and timeouts are reported as
provider failures rather than answer mistakes.

The **AI model** section in the Streamlit sidebar has a **Provider** dropdown and a
**Model** dropdown. You can switch between Gemini, Groq, Ollama Cloud, OpenAI, or a
custom OpenAI Chat Completions-compatible service without restarting the app.
Groq and Ollama Cloud model dropdowns use their official model-list APIs. Groq
models must advertise text input/output and the `tools` feature; Ollama Cloud
models must advertise both `completion` and `tools`. Each choice shows a friendly
name and the exact API ID. The list is cached for 15 minutes; **Refresh models**
fetches it again. A model-list failure shows fallback IDs with a warning, while
a successful empty list shows no compatible models. Configured and previously
selected IDs remain available with a compatibility warning if they disappear
from the live list. **Other model ID (enter manually)** remains available.
The last selected model is remembered separately for each provider during the
session. Switching providers/models clears the previous response.
The selected provider/model are passed to each question; the app does not rewrite
environment variables or disclose your API keys.

Add the corresponding `*_API_KEY` (and a compatible base URL, where required)
to your local `.env` before selecting a provider. A provider without its key
is shown but the **Ask agent** button remains disabled. For Groq, Ollama Cloud,
OpenAI and other compatible APIs, install the optional client:
`python -m pip install -e ".[openai,dev]"`.
The listing metadata identifies advertised tool support; it cannot guarantee
reliable function calling in a specific live question. Test using
`syden-agent smoke --provider <provider>` or a real question.

For OpenAI as provider, install `pip install -e ".[openai,dev]"`, set `LLM_PROVIDER=openai`
and `OPENAI_API_KEY` in `.env`.

For **Groq**, install `pip install -e ".[llama,dev]"`, then set
`LLM_PROVIDER=groq` and `GROQ_API_KEY` in `.env`. The default model ID is
`openai/gpt-oss-20b`; the dropdown discovers other account-accessible models,
including hosted Llama when available. This is a hosted API, not Ollama running locally.

For another OpenAI Chat Completions-compatible provider, use `LLM_PROVIDER=compatible`
and set `COMPATIBLE_API_KEY`, `COMPATIBLE_MODEL`, `COMPATIBLE_BASE_URL`.
Provider feature parity is **not** guaranteed: test custom tool calling with the exact model
and SDK before relying on it in the live interview.

For **Ollama Cloud direct API**, install `pip install -e ".[openai,dev]"`, set
`LLM_PROVIDER=ollama_cloud`, `OLLAMA_API_KEY`, and `OLLAMA_MODEL` in `.env`.
The adapter uses the [documented](https://docs.ollama.com/api/openai-compatibility)
`https://ollama.com/v1` Chat Completions endpoint.
The dropdown uses exact IDs returned by `https://ollama.com/api/tags` for direct
cloud access, such as `gpt-oss:20b`; an older configured `:cloud` alias remains
selectable but is flagged when it is absent from the current list. Ollama
documents API-level tool support. The discovered `gpt-oss:20b` ID passed a real
synthetic tool-call smoke test with the configured account; check your own
selected model before a demo.

### Environment variables

Copy `.env.example` to `.env` and fill only the provider you use. `LLM_PROVIDER` selects
`gemini`, `openai`, `groq`, `ollama_cloud`, or `compatible`. Each provider has its own
`*_API_KEY` and `*_MODEL`; OpenAI-compatible services also accept a `*_BASE_URL`.
`SYDEN_DB_PATH` selects the local SQLite index (default `.local/syden_documents.db`), and
`SYDEN_MAX_FILE_MB` sets the per-file size limit (default 100 MiB). Keep `.env` private.

## macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[openai,dev]'
cp .env.example .env
# Add OLLAMA_API_KEY for the default Gemma model. Keep .env private.
mkdir -p documents
syden-agent ingest documents
syden-agent ask 'Summarize the scope of work in this contract'
python -m streamlit run app.py
```

## Architecture

```
Documents folder (PDF/XLSX/XLSM/XLS/DOCX)
     | (read-only parsing and source provenance)
     v
SQLite: documents + PDF passages/BOQ rows + Word blocks + Excel rows
     |                                      |
     +-- PDF/Word/text search               +-- numeric Excel/PDF BOQ queries
                          ^
                          | explicit read-only function calling
                Gemini / OpenAI / Groq / Ollama Cloud agent
                          |
              Streamlit / CLI -> cited answer + trace
```

The architecture is deliberately small enough to explain and extend live.
For a file-by-file code tour and a short demo sequence, use the
[interview guide](docs/INTERVIEW_GUIDE.md).
For full implementation requirements and hardening priorities, see **`PROMPT_FOR_CODEX.md`**.

## Run offline checks

```powershell
python -m pytest -q
ruff check src tests app.py scripts
```

Tests construct synthetic workbooks and Word documents in temporary directories. No API credentials are needed for
these unit tests. Run `syden-agent smoke --provider gemini`, `--provider groq`, or
`--provider ollama_cloud` with your own key before relying on the model in a demo.
`success: true` requires an actual provider tool call, a verified source, and the exact
synthetic answer. The smoke command does not read your indexed documents.
The final local suite on 21 October 2026 passed **272 tests with 1 skipped**;
Ruff passed. [GitHub Actions](https://github.com/7clan/syden-document-agent/actions/workflows/ci.yml)
runs the same gate on repository updates; check its latest run before a demo.
Earlier test history and individual regression scenarios remain in
[docs/TEST_PLAN.md](docs/TEST_PLAN.md).

### Live interview-style provider results (21 October 2026)

A new, previously unused folder of seven fictional files (three PDFs, three
Excel workbooks and one Word document) was tested through the production
`ask()` path. The three phases
covered signed scope and deliverables, a strict SAR BOQ threshold, then a
cross-document change-order, deadline, and inspection decision. The original
files were read independently to assess the displayed answers. These are
small synthetic samples, not estimates of accuracy on employer documents.

| Provider and model | Contract scope | BOQ above SAR 1 million | Cross-document decision |
| --- | --- | --- | --- |
| Ollama Cloud `gemma4:31b` | All requested contract facts; also listed extra BOQ quantities | Correct: two cells, SAR 3,000,000 total | Correct with separate PDF, Word and Excel sources |
| Gemini `gemini-2.5-flash` | Contract facts present, but also described BOQ-only items as contract scope | Correct deterministic result | HTTP 429 on first call and one retry; no answer |
| Groq `openai/gpt-oss-20b` | Initial HTTP 400 final JSON; retry returned the requested facts plus extra BOQ quantities | Correct deterministic result; Python completed it after a provider limit | HTTP 429 on first call and one retry; no answer |

Every source citation in a completed answer resolved to indexed text or cells.
The BOQ was calculated in Python; an evidence-linked prose label does not prove
that the model interpreted scope correctly. The local synthetic documents and
full JSON audits are Git-ignored. OpenAI and Groq-hosted Llama were not live
checked with this account. The earlier live exercises and their observed
limitations are documented in [the test plan](docs/TEST_PLAN.md).

## Current limitations

- Keyword search is a bounded lexical baseline; semantic/hybrid retrieval is not implemented.
- Scanned or image-only PDF pages need OCR; pages without extractable text are reported.
- PDF table extraction is heuristic. Borderless text-line BOQs are flagged for visual review, and rows without a verified currency are omitted from currency-filtered totals.
- Complex merged Excel headings and unusual BOQ layouts still need human inspection of the selected column and warnings.
- Date extraction identifies candidate dates and nearby actions; an action is not automatically a verified contractual deadline.
- Source-linked status checks retrieved citation provenance and explicit date presence, not arbitrary semantic support. Inspect the original source for important conclusions.
- A model can cite a real BOQ row while incorrectly describing it as a clause of a named contract; the final fictional test observed this scope error with Gemini. Review which document establishes each interpretation.
- Ollama GPT-OSS 20B received a compact tool-name reminder; in a follow-up fictional test it still omitted the inspection part of a cross-document answer. If a model skips a numerical tool while multiple tables are indexed, the application now abstains instead of verifying a broad fallback total. See [the test plan](docs/TEST_PLAN.md).
- Groq-hosted Llama specifically and OpenAI have not been live-tested with accessible models/keys. Groq GPT-OSS has been tested.
- Hosted models can still return quota errors, HTTP 400/500, or exceed the answer time budget. Retries are bounded and errors are sanitized; Gemma remained the most consistent default in the latest fictional three-question exercise. See [the test plan](docs/TEST_PLAN.md) for observed results.
- The UI provides paginated BOQ/date results and BOQ CSV export, but preparing very large exports can be slow.
- Missing-cache `.xlsx`/`.xlsm` formulas are flagged; calculation remains out of scope.
- Legacy `.xls` formulas expose only their stored result through `xlrd`; formula expressions are not available. An absent cached result is never calculated. Password-protected `.xls` files cannot be read.
- Word indexing covers body paragraphs and top-level tables in document order. Content in headers, footers, comments, tracked revisions, text boxes and nested tables is not indexed. Source locations identify paragraphs or table rows rather than rendered page numbers.

## Source conventions

- PDF: `Contract.pdf | page 12 | chunk 2`
- PDF BOQ: `BOQ.pdf | page 1 | table 1 | row 2 | column B`
- Borderless PDF BOQ: `BOQ.pdf | page 1 | line 4 | amount` (flagged for visual review)
- Excel: `BOQ.xlsx | Electrical BOQ!C24`
- Legacy Excel: `BOQ.xls | Electrical BOQ!C24`
- Word: `Contract.docx | paragraph 7` or `Contract.docx | table 2 | row 3`

These references originate from stored metadata and are checked against indexed evidence.
Answers are not guaranteed correct solely because a model produces them; verify results
against independent acceptance fixtures.

## SYDEN assessment notes

The original brief scores delivery time, readable code/documentation and live accuracy on unseen
documents. The candidate must provide a GitHub repository and approximately half a page describing
actual coding-agent usage, actual hours spent, decisions and improvements with more time.
The [development note](docs/DEVELOPMENT_NOTE.md) records OpenAI Codex use,
design decisions, limitations and the candidate's approximately 11-hour
estimate of active involvement. This is an estimate, not a time-tracking log.

## Credentials and source-only archive

The audit found that an earlier ZIP contained `.env`. `.gitignore` does not protect ZIP files.
Rotate those exposed provider keys before submission. Do not include `.env`, local databases,
or real company files in a GitHub repository or shared archive. To create an allowlisted archive:

```powershell
python scripts/package_submission.py
```

The output is `.local/submission/syden-document-agent.zip`. Its contents are checked by an
offline test. Inspect the archive yourself before sharing it; this command does not rotate keys.

## References

- [Google Gemini function calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Google Python SDK](https://googleapis.github.io/python-genai/)
- [OpenAI tool calling](https://developers.openai.com/api/docs/guides/function-calling)
- [Groq local tool calling (custom Python functions)](https://console.groq.com/docs/tool-use/local-tool-calling)
- [Groq supported models](https://console.groq.com/docs/models)
- [openpyxl read-only and cached formula behavior](https://openpyxl.readthedocs.io/en/stable/optimized.html)
- [pdfplumber](https://github.com/jsvine/pdfplumber)
- [xlrd legacy Excel reader](https://xlrd.readthedocs.io/en/latest/)
- [python-docx document order](https://python-docx.readthedocs.io/en/latest/api/document.html)

## Repository and submission

The project is already published at [7clan/syden-document-agent](https://github.com/7clan/syden-document-agent),
with the current application on `main`. The previous `main` commit was preserved
on `archive/main-before-evidence-first-2026-10-21`. The source-only archive
above is optional; the GitHub repository and the development note are the
assessment deliverables. Keep credentials and generated document databases out
of anything shared with reviewers.
