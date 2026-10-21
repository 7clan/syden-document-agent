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

## Structured schedule evidence and Groq context check (2026-10-20)

The first live Gemini rerun of the five-milestone question stopped after six
tool rounds. `inspect_document` showed the rows but did not provide copyable
row citations; the model tried two unsupported citation formats and two
financial `query_spreadsheet` calls, both with zero matches. After adding exact
row citations to inspection previews and clarifying each tool's purpose, a
second live Gemini run returned all five activities, dates, classifications,
and approval statuses with the correct `05_Project_Schedule.xlsx | Milestones |
row 2` through `row 6` references. All five claims were evidence-linked and
none was rejected. The run took about 9 seconds and used `list_documents`,
`inspect_document`, and five `get_evidence` calls. It did not call
`query_spreadsheet` on the schedule.

The new offline structured-row cases cover combined-column paraphrases,
swapped dates, approval and classification conflicts, a description copied
from a different row, repeated headers, reordered columns, `.xls` citations,
and strict Word quotes. Provider tests check bounded one-time 429 retry,
`retry-after` parsing, safe messages, duplicate search-result suppression,
and compact model previews. These tests use mocked rate-limit responses;
the retry path has not been observed on a live 429.

One real Groq synthetic smoke attempt used `search_documents` and
`get_evidence` and returned the correct ORCHID-7429 fact, but the smoke
command reported `success: false` because the model added an unsupported
tool-action claim. It was omitted from the final answer, so this is not a
passing provider smoke test. No live 429 occurred on this attempt. Model
availability and rate limits remain provider and account dependent.

## Grouped milestone regression (2026-10-20)

The Streamlit Groq result for “Which milestones are contractual and which are
unapproved planning dates?” omitted two otherwise cited grouped claims. The
verifier required every row to contain every ID in a multi-row list. The
regression now checks that each claimed ID is covered by its own cited row and
that a shared property agrees with every row. Missing rows, wrong-status rows,
and swapped per-record dates are rejected. Against the indexed synthetic
`05_Project_Schedule.xlsx`, the exact two grouped claims are now retained as
**evidence-linked**, with row 2–6 citations. This is an offline validation of
the displayed claims, not a successful new live Groq answer.

One live Groq retest returned HTTP 429 with an 11-second suggested wait. A
single retry after that wait returned another 429 with a 21-second wait. The
application showed friendly rate-limit messages instead of raw API errors.
No further provider calls were made; live Groq answer quality after this fix
remains unverified. No new semantic-verification model request or new class of
wording rules was added.

## Unseen Sable corpus and active verifier removal (2026-10-20)

Four newly generated fictional documents were indexed in an isolated, ignored
`.local/unseen_sable_20261020_v1/documents` folder: a two-page contract PDF, a
change-notice PDF, an XLSX BOQ with row-4 and repeated headers, and a legacy XLS
gate register. All four indexed successfully. The independent BOQ query found
EL-41 and EL-42 at `Sable_BOQ.xlsx | Base Prices!E5` and `!E6`, strictly above
SAR 1,000,000, totaling SAR 2,350,000. The SAR 1,000,000 boundary row was excluded.

Before removing active claim checks, Gemini answered the PDF scope/date and BOQ
questions correctly. It also answered a two-PDF contract/change question
correctly. Gemini and Groq both retrieved the right legacy XLS rows and gave
the right two dates, but the verifier omitted their combined-date claim because
each cited row contained only one date. This was a false rejection on new data.
Groq's first PDF run exhausted six tool rounds; its BOQ attempts returned one
HTTP 400 `output_parse_failed` and one HTTP 429. Those were separate provider
failures, not verifier rejections.

