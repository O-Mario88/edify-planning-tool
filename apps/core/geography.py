"""
Uganda administrative-name normalization — faithful port of normalize.ts.

The single function every geography match goes through, so free-text school
uploads resolve to official COD-AB records deterministically (never silent
fuzzy guessing). The ORIGINAL text is always preserved by the caller; this
only produces a comparison key.
"""

from __future__ import annotations

import re
import unicodedata


_DIACRITICS = re.compile(r"[\u0300-\u036f]")

# Tokens that are administrative *suffixes*, not part of the place identity.
# We strip them so "Lira District" and "LIRA" both normalize to "lira". We do
# NOT strip "Town Council"/"Division"/"Municipality" — those distinguish
# distinct units (e.g. "Lira" district vs "Lira City" — keep them separate).
_SUFFIXES = [
    "district",
    "sub county",
    "subcounty",
    "sub-county",
    "county",
    "parish",
    "region",
]


def normalize_uganda_admin_name(value: str | None) -> str:
    """Normalize a Ugandan admin name to a stable comparison key."""
    if not value:
        return ""
    # Strip diacritics via NFKD decomposition.
    s = unicodedata.normalize("NFKD", value)
    s = _DIACRITICS.sub("", s)
    s = s.lower().strip()
    # unify apostrophes/punctuation → drop; keep alphanumerics + spaces
    s = re.sub(r"['’`.,]", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    # unify sub-county spellings
    s = re.sub(r"\bsub\s*county\b", "subcounty", s)
    s = re.sub(r"\s+", " ", s).strip()
    # strip a trailing admin suffix word (only at the end, only once)
    for suf in _SUFFIXES:
        pat = re.compile(r"\s" + re.sub(r"[-\s]", r"\\s*", suf) + r"$")
        if pat.search(s):
            s = pat.sub("", s).strip()
            break
    return s


def levenshtein(a: str, b: str) -> int:
    """Levenshtein distance (small strings) — for strict, bounded fuzzy matching."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        diag = prev[0]
        prev[0] = i
        for j in range(1, len(b) + 1):
            tmp = prev[j]
            cost = 0 if a[i - 1] == b[j - 1] else 1
            prev[j] = min(prev[j] + 1, prev[j - 1] + 1, diag + cost)
            diag = tmp
    return prev[len(b)]


def similarity(a: str, b: str) -> float:
    """Similarity ratio in [0,1] from normalized Levenshtein."""
    if not a and not b:
        return 1.0
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1 - levenshtein(a, b) / longest


__all__ = [
    "normalize_uganda_admin_name",
    "levenshtein",
    "similarity",
]
