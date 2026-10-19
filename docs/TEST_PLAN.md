# Acceptance test plan and observed results

| Scenario | Expected acceptance criterion | Actual result |
| --- | --- | --- |
| Empty folder | Clear warning, no hallucinated files | Covered by offline test; manual review pending |
| Corrupt PDF + valid XLSX | PDF reported failed, Excel remains searchable | Corruption isolation covered by offline tests; exact pairing pending manual review |
| All BOQ items > SAR 1M | Excludes exactly 1M; includes all >1M; cites sheet/cells | Passed offline and live Gemini on synthetic demo |
| Two BOQs with different header rows | Finds correct total amount columns in both sheets | Covered by multi-sheet/repeated-header offline tests |
| Different currencies | Does not assume all numbers are SAR | Covered by XLS/XLSX mixed-currency offline tests |
| Scope summary | Only sourced obligations/exclusions, precise pages | Not run manually |
| Dates + deliverables | All candidate dates, real deliverable associations, no invented deadlines | Not run manually |
| Scanned document | Explicit limitation or OCR fallback | Empty-text PDF reported failed in offline test; OCR absent |
| Large workbook | No OOM; good performance; no silently lost matches | 5,000-row synthetic workbook passed; larger unseen files pending |
| Switch document folders | Old folder's records cannot affect new answer | Covered by offline test |
| Prompt injection in PDF/Excel cell | Instructions inside data ignored | Not run manually |
| Legacy XLS/XLSX equivalence | Numeric filters, repeated headers, dates, cached values and cell citations agree | Covered by synthetic offline tests |
| Word paragraphs and tables | Ordered blocks, resolvable references, dates and cross-document search | Covered by synthetic offline tests |
| Corrupt/empty XLS and DOCX | Each file fails independently; valid files remain searchable | Covered by synthetic offline tests |
| Separate amount/currency columns | SAR row retained; AED row excluded in XLSX and XLS | Covered by synthetic offline tests |
| Numeric year and merged/repeated headings | Both SAR amounts found at original cells | Covered by synthetic offline tests |
| Formula without cached value | Known row returned; unknown cell and incomplete warning reported | Covered by synthetic offline tests |
| PDF BOQ table and borderless lines | Page/table/row or page/line citation; uncertain lines warned | Covered by independent ReportLab fixtures |
| More than 100 dates | Correct total and offset pagination; month-first Nov date captured | Covered by synthetic offline tests |
| Unsupported prose with real citation | Fabricated budget rejected | Covered by synthetic offline test |
| Streamlit indexing/result display | No exception; verified BOQ table visible | Covered by headless AppTest |
| CLI ingest, list, BOQ and dates | Commands return expected JSON and citations | Covered by offline integration test |
| Source-only ZIP | No `.env`, documents, databases or generated metadata | Covered by offline ZIP test |
| Gemini live tool call | Inspect actual call trace and cited answer | Passed on synthetic corpus with `gemini-2.5-flash` |
| Groq live tool call | Inspect actual call trace and cited answer | Passed with `openai/gpt-oss-20b`; Llama models unavailable to this key |
| Ollama Cloud live tool call | Inspect actual call trace and cited answer | Passed with `gpt-oss:20b-cloud` |
| Fresh environment setup | Editable install and checks succeed in a clean Windows venv | `pip install -e '.[openai,dev]'` succeeded in `.local/fresh_venv`; CLI help, 55 tests and Ruff passed |

Do not mark rows passed until they have actually been executed and independently checked.

## Reproducible synthetic demo

Run `python scripts/create_demo.py` once from the repository root, then
`syden-agent ingest ".local/demo_documents"`. The script refuses to overwrite an
existing folder. These files contain invented project data, not employer documents.
The deterministic assertions are in `tests/test_demo_e2e.py`.

