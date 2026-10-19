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
                 {"failed", "fail", "unsuccessful"})
NEGATION = re.compile(r"\b(?:not|never|without|excluded|exclude|excludes|no)\b", re.IGNORECASE)
IDENTIFIER = re.compile(r"\b(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z]{1,8}[-–—]?\d+[A-Z0-9-]*\b", re.IGNORECASE)
NUMBER = re.compile(r"(?<![\w])\d[\d,]*(?:\.\d+)?(?:\s*(?:thousand|million|billion))?(?!\w)", re.IGNORECASE)


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


def _contradiction(claim: str, quotes: list[str]) -> str | None:
    claim_status = _status(claim)
    quote_statuses = {_status(quote) for quote in quotes} - {None}
    if claim_status is not None and quote_statuses and claim_status not in quote_statuses:
        return "Approval or decision status conflicts with cited evidence"
    if len(quote_statuses) > 1:
        return "Cited sources state conflicting decision statuses"
    claim_negated = bool(NEGATION.search(claim))
    source_negations = {bool(NEGATION.search(quote)) for quote in quotes}
    if len(source_negations) == 1 and claim_negated != next(iter(source_negations)):
        return "Negation conflicts with cited evidence"
    return None


def _external_conflict(conn: sqlite3.Connection, claim: str,
                       cited: list[str], observed: set[str]) -> str | None:
    """Flag opposite explicit statuses for the same identifier in retrieved sources."""
    identifiers = {item.upper() for item in IDENTIFIER.findall(claim)}
    status = _status(claim)
    if not identifiers or status is None:
        return None
    for citation in sorted(observed - set(cited)):
        other = _evidence_text(get_evidence(conn, citation))
        if identifiers & {item.upper() for item in IDENTIFIER.findall(other)} and (
                other_status := _status(other)) is not None and other_status != status:
            return f"Conflicting retrieved source for the same identifier: {citation}"
    return None


def validate_claims(conn: sqlite3.Connection, raw: str,
                    observed_citations: list[str], question: str = "") -> dict[str, Any]:
    """Return claim-level statuses using only retrieved, locally indexed evidence."""
    payload = parse_answer(raw)
    if payload is None:
        return {"status": "unverified", "claims": [], "sources": [],
                "answer": "Structured answer unavailable. Inspect the retrieved sources below.",
                "reason": "Malformed or missing structured answer"}
    allowed = set(observed_citations)
    named_files = [row["path"] for row in conn.execute("SELECT path FROM documents")
                   if row["path"].casefold() in question.casefold()]
    if named_files:
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
            combined = " ".join(quotes)
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
            elif not {identifier.upper().replace("–", "-").replace("—", "-")
                      for identifier in IDENTIFIER.findall(claim)}.issubset(
                    {identifier.upper().replace("–", "-").replace("—", "-")
                     for identifier in IDENTIFIER.findall(combined)}):
                reason = "Identifier is absent from supporting quote"
            else:
                reason = _contradiction(claim, quotes) or ""
            if not reason:
                claim_terms = {term for term in re.findall(r"[a-z]{3,}", claim.casefold())
                               if term not in STOPWORDS and term not in CARDINALS}
                quote_terms = set(re.findall(r"[a-z]{3,}", combined.casefold()))
                if claim_terms and not claim_terms & quote_terms:
                    reason = "Quotation has no shared subject or action anchor"
            if not reason:
                reason = _external_conflict(conn, claim, citations, allowed) or ""
        status = ("unverified" if reason else
                  "deterministically_verified" if any(normalize(claim) in normalize(q)
                                                  for q in quotes) else "evidence_linked")
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