The live provider path now displays model claims with retrieved citations and
original indexed text/cells. It no longer calls `validate_claims` or checks
model prose against row values. On retest, both Gemini and Groq gave complete,
correct XLS gate/date answers with row 4 and row 5 citations. Groq also gave a
complete, correct two-page PDF scope/exclusion/date answer. A final Groq BOQ
attempt still returned HTTP 400 `output_parse_failed`; Groq financial live
success is **not verified**. The deterministic BOQ result and Gemini BOQ run
passed. These results are a small live sample, not a guarantee on arbitrary
documents. Source-linked model claims can still be factually wrong even when
their cited locations exist; the interface labels that distinction explicitly.

## Groq parsing and model discovery check (2026-10-20)

The attached Streamlit trace showed a Groq HTTP 400 `output_parse_failed` on a
tool-capable date-question continuation. Its `failed_generation` was planning
text. The API error did not identify whether the model was attempting another
tool call or a final answer, so the failure is classified by request mode rather
than guessed from that unparsed text. A pre-change live reproduction of the same
question succeeded in two Groq requests; the error is intermittent. The revised
path retries at most once with compact indexed evidence, can force a needed tool
call, and uses Groq strict JSON schema only for a tool-free final response.
Offline tests simulate tool-call parsing failures, final-response parsing
failures, malformed tool arguments, a second failed retry, other HTTP 400s,
429 separation, strict JSON, a contract citation, and deterministic BOQ results.

One post-change live Groq `openai/gpt-oss-20b` date query used `extract_dates`
and two `get_evidence` calls, then returned a cited, evidence-linked answer
distinguishing contractual deadlines, planning targets, and other dates. The
next live Groq contract question received HTTP 429 with an approximately
1,369-second retry suggestion. No further Groq generation calls were made.
A Gemini `gemini-3.5-flash-lite` contract-scope check then searched six times
and returned insufficient evidence despite the local index containing the
scope passage. That is an observed model-orchestration false refusal; it is not
counted as a passing contract test. The offline deterministic BOQ query on
`04_Electrical_BOQ.xlsx` returned three SAR rows above 1,000,000 at cells F2,
F3, and F6, totaling SAR 4,335,000. These two checks do not establish live
Groq success for those questions.

