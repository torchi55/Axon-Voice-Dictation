"""Snippet collision detection (PLAN steps 5, 9) — pure, no Qt.

Errors block saving; warnings are advisory. Duplicate keywords are an error
(ambiguous). Whole-word containment ("api" inside "api key") is only a warning,
because Snippet expansion sorts by descending keyword length so the longer
keyword deterministically wins.
"""
import re


def find_collisions(pairs: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for a list of (keyword, expansion) rows."""
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    keywords: list[str] = []

    for kw, exp in pairs:
        k = kw.strip()
        if not k:
            if exp.strip():
                errors.append("A row has an expansion but no keyword.")
            continue
        kl = k.lower()
        if kl in seen:
            errors.append(f"Duplicate keyword: {k!r}")
            continue
        seen.add(kl)
        keywords.append(k)

    for a in keywords:
        for b in keywords:
            if a.lower() == b.lower():
                continue
            if re.search(rf"\b{re.escape(a)}\b", b, re.IGNORECASE):
                warnings.append(f"{a!r} is contained in {b!r} — the longer keyword wins.")

    return errors, warnings
