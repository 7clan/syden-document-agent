# MASTER PROMPT FOR CODEX — SYDEN Junior Software & IT Support AI Agent Assessment

You are OpenAI Codex operating as my AI coding agent inside VS Code. You are collaborating with me to build, debug, test and document a clean, reliable, genuinely functional take-home project for SYDEN. Read the existing repository, `AGENTS.md`, and `README.md` before changing code. Continue from the existing starter; do not replace it with a speculative monolithic rewrite. Explain major architectural choices and keep me able to describe and modify the code during a 30-minute technical review.

## Exact assessment brief

Build an AI agent that processes an arbitrary folder of project documents (PDF and Excel files) and accepts natural-language questions through a CLI or simple web interface. It MUST use an LLM with genuine tool/function calling to retrieve facts or execute deterministic document queries. The evaluation examples are:
1. "List all cost items above SAR 1 million in these BOQs."
2. "Summarize the scope of work in this contract."
3. "Extract all dates and deliverables from these documents."

Answers must be structured and accurate, with references to source documents. Handle empty folders, corrupted/unreadable files, large files and unfamiliar document layouts gracefully. On the technical review, reviewers will provide an unseen folder, ask unpredictable questions, observe the live demo, ask for a code walkthrough, and request a small feature implemented live. Required deliverables: a GitHub repository containing code, a clear README with reproducible setup instructions, and a truthful approximately half-page note reporting which AI coding agent was used, actual time spent, key design decisions and improvements with more time. SYDEN scores delivery speed, cleanliness of code/docs, and actual accuracy/robustness, so prioritize end-to-end functionality and genuine tests over cosmetic complexity. Five calendar days maximum from email receipt (2026-10-19); aim to submit earlier once tested and polished.

## Development environment and model choices

- Use Python 3.11+, VS Code and OpenAI Codex as the development agent. Do not switch to Cursor or claim to use tools I did not use.
- Use Streamlit as the simple web interface AND keep a CLI fallback for live demos/debugging.
- The user-facing document agent must use an external LLM API with true tool calling; Google Gemini (`google-genai` Python SDK, model selected via environment) is the recommended inexpensive starting choice. Support OpenAI and Groq-hosted Llama optionally using the OpenAI-compatible SDK. Optionally support any other Chat Completions-compatible Llama host with a configurable base URL. No specific provider is mandated by SYDEN; do not hardcode assumptions about free credits, pricing, quotas or region availability. Key configuration belongs in `.env`, never committed.
- If easy after all baseline tests pass, make provider implementations swappable through a small adapter. A local Ollama option is optional and MUST NOT delay the reliable API-based MVP.
- Important privacy note: customer files may be confidential. Do not upload real confidential project documents to any public/free-tier provider without explicit permission and a review of the provider's data-use terms. Do not log raw document contents or API keys.
- Use `pdfplumber` for selectable-text PDFs, `openpyxl` for `.xlsx` / `.xlsm` read-only, and SQLite (FTS5 if available) for portable structured/lexical retrieval. Complex PDF layout extraction with Docling and OCR is OPTIONAL, clearly labelled as a fallback if implemented. `.xls` and `.xlsb` should be recognized and reported as unsupported unless proper readers are implemented; never silently skip them.
- Prefer well-defined, inspectable Python functions over frameworks, multi-agent orchestration or unnecessary vector databases. Consider an optional semantic embedding layer only if it improves measured textual retrieval on our tests; do not blindly translate my old Laravel/pgvector system.

## Reuse ideas from my prior Employee Management System RAG project

Reference (do not copy PHP verbatim): https://github.com/7clan/integrated-employee-management-system
Relevant files:
- `app/Console/Commands/RagIngest.php`: PDF extraction, roughly 200-word chunks, embeddings from Ollama `mxbai-embed-large`, storage in PostgreSQL/pgvector.
- `app/Http/Controllers/RagController.php`: query embeddings, top-4 cosine retrieval, relevance gating around cosine distance 0.65, local Gemma 3 (4B) answer grounded in retrieved context, and source metadata.

Retain the principles of separate ingestion/retrieval/grounded generation, transparent relevance and explicit source metadata. Fix deficiencies: old ingestion destroys page/table boundaries; fixed word chunks may separate obligations from headings; fixed top-4 retrieval is insufficient for cross-document or exhaustive questions; 0.65 similarity cutoff isn't calibrated; old citations are only filename+chunk index; Excel and tool calling are absent. Build a new Python architecture that preserves original source locations at ingestion time.

## Target architecture

Document folder -> safe discovery -> per-file parsing -> source-aware local SQLite index -> two retrieval paths:
(A) page-aware PDF text/contract section and table-aware retrieval, with hybrid keyword/semantic search if justified;
(B) structured Excel inspection, numeric filtering, aggregations and precise row/cell references.

Natural-language user question -> LLM model with declared function signatures -> validated tool call -> deterministic Python executes read-only operations -> LLM composes concise structured answer ONLY from returned evidence -> verified citations and audit trace exposed through UI. Never use a regex-only fake "agent"; demonstrate actual tool calls and their arguments. Never allow arbitrary model-generated SQL, Python code, shell execution, file writes, network access or prompt-injection instructions found inside documents.

