# Document Intelligence Agent — developer instructions

This is an independent document-analysis project, not a hiring submission. Read `README.md` and `PROMPT_FOR_CODEX.md` before editing.

Make small, testable changes. Run `python -m pytest -q` and `ruff check src tests app.py scripts` before merging. Do not claim tests ran unless they actually did.
Never commit `.env`, API secrets, indexed databases, uploads, or confidential source documents. Preserve read-only LLM tools and source citations. Do not allow the model to execute arbitrary code, SQL, or shell commands.
Maintain provider portability, deterministic financial calculations, and explicit uncertainty when extraction fails. Hybrid retrieval is a planned improvement; don't describe it as implemented until it is tested and integrated.
Prefer readable Python over excessively compressed expressions, with comments explaining non-obvious logic.
