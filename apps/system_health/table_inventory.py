"""Which tables show everything, and which show a page.

A table with no bound grows with the data behind it. Two cards side by side end
up different heights, the page scrolls for reasons nobody chose, and a busy
account waits on rows it will not read.

This finds every table in the templates and classifies how it is bounded:

* **paginated** — a pager object drives it, so it shows a page and says so.
* **sliced** — a `|slice:` cap. Bounded, but silent: the reader is not told
  there is more, and there is no way to reach it.
* **unbounded** — every row, however many there are.

Sliced is deliberately not counted as done. A cap that hides rows without
saying so is how a person comes to believe they have seen everything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

TEMPLATES = Path(settings.BASE_DIR) / "templates"

#: `{% for row in source %}` — the loop that feeds a table body.
_FOR = re.compile(r"{%\s*for\s+\w+\s+in\s+([\w.]+)")
_SLICE = re.compile(r"\|slice:")
_PAGER = re.compile(r"pager\.|paginator|page_obj|has_next|has_previous")


@dataclass(frozen=True)
class TableFinding:
    template: str
    line: int
    source: str
    state: str  # paginated | sliced | unbounded


def _tables_in(text: str) -> list[tuple[int, int]]:
    """(start, end) character offsets of each <table>…</table>."""
    spans = []
    for match in re.finditer(r"<table\b", text, re.IGNORECASE):
        close = text.find("</table>", match.start())
        spans.append((match.start(), close if close != -1 else len(text)))
    return spans


def scan_tables() -> list[TableFinding]:
    findings: list[TableFinding] = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = str(path.relative_to(settings.BASE_DIR))

        for start, end in _tables_in(text):
            body = text[start:end]
            loop = _FOR.search(body)
            if not loop:
                # A static table -- headers only, or a layout table. Nothing to
                # bound.
                continue
            line = text.count("\n", 0, start) + 1
            source = loop.group(1)

            # A pager may sit just outside the table it drives, so look at the
            # surrounding block rather than only between the tags.
            neighbourhood = text[start : min(len(text), end + 1200)]
            if _PAGER.search(neighbourhood):
                state = "paginated"
            elif _SLICE.search(body):
                state = "sliced"
            else:
                state = "unbounded"
            findings.append(TableFinding(relative, line, source, state))
    return findings


def table_report() -> dict:
    findings = scan_tables()
    by_state: dict[str, list[TableFinding]] = {}
    for finding in findings:
        by_state.setdefault(finding.state, []).append(finding)
    return {
        "total": len(findings),
        "paginated": len(by_state.get("paginated", [])),
        "sliced": len(by_state.get("sliced", [])),
        "unbounded": len(by_state.get("unbounded", [])),
        "findings": findings,
    }
