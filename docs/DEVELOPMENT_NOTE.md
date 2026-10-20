# Development note for SYDEN

I used OpenAI Codex inside VS Code as my AI coding agent. As of 20 October 2026,
I estimate **6–8 hours of my own involvement** in planning, working with Codex,
reviewing changes, testing the application, troubleshooting API and verification
issues, and checking results. Development is ongoing, so this is not a final time log.

Codex helped inspect the starter repository, implement the Python ingestion and
query modules, integrate LLM function calling, and write synthetic regression
tests and documentation. I reviewed the behavior against the assignment's three
example questions and an independent audit. Concrete fixes included recognizing
BOQ rows with separate currency columns, preserving rows when a header contains a
numeric year, and surfacing formulas whose cached result is unavailable.

The design keeps document parsing, local SQLite storage, deterministic numerical
queries, and the LLM provider loop separate. Source locations are stored at
ingestion, and read-only tools resolve them before answers are shown. The model
uses genuine provider function calls to request evidence; Python checks amounts,
currency, thresholds, and totals. Gemini, OpenAI, Groq, and Ollama Cloud remain
configurable through environment variables.

I later replaced the active prose verifier with source-linked claims: Python
checks that cited locations were retrieved and displays their indexed text or
cells, while making no guarantee about the model's interpretation. There is no
verification-only model request. Spreadsheet filtering and totals remain
deterministic. The interface also lets a reviewer open the cited location.

With more time I would add OCR for scanned PDFs, improve complex BOQ extraction,
measure retrieval accuracy on more unseen documents, and test the submission on
a fresh machine. I would also review confidentiality requirements before sending
any real customer content to a hosted model.