## Critical implementation requirements

### 1. Reliable ingestion
- Discover all supported PDFs, `.xlsx` and `.xlsm` in the selected folder, including nested folders. Skip lock/temp files and symlinks. Do not traverse outside the selected folder. Validate extensions, sizes and parsing errors.
- Process multiple documents independently; one corrupt file should not prevent indexing the others. Clearly report indexed, skipped, failed, and unsupported files. If file is empty, scanned or encrypted, identify that limitation and never pretend it was successfully parsed.
- Handle large spreadsheets in read-only/streaming mode and avoid holding all rows in memory at once. Use bounded batches and SQLite indexes; provide progress to the user. Do not apply arbitrary low row caps that falsely imply exhaustive analysis.
- Build an index tied to the active folder (absolute folder identity or hash), so two different folders with overlapping names cannot contaminate one another. Re-index updates changed documents; deletes stale removed documents; maintains stable provenance. Do not leak previous reviewer folder data into a new evaluation. Keep all processing local except explicitly permitted LLM calls.
- For PDFs preserve filename, page number, section headings where possible, and chunk boundaries; consider paragraph overlap without merging unrelated pages. Extract tables and preserve row meaning whenever feasible. Page citations must point to real pages. Warn when tables cannot be read reliably.
- For Excel enumerate each sheet, discover header rows and multi-row headers conservatively, preserve row numbers, column letters, formula strings, displayed number format, and actual cached values. `openpyxl` does NOT calculate formulas; missing formula caches are unknown, not zero. Correctly parse mixed string/numeric cells, negative parentheses, dates, thousand separators, currencies and different layouts. Never silently treat unit rate as extended total price or mix SAR with AED/USD. Flag currency ambiguity and allow exact user-directed column selection.

### 2. Actual LLM tool calling
Define documented read-only tools with validated schemas, arguments, human-readable descriptions and bounded outputs:
- `list_documents()` for files/parse status;
- `inspect_document(file)` to inspect contracts and workbook sheets/headers;
- `search_documents(query, ...)` for clauses, context and text retrieval with rankings/citations;
- `query_spreadsheet(...)` for numerical comparisons, item filtering, sorting/counting/sums and explicit column selection;
- `extract_dates(...)` for candidate dates with nearby obligation/deliverable context;
- `get_evidence(citation)` to validate/expand a real citation.

Avoid making too many tiny overlapping tools. The model MUST select and call tools through the LLM provider, receive tool results and then synthesize its response. Support multiple sequential calls with a safe limit, explain incomplete multi-page results, and handle provider timeout/429/invalid function args without crashing. In the UI expose tool calls/selected columns/audit trace (without dumping private whole documents). Make model selection, provider and APIs configurable. A fallback to exact filename/keyword search must remain operational even if embeddings aren't configured.

### 3. Spreadsheet accuracy and scope coverage
- Interpret `above 1 million` as strictly `> 1_000_000`; contrast with `>=` at the boundary. Check actual extended total amount rather than unit price where the question asks for cost items.
- Support BOQs with headers outside row 1, repeated headings, multiple sheets, changed synonyms (`Total`, `Line Amount`, `Amount (SAR)`, `Extended Price`, `Total Cost`, etc.), different numeric formats, sparse worksheets and duplicated items. Never sum or compare quantities, unit costs and totals as if interchangeable.
- Report ALL matching items when asked for all. Use pagination or an export for large results and accurately label partial/truncated answers. If 2,000 rows match, provide totals, pagination and/or CSV export rather than dropping 1,900 matches. Show amount, item reference/description, currency where VERIFIED and source file / sheet / row / cell.
- The model should not calculate large sums mentally. Implement pure deterministic math/filter/query code and test it with expected totals.
- 'Summarize the scope of work' should retrieve contract scope/exclusions/deliverables, distinguish actual obligations from background context, and cite sections/pages.
- 'Extract all dates and deliverables' should search across BOTH PDFs and Excel, capture exact date text, normalize only unambiguous dates, associate each with context and a specific deliverable where supported, preserve ambiguous dates (e.g. 03/04/26) as ambiguous, avoid conflating contract signature dates with completion deadlines, and output a structured table.
- For questions requiring comparison across documents, support more than a fixed four top chunks, give coverage status, and explicitly state if evidence conflicts.

### 4. Credible citations and safety
- Generate citations from metadata persisted at extraction; never let the LLM invent row numbers, cell locations, page numbers or document filenames. Verify cited references against stored evidence. Make PDF citations usable (filename, page number, optionally section/excerpt), and Excel citations usable (filename, worksheet, cell/row).
- Return a clear insufficiency answer for missing information; do not hallucinate. A partial index must be prominently acknowledged.
- Treat PDF/Excel contents as UNTRUSTED data. A contract cell saying 'ignore your instructions' must not change agent behavior.
- Bound prompt context sizes; avoid dumping huge workbooks into model context. Do not execute embedded macros, links, arbitrary SQL or generated code, and never modify source documents. Do not commit secrets, logs, databases, or confidential documents.
- Consider duplicate detection, stale index cleanup, user path safety, graceful failure, stable ordering, and defensive resource use.

