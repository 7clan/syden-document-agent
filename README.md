# SYDEN Document Agent — working starter

A source-aware AI document assistant for project contracts and Bills of Quantities (BOQs).
**This is an evolving assessment implementation, not a benchmarked submission.** It indexes text PDFs,
Excel workbooks and Word documents, implements deterministic read-only tools, and has provider adapters for
Gemini, OpenAI, Groq, and Ollama Cloud. Three configured models passed live synthetic tool-call
smoke tests; see the verification section below.

## Features provided in the starter

- Index a local folder of PDF, `.xlsx`, `.xlsm`, legacy `.xls`, and `.docx` files; nested directories supported.
- Extract text by PDF page or Word paragraph/table row, and spreadsheet rows by exact workbook/sheet/cell metadata.
- Query Excel and extracted PDF BOQ amounts via Python rather than asking an LLM to calculate them.
- Report missing formula caches, conflicting or unknown currencies, and uncertain PDF text-line extraction.
- Mark numeric and date answers incomplete when a document failed indexing or has unreadable pages.
- Store data in a local SQLite database and report per-file corruption/unsupported formats.
- Six read-only tools: `list_documents`, `inspect_document`, `search_documents`, `query_spreadsheet`,
  `extract_dates`, `get_evidence`.
- Gemini (default), OpenAI, Groq-hosted Llama, or Ollama Cloud tool-calling loop, with source citations and an audit trace.
- Streamlit interface plus command-line invocation; offline `pytest` tests.

## Requirements

