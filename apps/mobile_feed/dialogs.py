"""Dialogs a page opens itself (My Targets' "Submit MSCS"): a part marked
role="dialog", shown while a flag in the page's x-data is true and closed
when the page opens. The page sends each with its blocks, by its flag, and a
button that sets the flag opens it as the app's sheet ("#dialog=<flag>").
"""

from __future__ import annotations

import re

from apps.mobile_feed.page_blocks import Node

#: ``@click="showMscs = true"``.
OPENS = re.compile(r"^\s*(\w+)\s*=\s*true\s*;?\s*$")
#: ``x-show="showMscs"``.
FLAG = re.compile(r"^\s*(\w+)\s*$")
HREF = "#dialog="
HEADINGS = ("h1", "h2", "h3", "h4")


def closed_flag(node: Node) -> str:
    """The flag that opens ``node`` when it is a dialog closed on opening."""
    is_modal = (
        node.get("role") == "dialog"
        or node.get("aria-modal") == "true"
        # A full-screen overlay is a dialog however it is marked.
        or (node.has("fixed") and node.has("inset-0"))
    )
    if not is_modal:
        return ""
    shown = FLAG.match(node.get("x-show"))
    if shown is None:
        return ""
    from apps.mobile_feed import checklists

    holder = node.parent
    while holder is not None and not holder.get("x-data"):
        holder = holder.parent
    if holder is None:
        # A part loaded later holds the dialog without the page's x-data; a
        # cloaked dialog is hidden until its script opens it.
        return shown.group(1) if "x-cloak" in node.attrs else ""
    is_open = checklists.data_value(holder.get("x-data"), shown.group(1))
    return shown.group(1) if is_open is False else ""


def opener_href(node: Node) -> str:
    """``#dialog=<flag>`` for a button that opens a page's dialog."""
    opens = OPENS.match(node.get("@click") or node.get("x-on:click"))
    return f"{HREF}{opens.group(1)}" if opens else ""


def read_all(root: Node) -> list[dict]:
    """The page's closed dialogs: each one's flag, title and blocks — the
    page's own, not the app shell's (its sidebar)."""
    from apps.mobile_feed import page_blocks

    main = root.find(lambda n: n.tag == "main") or root
    read = []
    for dialog in main.find_all(lambda n: bool(closed_flag(n))):
        if any(item["key"] == closed_flag(dialog) for item in read):
            continue  # One sheet per flag: the page drew the dialog twice.
        title = dialog.find(lambda n: n.tag in HEADINGS)
        words = title.text() if title is not None else ""
        blocks = page_blocks._blocks(page_blocks._for_phone(dialog), [])
        read.append(
            {
                "key": closed_flag(dialog),
                "title": words,
                "blocks": [_untitled(block, words) for block in blocks],
            }
        )
    return read


def _untitled(block: dict, title: str) -> dict:
    """A form under the sheet's title does not say it again."""
    form = block.get("form")
    if form is not None and form["title"] == title:
        return {"form": {**form, "title": ""}}
    return block
