"""
Audit hash-chain helpers — faithful port of audit-hash.ts.

Pure functions (no Django deps) so they can be reused by the AuditService, the
chain verifier management command, and unit tests.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


def stable_stringify(value: Any) -> str:
    """Deterministic JSON: object keys sorted recursively, so a payload
    re-serialized from the DB hashes identically to the original."""
    if value is None or not isinstance(value, (dict, list)):
        # JSON.stringify(undefined) -> "null"; map None -> "null".
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            # Match JS JSON.stringify for finite numbers; ints render without .
            if isinstance(value, float) and value.is_integer():
                return str(int(value))
            return repr(value)
        return _json_escape(str(value))
    if isinstance(value, list):
        return "[" + ",".join(stable_stringify(v) for v in value) + "]"
    obj = value
    keys = sorted(obj.keys())
    return (
        "{"
        + ",".join(f"{stable_stringify(k)}:{stable_stringify(obj[k])}" for k in keys)
        + "}"
    )


def _json_escape(s: str) -> str:
    # Minimal JSON string escaping matching JS JSON.stringify for the typical
    # inputs that appear in audit payloads.
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


@dataclass
class CanonicalAuditFields:
    action: str
    subject_kind: str | None = None
    subject_id: str | None = None
    actor_id: str | None = None
    actor_role: str | None = None
    success: bool = True
    reason: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    correlation_id: str | None = None
    payload: Any = None


def canonical_audit(record: CanonicalAuditFields) -> str:
    """The canonical, hashed representation of an audit record's business fields."""
    return stable_stringify(
        [
            record.action,
            record.subject_kind if record.subject_kind is not None else None,
            record.subject_id if record.subject_id is not None else None,
            record.actor_id if record.actor_id is not None else None,
            record.actor_role if record.actor_role is not None else None,
            record.success,
            record.reason if record.reason is not None else None,
            record.ip_address if record.ip_address is not None else None,
            record.user_agent if record.user_agent is not None else None,
            record.correlation_id if record.correlation_id is not None else None,
            record.payload if record.payload is not None else None,
        ]
    )


def chain_hash(prev_hash: str, canonical: str) -> str:
    return hashlib.sha256(f"{prev_hash}\n{canonical}".encode("utf-8")).hexdigest()


__all__ = [
    "stable_stringify",
    "CanonicalAuditFields",
    "canonical_audit",
    "chain_hash",
]