One live model-list request through the new discovery code returned three
Groq text/tool models: `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, and
`qwen/qwen3.8-27b`. Ollama Cloud returned 22 models with both `completion`
and `tools`, including the seven requested families. These are advertised
capabilities and exact direct API IDs, not a live tool-call test of every model.
One additional synthetic smoke test used the discovered direct Ollama ID
`gpt-oss:20b`: it called `search_documents` and returned the fictional
ARBOR-17 code with an indexed PDF citation in about 8 seconds. Other listed
Ollama models remain untested for actual tool-call reliability.

## Indexed evidence handoff and provider diagnostics (2026-10-20)

An observed Ollama GPT-OSS 120B answer falsely said an approved change order
contained no revised sum, although the indexed PDF stated SAR 7,070,000. The
previous model-facing search preview showed only the first 360 characters and
suppressed a citation when a later search found it again. Search now shows a
query-relevant excerpt on every new search, while an exact duplicate call remains
cached. The next model request also receives bounded original indexed text for
search and inspection citations without requiring a model-selected `get_evidence`
call. If a model reports insufficiency after retrieval, one answer retry receives
indexed evidence. A persistent absence response remains unverified, with candidate
source locations available for manual inspection. This is an evidence delivery
fix, not proof of semantic correctness.

The offline regression uses identical synthetic main-contract and change-order
records. A simulated GPT-OSS sequence searches twice, omits `get_evidence`,
incorrectly reports no sum, then answers correctly after the bounded retry. A
simulated Gemma sequence calls `get_evidence`. Both see the indexed revised sum.
A persistent false absence stays unverified. Diagnostics tests check HTTP status,
sanitized error code, and request phase without provider body text.

Live comparison used the same two generated PDFs for each model:

| Provider/model | Seconds | Actual document tools | Revised sum visible in model context | Outcome |
| --- | ---: | --- | --- | --- |
| Ollama `gemma4:31b` | 7.0 | `search_documents` | Yes; 997 handoff characters, 2 citations | SAR 7,070,000, cited, evidence-linked |
| Ollama `gpt-oss:120b` | 6.4 | `search_documents` | Yes; 905 handoff characters, 1 citation | SAR 7,070,000, cited, evidence-linked |
| Groq `openai/gpt-oss-120b` | 6.8 | `search_documents`, `get_evidence` | Yes; 905 handoff characters, 1 citation | SAR 7,070,000, cited, evidence-linked |

The earlier Ollama false absence and Groq HTTP 400 were not reproduced in these
three live calls. This small sample cannot establish a false-refusal rate or
guarantee unseen document performance. Groq HTTP 400 code/phase display is
covered by mocked errors; no actual HTTP 400 occurred in this retest.

## Focused six-document acceptance and separate held-out run (2026-10-20)

The acceptance index contained exactly the six fictional files requested for
questions 9–11: three PDFs, two XLSX workbooks and one DOCX. Original values were
read from the source files and the local index, not inferred from answer status:
`04_Electrical_BOQ.xlsx` / `Electrical BOQ` has seven amount cells F2–F8 totaling
SAR 5,934,500; its separate `Change Order BOQ` has SAR 320,000 at F2;
`01_Main_Contract.pdf` page 2 states the original contract value of SAR 6,750,000.
The schedule's `Milestones` rows 2–6 contain M-01 through M-05, with rows 5 and
6 marked planning target and unapproved proposal respectively.

| Question | Gemini 3.5 Flash Lite | Ollama GPT-OSS 120B | Groq GPT-OSS 20B |
| --- | --- | --- | --- |
| 9: EL-103 above SAR 1m? | Pass: No, SAR 890,000 at F4; application numeric fallback recorded | Pass: No, SAR 890,000 at F4 | Untested: HTTP 429 on first attempted focused call |
| 10: BOQ subtotal versus original contract | Pass: Python compared SAR 5,934,500 with SAR 6,750,000; nine source locations | Pass: same values and result | Untested after rate limit |
| 11: contractual versus planning milestones | Pass: M-01–M-05 with rows 2–6 | Pass: M-01–M-05 with rows 2–6 | Untested after rate limit |

The prior Ollama model output had merged base and change-order sheets and cited
real cells. A real citation did not make that sum correct. The new comparison is
application-calculated from separately queried worksheet and PDF operands; its
audit event says `origin: application`, and its answer remains `evidence_linked`
to avoid claiming semantic certainty about source selection. Gemini's missing
numeric tool call now triggers a separately labeled application fallback.
Gemini's empty final answer after retrieval has one compact JSON recovery; an
empty recovery still returns no invented claim. The local offline suite passed
251 tests with 1 skipped and Ruff before publication.

Representative earlier questions were rerun: contract scope (question 2) and
the strict BOQ threshold and SAR 4,335,000 sum (question 8) passed on both
Gemini and Ollama. Ollama also answered the proposed handover status (question
12) and the contractual-versus-proposed dates (question 18); its answer to 12
did not restate the unchanged contractual date, so that answer remains partial
against the full expected text. The other 18-question rows were not rerun.

After the fixes, a separate ignored folder `.local/unfamiliar_final` was
generated with a new fictional contract PDF, two Excel registers and Word site
decisions. These files and values were not used to develop the fixes. Its
original-work sheet has three cost rows totaling SAR 2,160,000, a separate
revision sheet has SAR 90,000, and the PDF states an original contract sum of
SAR 2,480,000. The delivery sheet contains two contractual gates, one planning
target and one unapproved proposal. The five held-out questions checked the
contract/BOQ comparison, a strict SAR 1m threshold, gate classification,
approval of a proposed date, and original scope:

| Provider | Held-out result | Material limitation |
| --- | --- | --- |
| Gemini 3.5 Flash Lite | 5/5 correct against original sources | These five prompts do not estimate accuracy on arbitrary documents |
| Ollama GPT-OSS 120B | 4 correct, 1 partial | Scope answer omitted the PDF's quantities of two panels and 85 metres of cable |
| Groq GPT-OSS 20B | Not run | Account returned HTTP 429 on the focused acceptance attempt |

All generated files, local indexes and raw answer logs are under ignored
`.local/`; no credentials or source documents are committed. The held-out run
exposed no incorrect calculation, but an evidence-linked scope summary can
still omit facts. This evaluation does not establish complete coverage of
unfamiliar documents or prove arbitrary model interpretations.

## Fresh interview-brief exercise (2026-10-20)

A separate fictional folder was generated under ignored
`.local/interview_blind_20261020` with one contract PDF and two XLSX BOQs. Its
names, values, layouts and dates differ from the development fixtures. The three
questions below use the exact wording in SYDEN's brief and were sent through
the CLI to the configured real Gemini provider, one at a time. The resulting
answers were compared against the generated source files, not inferred from
their citation status.

| Exact brief question | Observed result | Real model-selected document tools |
| --- | --- | --- |
| List all cost items above SAR 1 million in these BOQs. | Pass: C-10 SAR 1,180,000, E-21 SAR 1,340,000, E-23 SAR 1,075,000; three matches, SAR 3,595,000. The SAR 1,000,000 boundary row was excluded. Exact amount cells E5, E6 and E8 were cited across the two books. | `list_documents`, `inspect_document`, `query_spreadsheet`, `get_evidence` |
| Summarize the scope of work in this contract. | Pass: two 250 kW pumps, foundation, 85 metres of cable, telemetry and acceptance package; also correctly reported the exclusions. Cited the contract PDF page 1. | `list_documents`, `search_documents` |
| Extract all dates and deliverables from these documents. | Initial answer found all five dates but clipped PDF context and omitted the spreadsheet status in its displayed summary. After a general date-presentation fix, a real retest showed IFC drawings 12 January 2028, FAT certificates 28 February 2028, commissioning/handover 30 June 2028, civil inspection planning target 15 May 2028, and unapproved proposed handover 15 July 2028, with PDF page and Excel cell references. Pass after the fix; status remains evidence-linked because candidate context does not prove contractual interpretation. | `extract_dates`, `list_documents`, `search_documents`, `inspect_document` on the retest |

Separate edge-case folders were indexed without an LLM request. An empty folder
reported `Folder is empty`, and asking a question returned `No readable documents
are indexed`. A corrupt PDF was marked failed; a subsequent question returned
the same safe no-readable-documents message. A 20,000-line XLSX indexed in about
7 seconds locally; the deterministic strict-threshold query returned all five
SAR 1,200,000 matches and their exact cells, for SAR 6,000,000 total. This
measures one large workbook and does not establish a general size or latency
guarantee for arbitrary PDFs or workbooks.

The fresh corpus exposed a presentation issue, so its dates retest is a
regression check rather than an untouched held-out measurement. No additional
provider or arbitrary employer documents were tested in this exercise.

## Harder unseen-folder interview exercise (2026-10-20)

Five new fictional documents were generated under ignored
`.local/interview_challenge_20261020`: a two-page contract, an approved
variation, an inspection report, and two XLSX workbooks. The spreadsheets have
a header on row 12, a repeated header, a separate approved-variation sheet,
an AED-only optional sheet, and a date register. Expected facts were checked
against the generated files: the three SAR items strictly over one million are
P-101 (SAR 1,300,000; E13), P-102 (SAR 1,235,000; E14), and C-201
(SAR 1,180,000; E5), totaling SAR 3,715,000. P-105 is exactly SAR 1,000,000
and must be excluded. The AED optional item must not enter a SAR result.

| Question | Live observation | Assessment |
| --- | --- | --- |
| Exact brief: list all cost items above SAR 1 million | Ollama Cloud called real document tools and returned the correct three cells and sum. Initially it falsely labeled coverage incomplete because an explicitly AED-only sheet existed. After a general currency-coverage fix, the same live question returned `deterministically_verified` with no warning. Gemini's attempt returned `provider_error` before an answer. | Ollama pass after fix; Gemini untested due request failure |
| Exact brief: summarize the scope of work in this contract | Ollama cited contract page 1 and correctly included two 180 kW pumps, 65 metres of header, SCADA alarms, and operation/maintenance manuals. | Pass, evidence-linked |
| Exact brief: extract all dates and deliverables | Ollama initially searched but never called `extract_dates`, so no date answer was shown. After a bounded, transparently application-initiated fallback, the live retest listed all nine indexed date occurrences with PDF pages or Excel cells. It did not explicitly repeat the inspection report's sentence that the proposed 15 October handover was unapproved. | Pass for candidate extraction; partial for date-status explanation |
| Did CM-02 authorize solar or extend handover, and was 15 October approved? | Ollama's first request returned HTTP 500. Its retry gave the correct yes/no facts, but cited the contract and variation for the 15 October approval claim; only the inspection report establishes that status. Source linking labeled the claim evidence-linked because the cited passages existed and were retrieved. Gemini's attempt returned `provider_error` before an answer. | Fail on citation relevance; provider errors recorded separately |
| What is the architect or consultant phone number? | Two Ollama attempts returned HTTP 500 during the tool phase. | Untested live; no answer was fabricated |

The configured Gemini model was reachable through the model-availability API,
but its two full answer requests failed with a safe generic diagnostic lacking
an HTTP status. This exercise does not establish the cause. Ollama's HTTP 500s
were also kept separate from answer-quality failures. The cross-document
mis-citation is a known architectural limit: checking that a passage exists and
was retrieved does not prove it supports every model claim. Another narrow
keyword or negation rule would not establish general factual correctness, so
the test records the failure and leaves source inspection necessary.

The fixes prompted by this exercise are general: an explicitly foreign-currency
amount sheet no longer makes a requested SAR query incomplete, while actual
row/header currency conflicts still warn; and explicit exhaustive date
questions receive one application-run `extract_dates` fallback when the model
omits the tool. The audit labels that fallback as application initiated. These
files and raw answers remain ignored under `.local/`, outside the PR.
The currency and date retests use this same corpus after the fixes, so they are
regression evidence rather than untouched held-out results.

## Final release exercise (2026-10-20)

The Streamlit server started on port 8502. Its health endpoint returned HTTP 200,
and 11 headless Streamlit AppTest cases covering document management, model
selection and source inspection passed. No browser automation was available, so
the visual click-through remains a manual demo step. The production `ask()` path
was called with real provider APIs and isolated SQLite indexes; an HTTP response
alone was not counted as a UI or answer-quality pass.

The isolated six-file folder contained exactly three PDFs, two XLSX files and
one DOCX. Gemini 2.5 Flash answered original contract scope, the SAR 1 million
BOQ threshold (EL-101, EL-102, EL-105; SAR 4,335,000), all 19 indexed date
occurrences, and the change-order/meeting approval question correctly against
the files. Its BOQ result used `query_spreadsheet`; the approval claims cited
the change order and the meeting paragraph separately. Groq GPT-OSS 20B passed
scope and the cross-document approval question with real search tool calls.
Ollama Gemma 4 31B passed scope; its separate approval attempt timed out.

A new, previously unused fictional interview folder was generated under ignored
`.local/final_unseen_20261020`: two PDFs, two XLSX workbooks and one DOCX.
The source files establish two 320 kW chillers, 90 metres of pipe, control panel
CP-7, and rooftop solar/landscaping exclusions. The base BOQ has CH-101 at
SAR 1,340,000 (E6), CH-102 at SAR 1,220,000 (E7), CH-103 at exactly
SAR 1,000,000 (E8), and CH-104 at SAR 700,000 (E9). Thus strict `> SAR 1m`
returns two items totaling SAR 2,560,000; the base subtotal and original PDF
contract sum are both SAR 4,260,000. CN-11 adds 35 metres of Annex C pipe and
SAR 275,000 without extending 30 June 2028. The proposed 15 July 2028
handover was not approved in the meeting minutes. These expected values were
checked against the generated source documents and CLI index, not the model's
verification label.

| Fresh interview question type | Ollama Gemma 4 31B observed result |
| --- | --- |
| Scope and exclusions | Correct, PDF page citation |
| All BOQ items strictly over SAR 1m | CH-101/E6 and CH-102/E7, SAR 2,560,000; deterministic result |
| All dates and deliverables | All 13 indexed occurrences; context shows contractual, planning and unapproved labels; source-linked candidate list |
| CN-11, solar, deadline and proposed-date approval | Correct three decisions; notice and meeting citations separated |
| Base BOQ versus original contract sum | Correct equality at SAR 4,260,000; Python checked the separate operands |
| Missing consultant phone/payment schedule | No invented detail; absence remains unverified, with inspectable candidate source |
| Exactly SAR 1m boundary item | Correctly says CH-103 does not exceed threshold; E8 cited |
| Independent Annex C quantity sources | Correct notice PDF, variation sheet row 2 and meeting paragraph 2 |

Other provider observations on the same new folder: Gemini 2.5 Flash passed
the BOQ calculation, then two subsequent attempts returned HTTP 429. Groq
GPT-OSS 20B passed scope/exclusions, then a BOQ request returned HTTP 429 with
an approximately 19-second retry suggestion. Gemini 3.5 Flash Lite passed the
six-file scope question, but its BOQ attempt failed before an answer and two
later tool-phase requests returned HTTP 504 `deadline_exceeded`. Ollama GPT-OSS
120B twice timed out at the client on the earlier cross-document challenge;
its answer quality after this change remains untested. The configured Groq
account listed GPT-OSS 20B/120B and Qwen, but no Gemma model, so a Groq Gemma
test was unavailable. OpenAI was not tested because no key was configured.

The earlier wrong-citation challenge was addressed by making explicit dates in
questions retrieve their matching indexed passages across documents and by
marking a cited claim unverified if its explicit date occurs in none of its
cited passages. This is a provenance guard, not a semantic approval verifier.
The real Ollama GPT-OSS 120B retest was blocked by timeouts; the new unseen
Ollama Gemma approval question did cite the correct meeting paragraph. A
separate mocked regression checks the original wrong-date-citation pattern.
Remaining risk: a model may attach a plausible but irrelevant citation to a
claim without an explicit date, or misinterpret a passage. Source-linked means
the original location is inspectable, not that the claim is guaranteed true.
After these changes, `python -m pytest -q` passed 259 tests with 1 skipped;
`ruff check src tests app.py scripts` passed. The fresh CLI indexed all five
files and independently returned CH-101/E6 and CH-102/E7 for strict SAR 1m.

## Three-level interview ladder and optional prompt check (2026-10-20)

A different fictional five-file folder was generated under ignored
`.local/interview_ladder_20261020`: two PDFs, two XLSX workbooks, and one DOCX.
The three questions increase in difficulty: (1) signed scope and exclusions,
(2) a strict SAR 1 million BOQ threshold across a repeated header and separate
currency/variation sheets, and (3) approved work, unapproved CCTV, unchanged
handover, rejected proposed date, and original/revised contract values across
multiple documents. Expected facts were read from the generated originals:
96 Zone West detectors, four panels CP-9 to CP-12, FP-101/E7 SAR 1,200,000 and
FP-102/E8 SAR 1,100,000 above threshold (sum SAR 2,300,000), FP-103/E9 at the
excluded boundary, A4's 18 Zone East loops and SAR 280,000 increase, original
SAR 3,450,000 and revised SAR 3,730,000, 30 November 2029 binding handover,
and an unapproved 15 December proposal.

| Model | Level 1 | Level 2 | Level 3 |
| --- | --- | --- | --- |
| Ollama Gemma 4 31B, unchanged prompt | Correct scope/exclusions with PDF citation | Correct 2 items, SAR 2,300,000, exact cells; deterministic status | Correct decisions and amounts with separate PDF/Word/Excel citations |
| Ollama GPT-OSS 20B, extra prompt | HTTP 500 during tool phase; no answer | Correct deterministic result and cells | Final-phase timeout; no answer |
| Groq GPT-OSS 20B, extra prompt | HTTP 429, about 688 s retry; no answer | HTTP 429, about 692 s retry; no answer | Facts and citations correct, but a malformed `list_documents` argument failed before successful search; overall status remained unverified |
| Gemini 2.5 Flash, extra prompt | HTTP 429 `resource_exhausted`; no answer | Not attempted after limit | Not attempted after limit |

On the previous six-file exercise, Groq's new-prompt approval answer correctly
cited the variation and meeting decision; a later BOQ request hit HTTP 429.
Gemini's approval request hit HTTP 429, and Ollama GPT-OSS 20B's approval
request hit HTTP 500. These provider failures do not measure answer accuracy
or prove the extra prompt improved it. A compact shared instruction was added
for non-Gemma models; Gemma's prompt remains byte-for-byte unchanged. No
provider-specific instruction was added based on one malformed tool call or
service outages. Full local answer/evidence JSON is ignored under
`.local/interview_ladder_results/`; no keys or generated documents are committed.

## Fresh provider reliability exercise (2026-10-20)

After adding provider-specific recovery, a different fictional five-file folder
was generated under ignored `.local/provider_reliability_20261020`. Three new
interview questions covered signed scope and exclusions, strict BOQ filtering
across separate sheets, and a cross-document approval/deadline/value decision.
The source files independently establish two SAR items above one million
(WP-11/E9 SAR 1,490,000; WP-12/E10 SAR 1,200,000), totaling SAR 2,690,000;
WP-13/E11 is exactly one million and excluded.

Gemma answered all three correctly against the source files. Ollama GPT-OSS
20B answered BOQ and the cross-document decision correctly; its first scope
attempt returned HTTP 500, then a retest answered correctly. A sanitized
request-shape probe showed that identical tool schemas can succeed, so the
HTTP 500 remains an intermittent provider/model risk. Groq GPT-OSS 20B
answered scope correctly, then reached a 429 quota delay of about 815 seconds;
one later retry still showed about 318 seconds remaining. Gemini 2.5 Flash
returned 429 on scope and again after a cooldown. Gemini 3.5 Flash Lite answered scope
correctly and, after a time-budget numeric completion fix, returned the exact
BOQ cells and sum; its cross-document question exceeded the time budget with
no answer. These provider failures were not counted as factual answer passes.

The full local suite passed **270 tests, 1 skipped** with
`python -m pytest -q --basetemp .local/pytest_provider_release`; Ruff passed.
Detailed local answers, actual tool traces, and original indexed evidence are
in `.local/provider_reliability_results/RESULTS.md` and sibling JSON files.
The generated documents and raw results are ignored by Git.

### Provider cooldown retest (2026-10-21)

Gemini 2.5 Flash answered the fictional water-plant scope question correctly
with the contract page citation after its earlier 429s. Its subsequent BOQ and
cross-document approval requests again returned 429, so neither answer was
verified live for that model. Groq GPT-OSS 20B's BOQ request completed three
real tool rounds, then hit 429 on a fourth as the repeated context grew. A
Groq-only fallback now runs the deterministic numeric/date path after prior
successful document tool use and labels it application initiated. The live BOQ
retest returned WP-11/E9 and WP-12/E10 with the correct SAR 2,690,000 sum and
indexed cell evidence. Its cross-document approval question still returned
429 after one cooldown retry; no prose answer was invented. A focused test
also checks that prose questions cannot use the numerical fallback. The
sanitized request-shape trace and raw results are in the ignored local report.
After this focused change, the full local suite passed **272 tests, 1 skipped**
and `ruff check src tests app.py scripts` passed.

## Final three-phase unfamiliar-document interview test (2026-10-21)

Seven new fictional files were generated after the application code was frozen:
three PDFs, three XLSX workbooks and one DOCX. The production `ask()` path was
used with Ollama Cloud `gemma4:31b`, Gemini `gemini-2.5-flash` and Groq
`openai/gpt-oss-20b`. The three phases asked for signed contract scope and
deliverables, all Signed Base SAR BOQ items strictly above SAR 1 million, and a
cross-document decision about change order CO-12, a proposed handover, contract
sums and final acceptance. The original files were separately opened to check
the answers, not just their citation status.

The BOQ's correct result is EL-401 at `03_Electrical_BOQ.xlsx | Signed Base!E7`
for SAR 1,560,000 and EL-402 at `E8` for SAR 1,440,000: two matches totaling
SAR 3,000,000. EL-403 at `E9` is exactly SAR 1 million and excluded. CO-12
authorizes 60 additional metres of West Wing cable for SAR 480,000, raising
the original SAR 8,240,000 contract to SAR 8,720,000. It neither authorizes
remote monitoring nor extends the binding 30 June 2031 handover. A 15 July
proposal was not approved; circuits C-04 and C-05 need retesting, and no final
acceptance certificate was issued.

| Model | Scope phase | BOQ phase | Cross-document phase |
| --- | --- | --- | --- |
| Gemma 4 31B | All requested facts, with extra BOQ quantities | Correct deterministic result | Correct with separate original sources |
| Gemini 2.5 Flash | Requested facts present, but BOQ-only items were also described as contract scope | Correct deterministic result | HTTP 429 on first call and one retry; no answer |
| Groq GPT-OSS 20B | First final request HTTP 400 `json_validate_failed`; retry returned the requested facts with extra BOQ quantities | Correct result from a labeled Python completion after provider limit | HTTP 429 on first call and one retry; no answer |

All citations in completed answers resolved to indexed passages or cells. Their
presence did not prevent Gemini's scope error, demonstrating why evidence-linked
claims remain human-reviewable rather than guaranteed. Each completed answer
included a real model document tool call; the BOQ calculations were performed
in Python. Twelve production answer sessions were made, including the three
bounded external retries. The full source files, displayed answers, tool calls,
and retrieved originals are saved only under ignored
`.local/interview_tests/final_interview_3_results/RESULTS.md` and sibling JSON files. This was
not a browser test or a reliability estimate for unfamiliar employer documents.

## Focused Ollama GPT-OSS 20B prompt retest (2026-10-21)

The same seven files and three questions were rerun with Ollama Cloud
`gpt-oss:20b`. Before the new prompt, scope omitted the contract deliverable
dates; the BOQ result was correct; the harder answer falsely said the original
SAR 8,240,000 contract sum was unavailable, and one retry returned no answer.

A compact, model-specific instruction now names the six permitted document
functions and asks the model to retrieve each source before claiming absence.
It adds 98 words to each Ollama GPT-OSS 20B request, with no extra LLM request.
Gemma and other provider prompts are unchanged. An intermediate live run
skipped `query_spreadsheet`; the broad application fallback incorrectly
included an unapproved quote. The fallback now abstains when multiple indexed
tables make its scope ambiguous, instead of labeling that total verified.

| Final prompt phase | Observed result |
| --- | --- |
| Contract scope | Correct signed scope, exclusions, three dated deliverables and original sum; citations include contract pages 1–2. |
| Strict SAR BOQ threshold | Called `query_spreadsheet` on `Signed Base`; correct two cells and SAR 3,000,000 total. |
| Cross-document decision | Correct change quantity, price, both contract sums, deadline and proposal status; omitted the requested C-04/C-05 retest and final-acceptance status. Partial answer. |

The two completed prose answers were source-linked, not semantically
guaranteed. The final run had no invented tool names, but one three-question
sample cannot establish that the prompt prevents future tool errors or
omissions. The ignored local JSON audits are named
`*_ollama_cloud_gpt-oss_20b_tighter_prompt_v2.json` in
`.local/interview_tests/final_interview_3_results/`. No browser interaction was performed.
