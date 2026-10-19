# Codex development instructions

Read `PROMPT_FOR_CODEX.md` before editing. This is a time-limited SYDEN hiring take-home project.
Prefer small, testable modifications with clear diffs. Run `pytest` and `ruff check` after changes.
Do not fabricate passing tests, model tool calls, successful API integrations, or source references.
Never commit `.env`, API credentials, generated DB files or real company documents.
Do not alter user-provided original PDF/Excel files. Model-generated code/SQL/shell are not permitted in the document query tool.
Keep the LLM provider swappable (Gemini, OpenAI, Groq-hosted Llama); verify the chosen model truly supports tool calling.
Keep the current application demoable at every stage and be prepared to implement a small feature live.
