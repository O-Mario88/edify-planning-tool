"""Charts a card sets up in its own script (``x-data`` that builds an
EdifyChartSystem config: My Targets' Progress Trend, the debrief dashboard's
donuts), read as the app's bar chart when the config's series and labels
are written out as plain values.

A line becomes one bar per label for each series; a donut becomes one series
across its labels. A config whose values are computed in the browser
(``points.map(...)``) cannot be read without running it, so it is left to the
card's other readers.
"""

from __future__ import annotations

import json
import re

from apps.mobile_feed.page_blocks import Node

MARKER = "cfg.series"
#: Where a config's categories are set, in the order they are looked for.
LABEL_NAMES = ("cfg.labels", "cfg.xaxis.categories")
#: JavaScript's plain words, as JSON spells them.
LITERALS = {"true": "true", "false": "false", "null": "null"}
TRAILING_COMMA = re.compile(r",\s*([\]}])")


class NotPlainValue(ValueError):
    """The config's value is computed in the browser, not written out."""


def holds(node: Node) -> bool:
    return MARKER in node.get("x-data")


def read(node: Node) -> dict | None:
    """The card's chart, or None when its config is not plain values."""
    if not holds(node):
        return None
    source = node.get("x-data")
    try:
        series = _value(source, MARKER)
        labels = next(
            (
                found
                for found in (_value(source, name) for name in LABEL_NAMES)
                if found is not None
            ),
            None,
        )
    except NotPlainValue:
        return None
    if not isinstance(series, list) or not isinstance(labels, list) or not labels:
        return None
    heading = node.find(lambda n: n.tag in ("h2", "h3", "h4"))
    title = heading.text() if heading is not None else ""
    return {
        "title": title,
        "subtitle": "",
        "horizontal": True,
        "categories": [str(label) for label in labels],
        "series": _series(series, title),
        "min": 0.0,
        "max": 0.0,
        "axisTitle": "",
    }


def _series(series: list, title: str) -> list[dict]:
    if all(isinstance(v, (int, float)) or v is None for v in series):
        # A donut: one figure per label.
        return [{"name": title, "values": [_number(v) for v in series]}]
    return [
        {
            "name": str(line.get("name", "")),
            "values": [_number(v) for v in line.get("data") or []],
        }
        for line in series
        if isinstance(line, dict)
    ]


def _number(value) -> float:
    # A reading with no value draws no bar.
    return float(value) if isinstance(value, (int, float)) else 0.0


def _value(source: str, name: str):
    """The plain value assigned to ``name`` in ``source``, or None when it is
    not assigned; NotPlainValue when it is computed."""
    found = re.search(re.escape(name) + r"\s*=\s*", source)
    if found is None:
        return None
    start = found.end()
    if start >= len(source) or source[start] not in "[{":
        raise NotPlainValue(name)
    return _from_js(_balanced(source, start))


def _balanced(source: str, start: int) -> str:
    """The bracketed literal starting at ``start``, strings respected."""
    depth = 0
    quote = ""
    index = start
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise NotPlainValue("unbalanced")


def _from_js(literal: str):
    """A JavaScript array or object of plain values, as Python values."""
    out: list[str] = []
    index = 0
    while index < len(literal):
        char = literal[index]
        if char in "'\"":
            text, index = _string(literal, index)
            out.append(json.dumps(text))
            continue
        if char.isalpha() or char in "_$":
            end = index
            while end < len(literal) and (
                literal[end].isalnum() or literal[end] in "_$"
            ):
                end += 1
            word = literal[index:end]
            rest = literal[end:].lstrip()
            if rest.startswith(":") and not rest.startswith("::"):
                out.append(json.dumps(word))
            elif word in LITERALS:
                out.append(LITERALS[word])
            else:
                raise NotPlainValue(word)
            index = end
            continue
        out.append(char)
        index += 1
    try:
        return json.loads(TRAILING_COMMA.sub(r"\1", "".join(out)))
    except ValueError as error:
        raise NotPlainValue("not JSON") from error


def _string(literal: str, start: int) -> tuple[str, int]:
    quote = literal[start]
    parts: list[str] = []
    index = start + 1
    while index < len(literal):
        char = literal[index]
        if char == "\\" and index + 1 < len(literal):
            parts.append(literal[index + 1])
            index += 2
            continue
        if char == quote:
            return "".join(parts), index + 1
        parts.append(char)
        index += 1
    raise NotPlainValue("unterminated string")
