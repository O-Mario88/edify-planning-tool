"""
Salesforce-ready ID validation — port of salesforce-id.util.ts.

Salesforce is NOT integrated — users enter these IDs manually and IA confirms.
Visits use SV- (canonical) AND SVE- (the prefix the FE emits). Trainings /
cluster meetings / SIT use TS-. Both forms round-trip the same.
"""

from __future__ import annotations

import re

_SV = re.compile(r"^SVE?-\w{3,}$", re.IGNORECASE)
_TS = re.compile(r"^TS-\w{3,}$", re.IGNORECASE)


def is_valid_salesforce_id(id_value: str, kind: str) -> bool:
    """kind: 'visit' | 'training'."""
    v = (id_value or "").strip()
    return bool(_SV.match(v)) if kind == "visit" else bool(_TS.match(v))


def salesforce_prefix_for(kind: str) -> str:
    return "SV-" if kind == "visit" else "TS-"


__all__ = ["is_valid_salesforce_id", "salesforce_prefix_for"]
