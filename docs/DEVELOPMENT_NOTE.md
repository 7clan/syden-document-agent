# Development note for SYDEN

I used OpenAI Codex inside VS Code as my AI coding agent. As of 19 October 2026,
I estimate **2–3 hours of my own work** on planning, working with Codex, reviewing
the implementation, testing, and addressing issues. Development is ongoing, so I
will update that estimate before submission rather than present it as a final time log.

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

With more time I would add OCR for scanned PDFs, improve extraction of complex
merged or borderless BOQ tables, measure retrieval quality on a larger unseen
document set, and test the final submission on a fresh machine. I would also
review each real customer document's confidentiality requirements before sending
any content to a hosted model.