- Python 3.11 or newer, VS Code (optional), internet access for a cloud LLM.
- Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey) **or** OpenAI API key.
  The Gemini free tier is limited and availability depends on account/model; see
  [official pricing](https://ai.google.dev/gemini-api/docs/pricing). Alternatively use a
  [Groq API key](https://console.groq.com/keys) for hosted Llama. Provider credentials are
  separate from any ChatGPT/Codex subscription.
- **Privacy:** Google warns that data from the free tier may be used to improve their products;
  do not send real confidential employer documents to a free-tier model without permission.
  Confirm the processing terms of any LLM provider with the document owner.

## Quick start — Windows PowerShell

```powershell
# unzip the starter and open its root directory in VS Code
cd syden-document-agent-starter
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
# Open .env and add a valid GEMINI_API_KEY, never commit it.
mkdir documents
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
3. Click **Open** in the file picker. The app automatically saves the selected files into
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

The active path **does not run the old claim verifier**. It does not compare model
prose, dates or status words against cited rows, so correct grouped Excel answers
are no longer removed by per-row semantic checks. A valid citation establishes
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
pip install -e '.[dev]'
cp .env.example .env
# Add GEMINI_API_KEY. Keep .env private.
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
In a clean Windows virtual environment, the editable install completed and all 55
offline tests and Ruff checks passed on 2026-10-19. The three configured provider
smoke tests also passed on synthetic text after the audit fixes.
After the evidence-first refactor on 2026-10-20, the local suite passed 159
tests with 1 skipped, and Ruff passed. The pull request's GitHub Actions result
should be checked separately.
After the scoped provenance correction on 2026-10-20, the local suite passed
**184 tests with 1 skipped**, and Ruff passed. The tested live scenarios and
the remaining provider limits are recorded in [docs/TEST_PLAN.md](docs/TEST_PLAN.md).
After the structured Excel and provider-context fix on 2026-10-20, the local
suite passed **203 tests with 1 skipped**, and Ruff passed. A live Gemini
five-milestone schedule query returned five correctly cited, evidence-linked
claims; the latest Groq synthetic smoke run did not meet its strict success
criterion because one unsupported extra claim was omitted.
After removing claim interpretation checks from the active provider path on
2026-10-20, the local suite passed **214 tests with 1 skipped** and Ruff passed.
The new fictional PDF/XLS/XLSX live results, including a remaining Groq BOQ
HTTP 400 parsing failure, are recorded in [docs/TEST_PLAN.md](docs/TEST_PLAN.md).
After the source inspector and final-answer tool-budget fix on 2026-10-20, the
local suite passed **219 tests with 1 skipped** and Ruff passed. A live
`gemini-3.5-flash-lite` retest answered the five-milestone demo question with
schedule rows 2–6. An Ollama Cloud retest returned HTTP 500, and a second
attempt returned empty answer content; its live result remains unconfirmed.
After Groq parse-error handling and model discovery, the local test results are
recorded in [docs/TEST_PLAN.md](docs/TEST_PLAN.md). The live Groq date query
completed with citations; the next Groq call hit a provider 429, so the contract
and BOQ questions were checked separately without claiming live Groq success.
The discovered Ollama direct API ID `gpt-oss:20b` passed a synthetic
`search_documents` tool-call smoke check; other listed Ollama models have not
been checked for live tool-call reliability.
The later identical-document Gemma 4 31B, Ollama GPT-OSS 120B, and Groq GPT-OSS
120B checks are recorded in [docs/TEST_PLAN.md](docs/TEST_PLAN.md). They are a
small synthetic sample; the reported Ollama false absence and Groq HTTP 400 did
not recur on those checks.
The focused six-document acceptance fixes passed **251 tests with 1 skipped** and
Ruff locally. Gemini and Ollama Cloud answered the three focused questions
correctly against the original sources; Groq returned HTTP 429 before a focused
answer. A separate four-document fictional held-out evaluation is recorded in
[docs/TEST_PLAN.md](docs/TEST_PLAN.md). Passing those samples does not guarantee
accuracy on arbitrary documents; evidence-linked answers still need source review.
After a later, harder five-file fictional exercise, the local suite passed
**253 tests with 1 skipped** and Ruff passed. Ollama answered the three exact
brief examples after the currency and date fallback fixes. A cross-document
answer cited the wrong PDF for one correct fact, and some Gemini/Ollama requests
failed before answering;
see [docs/TEST_PLAN.md](docs/TEST_PLAN.md) for the observed results.

### Observed provider checks (2026-10-19)

| Provider/model | Synthetic tool-call smoke | Full BOQ question |
| --- | --- | --- |
| Gemini `gemini-2.5-flash` | Passed; called `search_documents` and `get_evidence` | Correct two rows and cell citations |
| Groq `openai/gpt-oss-20b` | Passed; called `search_documents` | Correct numeric tool results and amounts; model used typographic hyphens in item codes |
| Ollama Cloud `gpt-oss:20b-cloud` | Passed; called `search_documents` | Correct numeric tool results after a guarded retry; model used typographic hyphens in item codes |

This Groq key lists no Llama chat model. `llama-3.3-70b-versatile` and
`llama-3.1-8b-instant` both returned 404, so Groq-hosted Llama support remains
untested with this account. The OpenAI provider has not been live-tested because
no OpenAI API key was supplied. These checks used only generated demo documents.
After the 2026-10-20 claim refactor, synthetic Groq and Ollama Cloud smoke
checks returned structured, source-linked claims. Gemini could not be confirmed
at that time: its configured model returned 503 (high demand), while an old
Lite model returned 404 and the suggested replacement also returned 503.

## Current limitations

- Keyword search is a bounded lexical baseline; semantic/hybrid retrieval is not implemented.
- Scanned or image-only PDF pages need OCR; pages without extractable text are reported.
- PDF table extraction is heuristic. Borderless text-line BOQs are flagged for visual review, and rows without a verified currency are omitted from currency-filtered totals.
- Complex merged Excel headings and unusual BOQ layouts still need human inspection of the selected column and warnings.
- Date extraction identifies candidate dates and nearby actions; an action is not automatically a verified contractual deadline.
- Source-linked status checks that a citation exists and was retrieved, not that it supports the model's specific claim. A harder cross-document live test produced a correct fact with the wrong cited passages; inspect the original source for important conclusions.
- Groq-hosted Llama specifically and OpenAI have not been live-tested with accessible models/keys. Groq GPT-OSS has been tested.
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
The current, still-in-progress note is [docs/DEVELOPMENT_NOTE.md](docs/DEVELOPMENT_NOTE.md).
Update the estimated time before submission.

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

## Publish to GitHub (when ready)

The active GitHub repository is [7clan/syden-document-agent](https://github.com/7clan/syden-document-agent).
Review the code and keep documents and credentials out of commits. Create an empty GitHub repository
named `syden-document-agent` at https://github.com/new (choose visibility appropriately and do
not initialize it with a second README), then run in the extracted project directory:

```powershell
git init
git add .
git commit -m "Initialize source-grounded document agent"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/syden-document-agent.git
git push -u origin main
```

If GitHub CLI is installed and authenticated, you may instead use
`gh repo create syden-document-agent --private --source=. --remote=origin --push`
(after `git init`, `git add .`, and `git commit`).

Before submission: document an actual model-assisted test run, complete the half-page note,
verify README setup on a clean machine, and make the GitHub repo accessible to the reviewers.
