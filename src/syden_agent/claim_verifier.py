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


def normalize(text: str) -> str:
    """Accept PDF line wrapping and harmless Unicode/whitespace differences."""
    text = unicodedata.normalize("NFKC", text).casefold()
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
    return {item.upper().replace("–", "-").replace("—", "-")
            for item in IDENTIFIER.findall(text)}


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


def _facts(text: str) -> tuple[frozenset[str], frozenset[Decimal], int | None, bool]:
    dates, rest = _date_values(text)
    return frozenset(dates), frozenset(numbers(rest)), _status(text), bool(NEGATION.search(text))


def _relation_terms(text: str) -> set[str]:
    _, rest = _date_values(text)
    rest = IDENTIFIER.sub(" ", rest)
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
    claim_numbers = numbers(IDENTIFIER.sub(" ", claim_rest))
    relation = _relation_terms(claim)
    for citation in sorted(observed):
        for clause in _clauses(_evidence_text(get_evidence(conn, citation))):
            if not identifiers <= _identifiers(clause):
                continue
            other_relation = _relation_terms(clause)
            shared = relation & other_relation
            comparable = (not relation or not other_relation or len(shared) >= 2
                          or (len(relation) == 1 and relation == other_relation))
            if not comparable:
                continue
            other_status = _status(clause)
            if status is not None and other_status is not None and other_status != status:
                return f"Conflicting retrieved source for the same identifier: {citation}"
            other_dates, other_rest = _date_values(clause)
            other_numbers = numbers(IDENTIFIER.sub(" ", other_rest))
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


def validate_claims(conn: sqlite3.Connection, raw: str,
                    observed_citations: list[str], question: str = "") -> dict[str, Any]:
    """Return claim-level statuses using only retrieved, locally indexed evidence."""
    payload = parse_answer(raw)
    if payload is None:
        return {"status": "unverified", "claims": [], "sources": [],
                "answer": "Structured answer unavailable. Inspect the retrieved sources below.",
                "reason": "Malformed or missing structured answer"}
    allowed = set(observed_citations)
    named_files, unknown_file = _explicit_files(
        question, [row["path"] for row in conn.execute("SELECT path FROM documents")])
    if unknown_file:
        allowed = set()
    elif named_files:
        allowed = {cite for cite in allowed if cite.split(" | ")[0] in named_files}
    results: list[dict[str, Any]] = []
    for entry in payload["claims"]:
        if not isinstance(entry, dict):
            results.append({"text": "", "status": "unverified", "sources": [], "quotes": [],
                            "reason": "Malformed claim"})
            continue
        claim = entry.get("text")
        supports = entry.get("supports")
        if (not isinstance(claim, str) or not 1 <= len(claim) <= 1000
                or not isinstance(supports, list) or not 1 <= len(supports) <= 8):
            results.append({"text": str(claim or "")[:1000], "status": "unverified",
                            "sources": [], "quotes": [],
                            "reason": "Missing claim text or source quotation"})
            continue
        citations: list[str] = []
        quotes: list[str] = []
        reason = ""
        for support in supports:
            if not isinstance(support, dict):
                reason = "Malformed source reference"
                break
            citation, quote = support.get("citation"), support.get("quote")
            if (not isinstance(citation, str) or citation not in allowed
                    or citation.endswith(" | document")
                    or not isinstance(quote, str) or not 4 <= len(quote) <= 1200):
                reason = "Source was not retrieved or quotation is missing"
                break
            evidence = _evidence_text(get_evidence(conn, citation))
            if not evidence or normalize(quote) not in normalize(evidence):
                reason = "Quotation does not occur at the cited source"
                break
            citations.append(citation)
            quotes.append(quote)
        if not reason:
            clauses = _relevant_clauses(claim, quotes)
            exact = any(normalize(claim) in normalize(quote) for quote in quotes)
            if not clauses and not exact:
                reason = "No source clause ties the claimed entity or action to its evidence"
            elif not clauses:
                clauses = quotes
        if not reason:
            # Values from other clauses must not rescue a wrong entity association.
            # A coordinated clause with several different values is uncertain
            # unless the claim repeats exact source wording or names every value.
            signatures = {_facts(clause) for clause in clauses}
            claim_dates, claim_without_dates = _date_values(claim)
            claim_numbers = numbers(claim_without_dates)
            if not exact and len(signatures) > 1 and (claim_dates or claim_numbers
                                                       or _status(claim) is not None):
                reason = "Conflicting facts among relevant source clauses; association is uncertain"
            elif not exact and len(clauses) == 1:
                source_dates, source_rest = _date_values(clauses[0])
                source_numbers = numbers(source_rest)
                if ((claim_dates and len(source_dates) > 1 and source_dates - claim_dates)
                        or (claim_numbers and len(source_numbers) > 1
                            and source_numbers - claim_numbers)):
                    reason = "Several values share one source clause; association is uncertain"
            if (not reason and not exact and not claim_dates and not claim_numbers
                    and _status(claim) is None
                    and max((len(_anchor_terms(claim) & _anchor_terms(clause))
                             for clause in clauses), default=0) < 2):
                reason = "Quote does not establish the claimed action or relationship"
        if not reason:
            combined = " ".join(clauses)
            claim_dates, claim_without_dates = _date_values(claim)
            source_dates, source_without_dates = _date_values(combined)
            if not claim_dates.issubset(source_dates):
                reason = "Date is absent or differs from supporting quote"
            elif not numbers(claim_without_dates).issubset(numbers(source_without_dates)):
                reason = "Quantity, amount, or date number is absent from supporting quote"
            elif not {code.upper() for code in re.findall(
                    r"\b(?:SAR|AED|USD|EUR|GBP)\b", claim, re.IGNORECASE)}.issubset(
                    {code.upper() for code in re.findall(
                        r"\b(?:SAR|AED|USD|EUR|GBP)\b", combined, re.IGNORECASE)}):
                reason = "Currency is absent from supporting quote"
            elif not _identifiers(claim).issubset(_identifiers(combined)):
                reason = "Identifier is absent from supporting quote"
            else:
                reason = _contradiction(claim, clauses) or ""
            if not reason:
                reason = _external_conflict(conn, claim, allowed) or ""
        status = ("unverified" if reason else
                  "deterministically_verified" if exact else "evidence_linked")
        results.append({"text": claim, "status": status,
                        "sources": list(dict.fromkeys(citations)) if not reason else [],
                        "quotes": ([{"citation": cite, "quote": quote}
                                    for cite, quote in zip(citations, quotes, strict=True)]
                                   if not reason else []),
                        "reason": reason or ("Exact source wording" if
                                           status == "deterministically_verified" else
                                           "Interpretation is not independently proven")})
    accepted = [item for item in results if item["status"] != "unverified"]
    rejected = [item for item in results if item["status"] == "unverified"]
    sources = list(dict.fromkeys(cite for item in accepted for cite in item["sources"]))
    if payload["insufficient"] or not accepted:
        rendered = "Insufficient verified evidence to answer."
    else:
        rendered = "\n".join(f"- {item['text']} — {', '.join(item['sources'])}"
                             for item in accepted)
    if rejected:
        rendered += f"\n\n{len(rejected)} unsupported claim(s) omitted."
    status = ("unverified" if rejected or not accepted or payload["insufficient"] else
              "evidence_linked" if any(item["status"] == "evidence_linked"
                                       for item in accepted) else "deterministically_verified")
    return {"status": status, "claims": results, "sources": sources,
            "answer": rendered, "reason": ""}