| Reviewer question | Exact expected evidence |
| --- | --- |
| List all cost items above SAR 1 million. | Transformers: SAR 1,500,000 at `BOQ.xlsx | Electrical BOQ!C2`; Switchgear: SAR 2,250,000 at `BOQ.xlsx | Electrical BOQ!C4`. Cable at C3 equals SAR 1 million and is excluded. Sum SAR 3,750,000. |
| What is the scope of work? | Install two transformers and commission the plant at `Contract.pdf | page 1 | chunk 0`. |
| What is excluded? | Civil excavation at `Contract.pdf | page 1 | chunk 0`. |
| Which dates and deliverables appear? | Design drawings by 15 November 2026 at `Contract.pdf | page 1 | chunk 0`; commission plant 2026-12-01 at `Milestones.xlsx | Milestones!B2`. `03/04/26` at B3 remains ambiguous and should not be called a definite deadline. |

Observed locally before optional format support: `python -m pytest -q` passed all 24 offline tests.
After adding XLS and DOCX support, `python -m pytest -q` passed all 31 offline tests and
`ruff check src tests app.py scripts` passed on 2026-10-19. These format tests use synthetic files;
no real confidential documents or live provider calls were used for the new formats.
CLI ingestion of the generated folder reported 3 indexed, 0 failed.
On 2026-10-19, live synthetic smoke checks passed with Gemini `gemini-2.5-flash`,
Groq `openai/gpt-oss-20b`, and Ollama Cloud `gpt-oss:20b-cloud`. Gemini answered
all three assessment questions on the synthetic folder with correct source
locations. Groq and Ollama Cloud produced correct numeric tool results for the
BOQ question, though their prose used typographic hyphens in item codes. The
Groq account listed no Llama chat model; two Llama model IDs returned 404.

## Audit remediation verification (2026-10-19)

The new audit fixtures are in `tests/test_audit_regressions.py` and
`tests/test_audit_agent.py`. They include independently generated ReportLab PDFs,
5,000 spreadsheet rows, both Excel formats, mixed currencies, missing formula
caches, ambiguous dates, and claim-verification checks. Live synthetic smoke
tests were rerun with Gemini, Groq `openai/gpt-oss-20b`, and Ollama Cloud
`gpt-oss:20b-cloud`; each made an actual document tool call and passed the
stricter smoke criterion. A live Gemini BOQ question called `query_spreadsheet`
and returned SAR 1,500,000 at C2 and SAR 2,250,000 at C4, excluding the
SAR 1,000,000 boundary row and summing to SAR 3,750,000. These live calls used
only invented demonstration documents. OpenAI and Groq-hosted Llama remain
untested with this account.

After the audit fixes and an explicit row-currency precedence test, a clean
Windows virtual environment passed all 55 offline tests and Ruff. The three
provider smoke tests were rerun against synthetic text after the numeric and
date answer changes. Each returned `success: true` with a real document tool
call. This verifies the configured models, not all models offered by each host.
The final live Gemini BOQ check returned two SAR rows (C2 and C4), a SAR
3,750,000 sum, and no false incompleteness warning from the unrelated
`Milestones.xlsx` workbook. Its trace included `query_spreadsheet`.

## Evidence-first claim refactor (2026-10-20)

The provider answer path now asks for one JSON answer with claim-level source
quotes. Local checks verify quote/citation integrity and comparable facts;
paraphrases are labeled evidence-linked rather than semantically proven.
The final answer is rendered from validated claims. No second provider request
is made solely to verify wording. `tests/test_claim_verifier.py` covers word
versus digit counts, wrong amounts/currencies/dates/identifiers, false quotes,
negation, approval status, conflicting sources, multiple passages, wrong file,
malformed output, and tool failures. The offline suite passed 159 tests with
1 skipped after these additions. The three-case acceptance check in
`test_claim_verifier.py` had 0 false accepts and 0 false rejects; this is a
small synthetic regression set, not a real-world accuracy estimate.
The OpenAI mock also verifies a single schema-rejection retry using instructed
JSON, with no verification-only request.

