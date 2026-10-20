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

### General-purpose evidence verification

The tool-calling model returns a JSON answer with individual claims and source
citations. A support may contain an exact quote or an empty quote. Python
resolves the citation against the local index, authenticates a supplied quote,
or selects a local source span when the quote is empty. Claim audit records
include the indexed excerpt and character offsets. Python checks explicit
numbers, dates, currencies, identifiers, and directly comparable conflicting
facts. These checks establish provenance and detect some errors; they cannot
prove arbitrary natural-language interpretations.

For Excel rows, Python reads the original structured cells. The model may
describe several columns in a different word order; its prose is checked
against the cited row's identifiers, dates, numbers, approval and
classification values instead of being treated as a verbatim quote. The audit
excerpt comes from indexed cells, and these interpretations remain
**evidence-linked**. PDF and Word quotes still require an authentic local text
span. Spreadsheet inspection previews include copyable row citations.
`query_spreadsheet` searches financial BOQ amounts; zero matches there do not
mean a milestone schedule is empty.
When one claim names several spreadsheet records, each named identifier must
have a cited row. Shared properties are checked against every cited row;
different per-record dates or amounts are best stated as separate claims.
This local check cannot prove an arbitrary interpretation of a row.

Each claim identifies the numbered part of the question it answers. A filename
constrains that part, while another part can use evidence from another file.
For a singular ambiguous request such as “the contract” when multiple contract
files are indexed, the app asks for a filename. Cross-workbook BOQ answers show
per-file subtotals and exact cells; currencies are never converted or mixed.
The displayed answer is assembled from the claims that pass these checks;
unsupported claims are omitted and counted. Malformed JSON falls back to
retrieved source excerpts, clearly labeled unverified.

For example, a final prose response has this shape (the `answer` field is
recorded but the UI renders the individually checked claims):

```json
{"answer":"Four circuits passed; two need retesting.","insufficient":false,
 "claims":[{"text":"Four circuits passed.","question_part":0,"supports":[
   {"citation":"Report.pdf | page 1 | chunk 0",
    "quote":"Four circuits passed and two circuits require retesting."}]}]}
```

The UI distinguishes **deterministically verified** exact source wording or
Python BOQ calculations, **evidence-linked** paraphrases whose interpretation
Python cannot prove, and **unverified** missing or contradictory support.
An authentic quote does not make its interpretation true. Changed amounts and
explicit conflicting decisions can be rejected, but a role reversal using the
same words may still be evidence-linked and needs human review. Python marks
only exact source wording and deterministic calculations as verified. A
truncated search is a coverage warning for exhaustive questions; a successful
retry clears an earlier tool error. Unreadable files remain visible as coverage
limits. Repeated tool calls are cached and bounded. No second model call is
made solely to verify a draft answer; a provider emitting invalid JSON may
receive one format-only generation retry.
Tool responses sent to models use compact previews while verification retains
the full local index. Groq and other compatible providers retry one HTTP 429
only when its `retry-after` delay fits the bounded request budget; otherwise
the app displays a provider-specific wait message without the raw API error.

OpenAI Chat Completions uses a strict JSON schema for the response. If that
format is rejected by the chosen OpenAI model, the generation request is
retried once with instructed JSON and the fallback appears in the audit trail.
Gemini, Groq, Ollama Cloud and other compatible endpoints use the same instructed JSON
contract with local schema and provenance checks; model support varies. The
old `semantic_verifier.py` is retained for experimental tests and is not in the
active provider request path.
Ollama states that its cloud API currently lacks enforced structured outputs
([official documentation](https://docs.ollama.com/capabilities/structured-outputs)).
Malformed cloud JSON can therefore still occur; the app retries answer
generation once, then shows indexed excerpts as unverified if parsing fails.

### Choose a provider and model in Streamlit

The **AI model** section in the Streamlit sidebar has a **Provider** dropdown and a
**Model** dropdown. You can switch between Gemini, Groq, Ollama Cloud, OpenAI, or a
custom OpenAI Chat Completions-compatible service without restarting the app.
The model dropdown offers the model configured in your local `.env`, a documented
default to try (availability depends on your account), and **Other model ID**
for an exact model name. Switching providers/models clears the previous response.
The selected provider/model are passed to each question; the app does not rewrite
environment variables or disclose your API keys.

Add the corresponding `*_API_KEY` (and a compatible base URL, where required)
to your local `.env` before selecting a provider. A provider without its key
is shown but the **Ask agent** button remains disabled. For Groq, Ollama Cloud,
OpenAI and other compatible APIs, install the optional client:
`python -m pip install -e ".[openai,dev]"`.
The Streamlit sidebar reflects configured model IDs, but it cannot guarantee
that a particular account can call them. Test real function calling using
`syden-agent smoke --provider <provider>` or a real question.

For OpenAI as provider, install `pip install -e ".[openai,dev]"`, set `LLM_PROVIDER=openai`
and `OPENAI_API_KEY` in `.env`.

For **Llama through Groq**, install `pip install -e ".[llama,dev]"`, then set
`LLM_PROVIDER=groq` and `GROQ_API_KEY` in `.env`. The default Groq Llama model ID is
`llama-3.3-70b-versatile`; verify it is available for your account before the demo.
This is a hosted Llama API, not Ollama running locally.

For another OpenAI Chat Completions-compatible provider, use `LLM_PROVIDER=compatible`
and set `COMPATIBLE_API_KEY`, `COMPATIBLE_MODEL`, `COMPATIBLE_BASE_URL`.
Provider feature parity is **not** guaranteed: test custom tool calling with the exact model
and SDK before relying on it in the live interview.

For **Ollama Cloud direct API**, install `pip install -e ".[openai,dev]"`, set
`LLM_PROVIDER=ollama_cloud`, `OLLAMA_API_KEY`, and `OLLAMA_MODEL` in `.env`.
The adapter uses the [documented](https://docs.ollama.com/api/openai-compatibility)
`https://ollama.com/v1` Chat Completions endpoint.
Ollama documents API-level tool support. The example model `gpt-oss:20b-cloud`
passed a real synthetic tool-call smoke test with the provided account; check your
own configured model before a demo.

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
- Groq-hosted Llama and OpenAI have not been live-tested with accessible models/keys.
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
