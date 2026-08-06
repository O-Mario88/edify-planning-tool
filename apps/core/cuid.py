"""
Collision-resistant identifiers (CUID) — a faithful port of the NestJS
`cuid()` default the legacy backend used for every model's `@id`.

We reproduce the format (`c` prefix + base36 timestamp + counter + random +
fingerprint) so seeded IDs and any persisted cross-references remain
lexically and structurally compatible. New IDs generated here intermingle
cleanly with legacy ones.
"""

from __future__ import annotations

import os
import threading
import time

_LOCK = threading.Lock()
# Counter + last-dispatched ms. Defaults chosen to mirror the reference impl.
_counter = 0
_last_ts = 0

# A per-process random fingerprint (constant for the process lifetime).
_FINGERPRINT = None


def _to_base36(number: int) -> str:
    if number == 0:
        return "0"
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    chars: list[str] = []
    while number:
        number, rem = divmod(number, 36)
        chars.append(alphabet[rem])
    return "".join(reversed(chars))


def _random_block(size: int = 4) -> str:
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(alphabet[b % 36] for b in os.urandom(size))


def _fingerprint() -> str:
    global _FINGERPRINT
    if _FINGERPRINT is None:
        # Mix the PID + a random block so two processes diverge.
        source = f"{os.getpid()}{_random_block(6)}"
        _FINGERPRINT = "".join(_to_base36(ord(ch) % 36) for ch in source)[:4].ljust(
            4, "0"
        )
    return _FINGERPRINT


def cuid() -> str:
    """Generate a new CUID string."""
    global _counter, _last_ts
    with _LOCK:
        now_ms = int(time.time() * 1000)
        if now_ms == _last_ts:
            _counter += 1
        else:
            _counter = 0
            _last_ts = now_ms
        local_counter = _counter

    # Timestamp block, base36, stripped of leading '0'.
    ts_block = _to_base36(now_ms)
    counter_block = _to_base36(local_counter).rjust(2, "0")[:2]

    return (
        "c"
        + ts_block
        + counter_block
        + _random_block(4)
        + _fingerprint()
        + _random_block(2)
    )


# A short, monotonic helper for deterministic IDs (e.g. CorePlan "cplan-<id>").
def deterministic(prefix: str, *parts: str) -> str:
    """Build a deterministic id like the legacy `cplan-{schoolId}` / `cslot-...`."""
    return f"{prefix}-" + "-".join(str(p) for p in parts)


__all__ = ["cuid", "deterministic"]