Live synthetic Groq and Ollama Cloud smoke checks produced structured answers
and actual document tool calls. Gemini was not confirmed for this refactor:
the configured model returned 503 due to high demand; an older Lite model
returned 404, and the provider-suggested Lite model returned 503. These are
provider responses, not passing application checks. OpenAI remains untested
without a key. Test the chosen model again before a live demo.

## Verification hardening before PR #1 merge (2026-10-20)

The claim verifier now checks numbers, dates, status words and negation in the
relevant clause rather than across the whole quotation. Clear sentence,
semicolon, contrast and repeated-subject conjunction boundaries are split;
ambiguous relationships are omitted as unverified. Retrieved evidence about
the same identifier is checked for conflicting decisions and comparable dates
or quantities. Filename restrictions use full-name matching, including nested
file basenames and multi-file questions, rather than substrings.

`tests/test_claim_verifier.py` includes adversarial acceptance and rejection
cases for opposite decisions on two records, swapped quantities and dates,
unrelated negation, cherry-picked cross-document citations, filename suffix
collisions, mixed-case names with spaces or punctuation, and quotes that share
only a noun with an unsupported conclusion. They also check that one record
can have different decisions for distinct subjects without a false conflict.
An unknown explicitly named file cannot borrow another file's citation.
A correct paraphrase remains evidence-linked; exact source wording remains
deterministically verified.
These synthetic cases do not measure accuracy on unseen project documents.

## Scoped provenance architecture check (2026-10-20)

`tests/test_architecture_correction.py` uses fictional PDF, Word, and Excel
evidence to check locally resolved character spans, optional exact quotes,
question-part filename scope, numeric and decision conflicts, a successful
tool retry after an error, nonexhaustive search truncation, ambiguous singular
filenames, repeated tool calls, one optional malformed-JSON generation retry,
per-workbook subtotals, and financial PDFs unrelated to BOQs.

The four explicit comparable-fact cases in that file had zero false accepts
and zero false rejects. A separate adversarial role-reversal claim remains
**evidence-linked** even though its interpretation is wrong: provenance and
shared words cannot prove who performed the action. Treat evidence-linked
answers as requiring review. These five cases are a small regression set,
not an accuracy benchmark.

Live requests against the fictional demo and a newly generated isolated
PDF/DOCX/XLSX corpus produced these observations:

| Scenario | Before correction | After correction |
| --- | --- | --- |
| QA counts, Gemini | Dropped the correct four-passed claim | Four passed and two retesting retained with PDF spans; evidence-linked, 15.0 s |
| CO-07 revised sum, Groq | Correct amount rejected or called incomplete | SAR 7,070,000 retained with PDF page and local span; evidence-linked, 10.0 s |
| PDF plus Word question, Gemini | Valid PDF claims rejected when question named Word file | All three facts retained across both documents; exact source wording, 16.5 s |
| QA counts, Ollama Cloud | Passed once, then two malformed JSON responses during correction | Both counts retained with PDF spans on a later run, 8.7 s; output format remains variable |
| Unfamiliar workbook, Ollama Cloud | Correct two cells and SAR 2,750,000 | Same deterministic result, 13.7 s |
| Ambiguous singular contract | Groq silently chose one contract | CLI asks which indexed contract file is intended |
| All demo BOQs | Correct SAR 11,004,500, but unrelated PDF warnings | SAR 11,004,500; separate workbook subtotals SAR 6,254,500 and SAR 4,750,000; no warnings |

Two final Groq calls encountered HTTP 429 token-per-minute limits. The
previously slow Groq BOQ and missing-detail cases therefore could not be
retested after correction; this is a provider quota result, not a passing
application check. OpenAI remains untested with a live key. Provider-internal
request and token totals are not instrumented, so latency is per CLI invocation
and may include several normal tool-calling rounds. No second semantic
verification request is used. The optional JSON retry is generation-only and
is bounded to one additional request.
