# Hybrid retrieval — implementation plan

**Status: planned, not implemented.** The current `search_documents` tool in `src/document_agent/tools.py` uses bounded lexical keyword matching. The existing `semantic_verifier.py` concerns answer verification; it is **not** a vector retrieval engine.

## Objective
Improve discovery of evidence when a question paraphrases a source document, while preserving exact-match search for item IDs, costs, filenames, and dates. Keep all displayed citations linked to the original indexed PDF, Word block, or worksheet row.

## Implementation stages
1. **Baseline tests**: Create a small held-out corpus of invented contracts and BOQs. Record retrieval recall@k for exact wording, synonyms, paraphrases, different document types and exact item codes before changing search.
2. **Optional embeddings**: Introduce a configurable, locally runnable embedding provider with a pinned model ID and dimensions. Embed normalized, citation-bearing passages, Word blocks, and carefully selected textual representations of worksheet rows. Avoid sending confidential files to hosted embedding APIs without authorization.
3. **Incremental index**: Store embeddings keyed by a stable source-record identifier/citation, content fingerprint, embedding model/version and vector dimension. Rebuild when content or model changes; remove deleted records. Keep the lexical database usable without embedding dependencies.
4. **Search and rank fusion**: Retrieve bounded top-k lexical and vector candidates, merge by exact citation and fuse ranks using reciprocal rank fusion (RRF) or an equally transparent method. Preserve strong exact-code matches; expose the retrieval mode and search evidence for auditing. A single index must not silently merge incompatible vector models.
5. **Agent integration**: Keep the existing `search_documents` contract and source citations stable where practical. Route evidence through existing `get_evidence` and citation checks. Do not let embedding similarity count as evidence of a numerical fact or final answer correctness.
6. **Tests and fallback**: Validate exact identifiers, cross-document ambiguity, numeric BOQ queries, citations, empty or corrupt documents, missing embeddings, provider failures, deleted/reindexed documents and reproducible ranking. Fall back to lexical search when embeddings are unavailable, with a visible notice.

## Suggested sequence for small, reviewable PRs
- PR 1: embedding interface + storage/migration + offline unit tests.
- PR 2: semantic retriever with fixed examples + deterministic fusion tests.
- PR 3: tool integration, configuration, UI indication + held-out evaluation.

## Guardrails
- BOQ totals still come from `query_spreadsheet` and `Decimal`, never vector similarity.
- The semantic search score helps **find candidate evidence**; it does not verify that evidence supports a claim.
- No generated SQL, shell commands or code execution by the LLM.
- Report measured retrieval metrics only after actually running the tests.
