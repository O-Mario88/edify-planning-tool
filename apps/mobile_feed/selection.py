"""The bar a page shows once rows are ticked (partials/activities/
selection_bar.html, Planning's ticked schools): what it calls the ticks and
the drawers it opens with them. One per page, as on the web; the rows' tick
boxes are each row's pick (page_blocks._pick).

A drawer gets the ticks as one comma-joined ``ids`` (the activity bar) or as
a repeated parameter (``school_ids``) when the web's script fills one hidden
input per tick. A form that posts (Export Selected) answers with a file and
stays on the web.
"""

from __future__ import annotations

import re

from apps.mobile_feed.page_blocks import SILENT, Node

#: ``x-show="selectedSchools.length > 0 && activeView === 'list'"``.
SHOWN_WHEN_TICKED = re.compile(r"^\s*(\w+)\.length\s*>\s*0")
#: ``x-for="sid in selectedSchools"``.
FOR_EACH_TICK = re.compile(r"^\s*\w+\s+in\s+(\w+)\s*$")


def read(root: Node) -> dict | None:
    bar = root.find(lambda n: "data-activity-bar" in n.attrs) or root.find(
        _is_school_bar
    )
    if bar is None:
        return None
    actions = [
        action
        for form in bar.find_all(lambda n: n.tag == "form" and bool(n.get("hx-get")))
        if (action := _action(form)) is not None
    ]
    if not actions:
        return None
    return {"noun": _noun(bar), "actions": actions}


def is_bar(node: Node) -> bool:
    return "data-activity-bar" in node.attrs or _is_school_bar(node)


def _is_school_bar(node: Node) -> bool:
    shown = SHOWN_WHEN_TICKED.match(node.get("x-show"))
    return (
        shown is not None
        and node.find(lambda n: n.tag == "form" and bool(n.get("hx-get"))) is not None
    )


def _action(form: Node) -> dict | None:
    submit = form.find(lambda n: n.tag == "button")
    joined = form.find(
        lambda n: n.tag == "input"
        and n.get("type").lower() == "hidden"
        and n.get("name") == "ids"
    )
    each = form.find(
        lambda n: n.tag == "template" and FOR_EACH_TICK.match(n.get("x-for"))
    )
    each_input = each.find(lambda n: n.tag == "input") if each is not None else None
    if submit is None or (joined is None and each_input is None):
        return None
    return {
        "label": _words(submit),
        "href": form.get("hx-get"),
        "param": "ids" if joined is not None else each_input.get("name"),
        "joined": joined is not None,
    }


def _noun(bar: Node) -> str:
    marked = bar.find(lambda n: "data-activity-noun" in n.attrs)
    if marked is not None:
        return marked.text()
    said = bar.find(
        lambda n: n.tag == "span" and "selected" in n.text() and not n.get("x-text")
    )
    return said.text() if said is not None else "selected"


def _words(button: Node) -> str:
    """A button's words in order, its icon and screen-reader-only parts aside."""
    parts = [
        child if isinstance(child, str) else child.text()
        for child in button.children
        if isinstance(child, str)
        or (child.tag not in SILENT and not child.has("sr-only"))
    ]
    return " ".join(" ".join(parts).split())
