"""A grid of small cards (My Targets' strategic priorities and their kin),
read as one record card each: the card's eyebrow and description under its
name, its status pills beside it, its figures as "Label: value" pairs, and
its link as the card's own page.

The web lays these out as a grid of bordered tiles (``<ol class="grid">``
of ``<li class="rounded-surface border">``); without this the phone got each
tile's parts as separate untitled panels.
"""

from __future__ import annotations

import re

from apps.mobile_feed.page_blocks import Node

#: A tile's colour, by the Tailwind hue in its pill's classes.
PILL_TONES = (
    (re.compile(r"\b(?:bg|text)-(?:emerald|green)-"), "good"),
    (re.compile(r"\b(?:bg|text)-(?:amber|yellow|orange)-"), "caution"),
    (re.compile(r"\b(?:bg|text)-(?:red|rose)-"), "alert"),
    (re.compile(r"\b(?:bg|text)-(?:sky|blue|indigo)-"), "info"),
)
HEADINGS = ("h3", "h4")
#: The words a pill holds at most; a longer rounded span is a sentence.
MAX_PILL_WORDS = 4
MIN_CARDS = 2
#: A small card's words at most: a name, a pill, a line and a few figures.
MAX_CARD_WORDS = 40
#: Parts that make a tile more than a small card: read inside instead.
NOT_SMALL = ("table", "form", "dialog")


def is_grid(node: Node) -> bool:
    """Whether ``node`` is a grid of at least two small cards of one kind."""
    if node.tag not in ("ol", "ul", "div") or not node.has("grid"):
        return False
    cards = [child for child in node.children if isinstance(child, Node)]
    if len(cards) < MIN_CARDS or len({card.tag for card in cards}) != 1:
        return False
    return all(_is_card(card) for card in cards)


def _is_card(node: Node) -> bool:
    if not node.has("border") or not any(
        name.startswith("rounded") for name in node.classes
    ):
        return False
    # A full surface (a section card with its own list) is read on its own.
    if node.has("edify-surface") or len(node.text().split()) > MAX_CARD_WORDS:
        return False
    if node.find(lambda n: n.tag in NOT_SMALL or n.has("edify-data-chart")):
        return False
    return len(node.find_all(lambda n: n.tag in HEADINGS)) == 1


def read(node: Node) -> list[dict]:
    """The grid's cards as records, in order."""
    return [_record(card) for card in node.children if isinstance(card, Node)]


def _record(card: Node) -> dict:
    from apps.mobile_feed import page_blocks

    heading = card.find(lambda n: n.tag in HEADINGS)
    strips = card.find_all(lambda n: n.has("context-metrics"))
    pills = card.find_all(_is_pill)
    parts = (heading, *strips, *pills)
    taken = {id(part) for part in parts} | {
        id(n) for part in parts for n in part.nodes()
    }
    eyebrow, description = _lines(card, heading, taken)
    return {
        "title": heading.text(),
        "href": _href(card, heading),
        "subtitle": " · ".join(part for part in (eyebrow, description) if part),
        "badges": [
            {"text": pill.text(), "tone": _tone(pill), "title": pill.get("title")}
            for pill in pills
        ],
        "actions": [],
        "facts": [
            {
                "label": metric["label"],
                "value": metric["value"],
                "href": metric["href"],
                "tone": metric["tone"],
            }
            for strip in strips
            for metric in page_blocks._strip(strip)["metrics"]
            if metric["label"] or metric["value"]
        ],
        "details": [],
        "detailsPath": "",
    }


def _is_pill(node: Node) -> bool:
    return (
        node.tag == "span"
        and (node.has("rounded-full") or node.has("rounded-pill"))
        and 0 < len(node.text().split()) <= MAX_PILL_WORDS
    )


def _tone(pill: Node) -> str:
    classes = " ".join(sorted(pill.classes))
    return next(
        (tone for pattern, tone in PILL_TONES if pattern.search(classes)), "plain"
    )


def _lines(card: Node, heading: Node, taken: set[int]) -> tuple[str, str]:
    """The card's loose text: the line before its name (the eyebrow) and the
    sentences after it (the description)."""
    before: list[str] = []
    after: list[str] = []
    is_after = False
    for leaf in card.nodes():
        if leaf is heading:
            is_after = True
        if id(leaf) in taken or not isinstance(leaf, Node):
            continue
        if leaf.tag in ("script", "style", "template") or any(
            isinstance(child, Node) for child in leaf.children
        ):
            continue
        text = leaf.text()
        if text:
            (after if is_after else before).append(text)
    return " ".join(before), " ".join(after)


def _href(card: Node, heading: Node) -> str:
    """The card's own page: its name's link, the card itself, or its one link."""
    link = heading if heading.tag == "a" else heading.find(lambda n: n.tag == "a")
    if link is None and card.tag == "a":
        link = card
    if link is None:
        links = card.find_all(lambda n: n.tag == "a" and bool(n.get("href")))
        link = links[0] if len(links) == 1 else None
    return link.get("href") if link is not None else ""
