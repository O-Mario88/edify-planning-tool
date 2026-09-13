"""Impact Assessment's collection worklist (IA review, 2026-09-13).

Every operationally active school in the officer's country, by what its
evidence needs next: never assessed, follow-up due, pending verification,
returned, collection scheduled, visit completed without scores, partner
collection pending — with special-project enrolments as one segment.

Owner: IA-C implements; the signature and return shape are the contract.
"""

from __future__ import annotations


def collection_worklist(principal, query) -> dict:
    """{"rows": [...], "counts": {state: n}, "filters": {...}, "page": {...}}."""

    return {"rows": [], "counts": {}, "filters": {}, "page": {"number": 1, "pages": 1}}