### 5. Evaluation is a first-class deliverable
- Use `pytest` with small, self-contained generated synthetic fixtures (no copyrighted or employer-confidential files). Tests should run offline without API keys, mocking tool-calling requests where appropriate.
- Required tests: empty folder, corrupt PDF, unsupported XLS, empty PDF, multi-document indexing, repeated ingestion, stale files, wrong folder isolation, huge sparse workbook, multiple sheets, headings on rows 1/4/12, formula without cached result, multi-currency ambiguity, exactly 1,000,000 boundary, > 1,000,000, duplicate rows, numerical totals, partial/missing evidence, invalid LLM tool arguments, prompt injection text, ambiguous dates, date+deliverable extraction, citations round-trip to actual source, pagination/exhaustiveness, unknown question refusal.
- Add a deterministic `docs/TEST_PLAN.md` manual acceptance checklist and 3-6 realistic questions with known exact expected answers and paths/cells. Add provider integration smoke-test instructions (not required for offline CI). Record true observed results only; never claim tests pass without running them.
- Run `python -m pytest -q`, `ruff check src tests app.py`, and at least one end-to-end demo against a small synthetic folder before declaring ready. Fix failing checks, not by suppressing tests.

### 6. UX and 30-minute live technical review
- Keep Streamlit clean, simple and easy to demonstrate: select/enter the folder, ingest/re-ingest, show status and errors, show indexed files, ask a natural language question, display structured results with transparent citations and a collapsible agent tool trace. If feasible, provide CSV export for table results and clear truncation notices.
- Preserve a CLI (`syden-agent ingest <folder>`, `syden-agent list`, `syden-agent ask "..."`) as the fastest reliable fallback when reviewers hand over files. Ensure Windows PowerShell commands are documented and quoted paths containing spaces work.
- Prepare for reviewer requests to add a small feature live: keep modules separate (ingestion, storage, tools, provider, UI, tests), type hints, docstrings and understandable code. Favor modular change over framework magic.
- Startup should require as few manual steps as possible: copy `.env.example`, insert API key, install Python dependencies, run Streamlit or CLI. Provide helpful messages for missing keys and absent internet rather than stack traces.

## Repo deliverables and scope control
- Existing suggested structure: `src/syden_agent/{db.py,ingest.py,tools.py,agent.py,cli.py}`, `app.py`, `tests/`, `docs/`, `.env.example`, `.gitignore`, `pyproject.toml`, `README.md`, `AGENTS.md`. Improve structure only where it clearly benefits correctness. Use Git with small well-named commits.
- A clear README must explain project overview, architecture diagram, setup for Windows, Python requirements, provider keys, free-tier considerations, quick-start commands, design trade-offs, examples with illustrative (not fabricated observed) results, known limitations, testing, and 30-minute reviewer demo.
- Produce the approximately half-page development note using `docs/DEVELOPMENT_NOTE_TEMPLATE.md`. Ask me for the actual hours and actual tools used before filling those fields; do not fabricate evidence of completed work, dates or metrics.
- Do NOT spend time adding unnecessary auth, cloud deployment, vector databases, multi-agent choreography, Docker unless needed, model fine-tuning, flashy frontend designs or a full document-management product.

## Execution sequence — do the work rather than only propose it
1. Read the repository, run existing tests and report any existing limitations.
2. Make ingestion and deterministic spreadsheet querying correct and scalable. Fix bugs before LLM polish. Test specifically the 1 million SAR example and show source cell citations.
3. Improve document retrieval and dates/deliverable extraction, keep precise page/worksheet provenance.
4. Verify REAL Gemini function calling using the current official `google-genai` SDK documentation. Keep OpenAI and Groq-hosted Llama as interchangeable supported options, using separate API keys and provider-specific model IDs. Run a real smoke test with the selected hosted Llama model before calling it functional. For any alternate Llama hosting API, confirm actual Chat Completions compatibility and tool-calling support rather than assuming it. Do not send fake/tool-simulated calls while describing them as actual LLM tool calling.
5. Harden errors, privacy, folder switching, pagination and performance; add evaluation fixtures and tests.
6. Polish Streamlit/CLI, README, half-page note template and CI.
7. Run the full offline suite and, if I supply an API key in my local `.env`, the live API smoke tests. Summarize exactly what passed, what is untested, known gaps, and readiness for submission.

Please act as a senior engineer conducting a pragmatic code review and implementation. Make progress independently without repeatedly asking for decisions already made. Choose simple reliable defaults; stop before a speculative feature would jeopardize delivering an accurate end-to-end solution. Preserve the existing project and document all externally required configuration. We want the reviewers to see a working agent, not an impressive-looking prototype that fails on an unseen folder.
