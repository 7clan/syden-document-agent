"""Validate claim provenance and comparable facts without semantic model calls.

An exact source quote proves that the quoted words occur in the index. It does
not prove that an interpretation of those words is true. Paraphrases with valid
anchors therefore remain evidence-linked rather than fully verified.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

from .tools import DATE_REGEX, _date_info, get_evidence

CARDINALS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}
STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "were", "was",
             "are", "has", "have", "had", "its", "into", "then", "while", "which",
             "their", "document", "source", "states", "says", "according"}
STATUS_GROUPS = ({"approved", "accepted", "authorized", "signed"},
                 {"proposed", "draft", "pending", "requested"},
                 {"rejected", "denied", "refused"},
                 {"passed", "pass", "succeeded", "successful"},
                 {"failed", "fail", "unsuccessful"},
                 {"included", "include", "includes"},
                 {"excluded", "exclude", "excludes"})
NEGATION = re.compile(r"\b(?:not|never|without|excluded|exclude|excludes|no)\b", re.IGNORECASE)
IDENTIFIER = re.compile(r"\b(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z]{1,8}[-–—]?\d+[A-Z0-9-]*\b", re.IGNORECASE)
NUMBER = re.compile(r"(?<![\w])\d[\d,]*(?:\.\d+)?(?:\s*(?:thousand|million|billion))?(?!\w)", re.IGNORECASE)
CLAUSE_BREAK = re.compile(r";\s*|(?<=[.!?])\s+(?=[A-Z])|,?\s+\b(?:while|whereas|but)\b\s+",
                          re.IGNORECASE)
STATUS_WORDS = set().union(*STATUS_GROUPS)
PREDICATE = re.compile(r"\b(?:is|are|was|were|has|have|had|did|does|shall|must|will|"
                       r"remains?|due|" + "|".join(sorted(STATUS_WORDS)) + r")\b",
                       re.IGNORECASE)
_DASHES = str.maketrans({char: "-" for char in "‐‑‒–—−"})


def _ascii_dashes(text: str) -> str:
    return text.translate(_DASHES)


def _without_identifiers(text: str) -> str:
    return IDENTIFIER.sub(" ", _ascii_dashes(text))


def normalize(text: str) -> str:
    """Accept PDF line wrapping and harmless Unicode/whitespace differences."""
    text = _ascii_dashes(unicodedata.normalize("NFKC", text)).casefold()
    text = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    return " ".join(text.split())


def numbers(text: str) -> set[Decimal]:
    values: set[Decimal] = set()
    for match in NUMBER.finditer(text):
        parts = match.group().lower().replace(",", "").split()
        try:
            amount = Decimal(parts[0])
            if len(parts) > 1:
                amount *= {"thousand": 1000, "million": 1000000,
                           "billion": 1000000000}[parts[1]]
            values.add(amount)
        except (InvalidOperation, KeyError):
            continue
    for word in re.findall(r"\b[a-z]+\b", text.casefold()):
        if word in CARDINALS:
            values.add(Decimal(CARDINALS[word]))
    return values


def _date_values(text: str) -> tuple[set[str], str]:
    dates = set()
    for match in DATE_REGEX.finditer(text):
        normalized, ambiguous = _date_info(match.group())
        if not ambiguous and normalized:
            dates.add(normalized)
    return dates, DATE_REGEX.sub(" ", text)


def parse_answer(raw: str) -> dict[str, Any] | None:
    """Parse a bounded JSON answer; refuse partial or malformed envelopes."""
    if not isinstance(raw, str) or len(raw) > 30000:
        return None
    candidate = raw.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = "\n".join(candidate.splitlines()[1:-1]).strip()
    try:
        value = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    if (not isinstance(value, dict) or not isinstance(value.get("answer"), str)
            or not isinstance(value.get("insufficient"), bool)
            or not isinstance(value.get("claims"), list)
            or len(value["claims"]) > 25):
        return None
    return value


def _evidence_text(evidence: dict[str, Any]) -> str:
    if "text" in evidence:
        return str(evidence["text"])
    if "row" in evidence:
        return " ".join(str(value) for value in evidence["row"].values()
                        if value is not None)
    return ""


def _spreadsheet_citation(citation: str) -> bool:
    """Distinguish workbook rows from PDF BOQ rows, which also have cells."""
    return bool(re.fullmatch(
        r".+?\.(?:xlsx|xlsm|xls) \| .+?(?: \| row [1-9]\d*|![A-Z]{1,3}[1-9]\d*)",
        citation, re.IGNORECASE))


def _row_conflict(conn: sqlite3.Connection, citation: str,
                  row: dict[str, Any], statement: str,
                  group_identifiers: set[str] | None = None) -> str | None:
    """Check explicit workbook facts against one cited row, never adjacent rows."""
    values = [str(value) for value in row.values() if value is not None]
    source = " ".join(values)
    claim_ids = _identifiers(statement)
    row_ids = _identifiers(source)
    if group_identifiers and not group_identifiers & row_ids:
        return "Cited spreadsheet row does not contain a claimed identifier"
    if claim_ids and not group_identifiers and not claim_ids <= row_ids:
        return "Identifier belongs to a different spreadsheet row"
    claim_dates, rest = _date_values(statement)
    source_dates, source_rest = _date_values(source)
    if not claim_dates <= source_dates:
        return "Date is absent or differs from cited spreadsheet row"
    if not numbers(_without_identifiers(rest)) <= numbers(_without_identifiers(source_rest)):
        return "Quantity or amount is absent from cited spreadsheet row"
    currency = re.compile(r"\b(?:SAR|AED|USD|EUR|GBP)\b", re.IGNORECASE)
    if {item.upper() for item in currency.findall(statement)} - {
            item.upper() for item in currency.findall(source)}:
        return "Currency is absent from cited spreadsheet row"

    # These are explicit cell states, not an inference from a prose sentence.
    def state(text: str, label: str) -> bool | None:
        if re.search(rf"\b(?:not|un|non)[ -]?{label}\b", text, re.IGNORECASE):
            return False
        if re.search(rf"\b{label}\b", text, re.IGNORECASE):
            return True
        return None

    for label in ("approved", "contractual", "accepted", "rejected"):
        asserted = state(statement, label)
        cell_states = {state(value, label) for value in values} - {None}
        if asserted is not None and cell_states and asserted not in cell_states:
            return f"{label.capitalize()} status conflicts with cited spreadsheet row"

    def decision(text: str) -> str | None:
        if re.search(r"\bnot[ -]+approved\b", text, re.IGNORECASE):
            return "not_approved"
        for word in ("approved", "rejected", "pending", "proposed", "accepted"):
            if re.search(rf"\b{word}\b", text, re.IGNORECASE):
                return word
        return None

    asserted_decision = decision(statement)
    source_decisions = {decision(value) for value in values} - {None}
    if (asserted_decision is not None and source_decisions
            and asserted_decision not in source_decisions):
        return "Approval or decision differs from cited spreadsheet row"

    # A distinctive cell value from another row cannot be attributed to this
    # one. This catches swapped descriptions even when their dates coincide.
    match = re.fullmatch(r"(.+?) \| (.+?)(?: \| row (\d+)|![A-Z]{1,3}(\d+))", citation)
    if match:
        path, sheet, row_number = match.group(1), match.group(2), int(match.group(3) or match.group(4))
        preceding = conn.execute(
            "SELECT s.cells_json FROM sheet_rows s JOIN documents d ON d.id=s.document_id "
            "WHERE d.path=? AND s.sheet=? AND s.row_num<? ORDER BY s.row_num DESC LIMIT 8",
            (path, sheet, row_number))
        for header_row in preceding:
            headers = json.loads(header_row[0])
            approval_columns = [col for col, cell in headers.items() if re.search(
                r"\b(?:approval|decision|status)\b", str(cell.get("value", "")), re.IGNORECASE)]
            if approval_columns:
                approval_values = [str(row[col]) for col in approval_columns if col in row]
                if asserted_decision is not None and approval_values:
                    approvals = {decision(value) or (
                        "not_approved" if re.search(r"\b(?:not|no)\b", value, re.IGNORECASE)
                        else "other") for value in approval_values}
                    if asserted_decision not in approvals:
                        return "Approval or decision differs from cited spreadsheet cell"
                break
        siblings = conn.execute(
            "SELECT s.cells_json FROM sheet_rows s JOIN documents d ON d.id=s.document_id "
            "WHERE d.path=? AND s.sheet=? AND s.row_num!=?", (path, sheet, row_number))
        folded_claim = normalize(statement)
        folded_source = normalize(source)
        for sibling in siblings:
            for cell in json.loads(sibling[0]).values():
                value = cell.get("value")
                if not isinstance(value, str):
                    continue
                phrase = normalize(value)
                if (len(phrase) >= 12 and len(phrase.split()) >= 2
                        and phrase in folded_claim and phrase not in folded_source):
                    return "Description or classification belongs to a different spreadsheet row"
    return None


def _status(text: str) -> int | None:
    words = set(re.findall(r"[a-z]+", text.casefold()))
    found = [index for index, group in enumerate(STATUS_GROUPS) if words & group]
    return found[0] if len(found) == 1 else None


def _clauses(text: str) -> list[str]:
    """Use only clear sentence, semicolon, and contrast boundaries."""
    clauses: list[str] = []
    for part in CLAUSE_BREAK.split(text):
        pieces = re.split(r"\s+and\s+", part, flags=re.IGNORECASE)
        joined = [pieces[0]]
        for piece in pieces[1:]:
            left = _subject(joined[-1])
            right = _subject(piece)
            if left and right and left != right:
                joined.append(piece)
            else:
                joined[-1] += " and " + piece
        clauses.extend(item.strip(" ,;.!?\n") for item in joined if item.strip(" ,;.!?\n"))
    return clauses


def _identifiers(text: str) -> set[str]:
    return {item.upper() for item in IDENTIFIER.findall(_ascii_dashes(text))}


def _anchor_terms(text: str) -> set[str]:
    """Score clause relevance without treating numbers or status words as entities."""
    terms = {term for term in re.findall(r"[a-z]{3,}", text.casefold())
             if term not in STOPWORDS and term not in CARDINALS
             and term not in STATUS_WORDS and term not in {"not", "never"}}
    # Preserve single-letter record labels such as "Pump A" without treating
    # an initial article ("A pump") as an entity label.
    labels = {letter.casefold() for letter in re.findall(r"(?<=\s)[A-Z](?=\s)", text)}
    return terms | labels


def _subject(text: str) -> frozenset[str]:
    predicate = PREDICATE.search(text)
    if predicate is None:
        return frozenset()
    lead = text[:predicate.start()]
    return frozenset(_identifiers(lead) or _anchor_terms(lead))


def _relevant_clauses(claim: str, quotes: list[str]) -> list[str]:
    clauses = [clause for quote in quotes for clause in _clauses(quote)]
    identifiers = _identifiers(claim)
    if identifiers:
        clauses = [clause for clause in clauses if identifiers <= _identifiers(clause)]
        terms = _relation_terms(claim)
    else:
        terms = _anchor_terms(claim)
    scored = [(len(terms & _anchor_terms(clause)), clause) for clause in clauses]
    best = max((score for score, _ in scored), default=0)
    if best:
        return [clause for score, clause in scored if score == best]
    return clauses if identifiers else []


def _relation_terms(text: str) -> set[str]:
    _, rest = _date_values(text)
    rest = _without_identifiers(rest)
    rest = NUMBER.sub(" ", rest)
    return _anchor_terms(rest)


def _contradiction(claim: str, clauses: list[str]) -> str | None:
    claim_status = _status(claim)
    source_statuses = {_status(clause) for clause in clauses} - {None}
    if len(source_statuses) > 1:
        return "Cited sources state conflicting decision statuses"
    if claim_status is not None and source_statuses and claim_status not in source_statuses:
        return "Approval or decision status conflicts with cited evidence"
    if claim_status is not None and not source_statuses:
        return "Decision status is absent from relevant evidence"
    claim_negated = bool(NEGATION.search(claim))
    source_negations = {bool(NEGATION.search(clause)) for clause in clauses}
    if len(source_negations) > 1:
        return "Relevant evidence has conflicting negation"
    if source_negations and claim_negated != next(iter(source_negations)):
        return "Negation conflicts with cited evidence"
    return None


def _external_conflict(conn: sqlite3.Connection, claim: str,
                       observed: set[str]) -> str | None:
    """Flag conflicting comparable facts for one identifier in retrieved sources."""
    identifiers = _identifiers(claim)
    if not identifiers:
        return None
    status = _status(claim)
    claim_dates, claim_rest = _date_values(claim)
    claim_numbers = numbers(_without_identifiers(claim_rest))
    relation = _relation_terms(claim)
    for citation in sorted(observed):
        for clause in _clauses(_evidence_text(get_evidence(conn, citation))):
            if not identifiers <= _identifiers(clause):
                continue
            other_relation = _relation_terms(clause)
            # Only comparable property wording supports a cross-source fact
            # conflict. A shared record ID and generic "change order" words do
            # not make a cable quantity comparable to a revised contract sum.
            comparable = (bool(relation and other_relation)
                          and (relation <= other_relation or other_relation <= relation))
            if status is not None and (not relation or not other_relation):
                comparable = True
            if not comparable:
                continue
            other_status = _status(clause)
            if status is not None and other_status is not None and other_status != status:
                return f"Conflicting retrieved source for the same identifier: {citation}"
            other_dates, other_rest = _date_values(clause)
            other_numbers = numbers(_without_identifiers(other_rest))
            if ((claim_dates and other_dates and not claim_dates <= other_dates)
                    or (claim_numbers and other_numbers and not claim_numbers <= other_numbers)):
                return f"Conflicting retrieved source for the same identifier: {citation}"
    return None


def _explicit_files(question: str, paths: list[str]) -> tuple[set[str], bool]:
    """Return exact named files and whether any named file was not indexed."""
    aliases: dict[str, tuple[str, set[str]]] = {}
    for path in paths:
        for alias in {path, re.split(r"[/\\]", path)[-1]}:
            key = alias.casefold()
            if key not in aliases:
                aliases[key] = (alias, set())
            aliases[key][1].add(path)
    matches: list[tuple[int, int, set[str]]] = []
    for alias, documents in sorted(aliases.values(), key=lambda item: len(item[0]),
                                   reverse=True):
        pattern = re.compile(r"(?<![\w./\\-])" + re.escape(alias) + r"(?![\w./\\-])",
                             re.IGNORECASE)
        for match in pattern.finditer(question):
            start, end = match.span()
            if not any(start < used_end and used_start < end
                       for used_start, used_end, _ in matches):
                matches.append((start, end, documents))
    # An unknown explicit filename must not leave every indexed file eligible.
    extensions = re.finditer(r"(?<=[\w)\]])\.(?:pdf|xlsx|xlsm|xls|docx)(?![\w.])",
                             question, re.IGNORECASE)
    unknown = any(not any(start <= extension.start() < end for start, end, _ in matches)
                  for extension in extensions)
    return {path for _, _, documents in matches for path in documents}, unknown


def question_parts(question: str) -> list[str]:
    """Preserve separately asked questions so a filename scopes only its part."""
    parts = re.split(
        r"(?i)[?;]+|,\s*(?=(?:what|which|how|when|where|who)\b)|"
        r"\s+and\s+(?=(?:what|which|how|when|where|who)\b)", question)
    cleaned = [part.strip(" ,.?;\n") for part in parts if part.strip(" ,.?;\n")]
    if (len(cleaned) > 1 and re.match(r"(?i)^(?:according to|from|in)\b", cleaned[0])
            and not re.search(r"(?i)\b(?:what|which|how|when|where|who)\b", cleaned[0])):
        cleaned[1] = cleaned[0] + ", " + cleaned[1]
        cleaned.pop(0)
    return cleaned or [question]


def _scope_allows(question: str, paths: list[str], filename: str,
                  part_index: int | None) -> bool:
    parts = question_parts(question)
    inherited: set[str] = set()
    if re.match(r"(?i)^according to\b", question):
        inherited, _ = _explicit_files(parts[0], paths)
    if part_index is not None:
        if not 0 <= part_index < len(parts):
            return False
        parts = [parts[part_index]]
    for part in parts:
        named, unknown = _explicit_files(part, paths)
        if not named and inherited:
            named = inherited
        if not unknown and (not named or filename in named):
            return True
    return False


def _source_span(source: str, quote: str) -> tuple[int, int] | None:
    """Map normalized PDF line wraps back to offsets in indexed source text."""
    folded: list[str] = []
    offsets: list[int] = []
    index = 0
    while index < len(source):
        wrapped = re.match(r"-\s*\n\s*", source[index:])
        if (wrapped and index and source[index - 1].isalnum()
                and index + wrapped.end() < len(source)
                and source[index + wrapped.end()].isalnum()):
            index += wrapped.end()
            continue
        for char in _ascii_dashes(unicodedata.normalize(
                "NFKC", source[index])).casefold():
            if char.isspace():
                if folded and folded[-1] != " ":
                    folded.append(" ")
                    offsets.append(index)
            else:
                folded.append(char)
                offsets.append(index)
        index += 1
    needle = normalize(quote)
    found = "".join(folded).find(needle)
    if found < 0:
        return None
    return offsets[found], offsets[found + len(needle) - 1] + 1


def _select_local_span(source: str, claim: str) -> tuple[int, int] | None:
    """Locate source text for a citation-only support; matching is not a truth verdict."""
    claim_terms = _anchor_terms(claim)
    claim_ids = _identifiers(claim)
    claim_dates, without_dates = _date_values(claim)
    claim_values = numbers(_without_identifiers(without_dates))
    candidates = []
    for match in re.finditer(r"[^\n.!?;]+(?:[.!?;]|$)", source):
        piece = match.group().strip()
        dates, rest = _date_values(piece)
        if (claim_ids and not claim_ids <= _identifiers(piece)) or (
            claim_dates and not claim_dates <= dates) or (
            claim_values and not claim_values <= numbers(_without_identifiers(rest))):
            continue
        score = len(claim_terms & _anchor_terms(piece))
        if score:
            candidates.append((score, -match.start(), match.start(), match.end()))
    if not candidates:
        return None
    _, _, start, end = max(candidates)
    return start, end


def _direct_conflict(claim: str, source: str) -> str | None:
    """Reject only comparable explicit facts; never use a clause to prove prose."""
    relevant = _relevant_clauses(claim, [source])
    if not relevant:
        return None
    if ((_status(claim) is not None or bool(NEGATION.search(claim)) or any(
            NEGATION.search(clause) for clause in relevant))
            and (_status(claim) is None or any(
                _status(clause) is not None for clause in relevant))):
        conflict = _contradiction(claim, relevant)
        if conflict:
            return "Explicit conflicting fact: " + conflict
    claim_dates, rest = _date_values(claim)
    claim_values = numbers(_without_identifiers(rest))
    source_dates, source_rest = _date_values(" ".join(relevant))
    source_values = numbers(_without_identifiers(source_rest))
    if claim_dates and source_dates and not claim_dates <= source_dates:
        return "Explicit date conflicts with the relevant source assertion"
    if claim_values and source_values and not claim_values <= source_values:
        return "Explicit amount or quantity conflicts with the relevant source assertion"
    return None


def _resolve_supports(conn: sqlite3.Connection, claim: str, supports: list[Any],
                      allowed: set[str], question: str, paths: list[str],
                      part: int | None) -> tuple[list[str], list[dict[str, Any]], list[str], str]:
    """Authenticate citations and return spans cut from the local index."""
    citations: list[str] = []
    excerpts: list[dict[str, Any]] = []
    full_sources: list[str] = []
    structured_rows: list[tuple[str, dict[str, Any], str]] = []
    for support in supports:
        if not isinstance(support, dict):
            return citations, excerpts, full_sources, "Malformed source reference"
        citation, quote = support.get("citation"), support.get("quote", "")
        if (not isinstance(citation, str) or citation not in allowed
                or citation.endswith(" | document") or not isinstance(quote, str)
                or len(quote) > 1200 or not _scope_allows(
                    question, paths, citation.split(" | ")[0], part)):
            return citations, excerpts, full_sources, (
                "Source was not retrieved or is outside the question part")
        evidence = get_evidence(conn, citation)
        source = _evidence_text(evidence)
        if not source:
            return citations, excerpts, full_sources, "Cited source is missing from the index"
        if _spreadsheet_citation(citation):
            row = evidence.get("row")
            if not isinstance(row, dict):
                return citations, excerpts, full_sources, "Cited spreadsheet row is missing"
            structured_rows.append((citation, row, quote))
            citations.append(citation)
            full_sources.append(source)
            excerpts.append({"citation": citation, "quote": source,
                             "start": 0, "end": len(source), "structured": True})
            continue
        span = _source_span(source, quote) if quote else _select_local_span(source, claim)
        if span is None:
            return citations, excerpts, full_sources, (
                "Quotation does not occur at the cited source" if quote else
                "No local source span matches the claim")
        start, end = span
        citations.append(citation)
        full_sources.append(source)
        excerpts.append({"citation": citation, "quote": source[start:end],
                         "start": start, "end": end})
    claim_ids = _identifiers(claim)
    grouped = (len(claim_ids) > 1 and len(structured_rows) > 1
               and len(structured_rows) == len(supports))
    if grouped:
        covered = set().union(*(_identifiers(_evidence_text({"row": row}))
                                for _, row, _ in structured_rows))
        if not claim_ids <= covered:
            return citations, excerpts, full_sources, "Claimed identifier is absent from cited rows"
    for citation, row, quote in structured_rows:
        # Each claimed ID must have its own cited row. Shared properties such as
        # "contractual" are checked on every row; dates and amounts must also
        # agree with every row unless the model splits them into atomic claims.
        if conflict := _row_conflict(conn, citation, row, claim,
                                     claim_ids if grouped else None):
            return citations, excerpts, full_sources, conflict
        if quote and (conflict := _row_conflict(conn, citation, row, quote)):
            return citations, excerpts, full_sources, conflict
    return citations, excerpts, full_sources, ""


def _check_comparable_facts(conn: sqlite3.Connection, claim: str,
                            excerpts: list[dict[str, Any]], full_sources: list[str],
                            allowed: set[str]) -> str:
    """Reject checkable discrepancies; do not certify semantic entailment."""
    combined = " ".join(item["quote"] for item in excerpts)
    whole = " ".join(full_sources)
    claim_dates, without_dates = _date_values(claim)
    source_dates, source_without_dates = _date_values(combined)
    claim_numbers = numbers(_without_identifiers(without_dates))
    source_numbers = numbers(_without_identifiers(source_without_dates))
    if not claim_dates <= source_dates:
        return "Date is absent or differs from supporting span"
    if not claim_numbers <= source_numbers:
        return "Quantity or amount is absent from supporting span"
    if not _identifiers(claim) <= _identifiers(combined):
        return "Identifier is absent from supporting span"
    def currencies(value: str) -> set[str]:
        return {code.upper() for code in re.findall(
            r"\b(?:SAR|AED|USD|EUR|GBP)\b", value, re.IGNORECASE)}
    if not currencies(claim) <= currencies(combined):
        return "Currency is absent from supporting span"
    # This is only a relevance floor. Shared words do not establish a relation.
    if not _identifiers(claim) and len(
            _anchor_terms(claim) & _anchor_terms(normalize(combined))) < (
                1 if claim_dates or claim_numbers or _status(claim) is not None else 2):
        return "Source span has no identifiable subject in common with claim"
    conflict = _direct_conflict(claim, combined)
    if conflict:
        return conflict
    if _status(claim) is not None:
        status_clauses = [piece for piece in _clauses(whole)
                          if (_status(piece) == _status(claim)
                              and (not _identifiers(claim)
                                   or _identifiers(claim) <= _identifiers(piece)))]
        if not status_clauses:
            return "Decision status is absent from cited source"
    return _external_conflict(conn, claim, allowed) or ""


def validate_claims(conn: sqlite3.Connection, raw: str,
                    observed_citations: list[str], question: str = "") -> dict[str, Any]:
    """Authenticate local support; reserve certainty for exact text or calculations.

    The model interprets prose. Local checks establish provenance and explicit
    comparable facts, but an authentic excerpt does not prove its interpretation.
    """
    payload = parse_answer(raw)
    if payload is None:
        return {"status": "unverified", "claims": [], "sources": [],
                "answer": "Structured answer unavailable. Inspect the retrieved sources below.",
                "reason": "Malformed or missing structured answer"}
    allowed = set(observed_citations)
    paths = [row["path"] for row in conn.execute("SELECT path FROM documents")]
    results: list[dict[str, Any]] = []
    for entry in payload["claims"]:
        if not isinstance(entry, dict):
            results.append({"text": "", "status": "unverified", "sources": [], "quotes": [],
                            "reason": "Malformed claim"})
            continue
        claim, supports = entry.get("text"), entry.get("supports")
        if (not isinstance(claim, str) or not 1 <= len(claim) <= 1000
                or not isinstance(supports, list) or not 1 <= len(supports) <= 8):
            results.append({"text": str(claim or "")[:1000], "status": "unverified",
                            "sources": [], "quotes": [], "reason": "Missing claim or support"})
            continue
        part = entry.get("question_part")
        if part is not None and (isinstance(part, bool) or not isinstance(part, int)):
            reason = "Invalid question part"
            citations: list[str] = []
            excerpts: list[dict[str, Any]] = []
        else:
            citations, excerpts, full_sources, reason = _resolve_supports(
                conn, claim, supports, allowed, question, paths, part)
            if not reason:
                # Cell facts have already been checked against their own rows.
                # Text passages retain strict span and comparable-fact checks.
                prose = [item for item in excerpts if not item.get("structured")]
                if prose and len(prose) == len(excerpts):
                    reason = _check_comparable_facts(
                        conn, claim, prose, full_sources, allowed)
        exact = not reason and any(not item.get("structured") and
                                   normalize(claim) in normalize(item["quote"])
                                   for item in excerpts)
        status = ("unverified" if reason else
                  "deterministically_verified" if exact else "evidence_linked")
        results.append({"text": claim, "status": status,
                        "sources": list(dict.fromkeys(citations)) if not reason else [],
                        "quotes": excerpts if not reason else [],
                        "reason": reason or ("Exact source wording" if exact else
                                             "Interpretation is not independently proven")})
    accepted = [item for item in results if item["status"] != "unverified"]
    rejected = [item for item in results if item["status"] == "unverified"]
    sources = list(dict.fromkeys(cite for item in accepted for cite in item["sources"]))
    rendered = ("Insufficient verified evidence to answer." if payload["insufficient"] or
                not accepted else "\n".join(
                    f"- {item['text']} — {', '.join(item['sources'])}" for item in accepted))
    if rejected:
        rendered += f"\n\n{len(rejected)} unsupported claim(s) omitted."
    status = ("unverified" if rejected or not accepted or payload["insufficient"] else
              "evidence_linked" if any(item["status"] == "evidence_linked"
                                       for item in accepted) else "deterministically_verified")
    return {"status": status, "claims": results, "sources": sources,
            "answer": rendered, "reason": ""}
