"""A machine-readable inventory of every card-like surface in the templates.

Companion to ``page_inventory`` and ``kpi_inventory``, and built the same way:
from the source, so it cannot drift away from the product.

What counts as a card here
--------------------------

``templates/components/card.html`` calls itself "the single source for all card
surfaces". It is included **twice** in 875 templates. Every other card is a
hand-rolled stack of utilities -- ``edify-surface rounded-surface border
border-slate-100 shadow-sm p-5 space-y-3`` and a hundred near-identical
variants -- so there is no component to enumerate and no attribute to key on.

This scan therefore treats a card as *a bordered surface that introduces itself
with a heading*. A surface with no heading is a layout wrapper, not an
information card, and counting those would bury the real surface in noise.

The heading is what makes the card auditable: it is the card's claim about what
it contains, and it is what two cards must not share on one page.

Findings are evidence for review, not a verdict. Two cards sharing a title on
one page is a question -- "is this one card rendered twice, a desktop/mobile
pair, or two different things badly named?" -- and only reading the page
answers it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from django.conf import settings


PROJECT_ROOT = Path(settings.BASE_DIR)
TEMPLATE_ROOT = PROJECT_ROOT / "templates"

# A bordered information surface. `edify-surface` is the platform background,
# `rounded-surface` the shared radius; `card`/`panel` catch the older families.
_SURFACE_RE = re.compile(
    r"""<(?P<tag>div|section|article|aside)\b[^>]*\bclass="(?P<cls>[^"]*)\"""",
    re.IGNORECASE,
)
_SURFACE_HINT = re.compile(
    r"\b(edify-surface|rounded-surface|card|panel)\b", re.IGNORECASE
)
# Surfaces that are chrome rather than information containers.
_NOT_A_CARD = re.compile(
    r"\b(card__|panel__|card-slot|card-row|kpi-strip|admin-kpi|legacy-kpi|kpi-card)",
    re.I,
)

# Decoration and controls that borrow a card's rounding or background: icon
# discs, status pills, avatars, buttons, and anything pinned to a small fixed
# box. Note `w-\d+` rather than `w-\d` -- the trailing word boundary in the
# latter cannot match inside `w-12`, which let every 3rem icon wrapper on the
# platform be counted as an untitled card.
_CHROME_RE = re.compile(
    r"\b(w-\d+|h-\d+|size-\d+|rounded-pill|avatar|icon|badge|chip|pill|btn|"
    r"button|shrink-0|inline-flex|absolute|sr-only|hidden)\b",
    re.IGNORECASE,
)
# How far above a surface a heading may sit and still be understood as titling
# the card this surface is a region *inside*.
_PARENT_HEADING_LINES = 40

_HEADING_RE = re.compile(
    r"<h(?P<level>[1-6])\b[^>]*>(?P<text>.*?)</h(?P=level)>", re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")
_DJANGO_RE = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.DOTALL)

# How far below a surface's opening tag its heading may sit before the two are
# considered unrelated.
_HEADING_WINDOW_LINES = 10

# Titles that name no information (mandate §22). "Overview" and "Summary" are
# the two that appear most; each needs to say what it is an overview *of*.
AMBIGUOUS_TITLES = frozenset(
    {
        "activity",
        "budget",
        "details",
        "information",
        "insights",
        "overview",
        "performance",
        "progress",
        "status",
        "summary",
    }
)


def _clean(text: str) -> str:
    """Heading text with tags and template syntax removed.

    Returns "" when nothing nameable survives. Some headings hold a *value*
    rather than a title -- ``<h3>{{ period.achieved }} / {{ period.target }}</h3>``
    on the Reports page -- and stripping the template syntax leaves only "/".
    That is a KPI figure wearing a heading tag, not a card title, and treating
    it as one reported two Reports cards as sharing the title "/".
    """
    text = _DJANGO_RE.sub("", text)
    text = _TAG_RE.sub(" ", text)
    cleaned = " ".join(text.split())
    return cleaned if re.search(r"[A-Za-z]", cleaned) else ""


@dataclass
class CardSite:
    template: str
    line: int
    title: str
    heading_level: int
    has_card_key: bool
    classes: str
    # Which branch of which enclosing conditional this card sits in, as
    # (block id, branch index) pairs -- so a card in the `{% if %}` arm and one
    # in the `{% else %}` arm of the same block are known to be alternatives.
    branch_path: tuple[tuple[int, int], ...] = ()

    @property
    def title_key(self) -> str:
        return self.title.casefold().strip(" :·—-")


@dataclass
class CardInventory:
    cards: list[CardSite] = field(default_factory=list)
    # Surfaces that look like cards but never introduce themselves, split by
    # *why*. Reporting one large "untitled" number invites the reading that a
    # thousand cards went unaudited; classifying it shows that almost none of
    # them are cards at all.
    #
    #   chrome    -- icon discs, pills, avatars, buttons: decoration borrowing
    #                a card's rounding or background.
    #   nested    -- a region inside a card that the parent's heading already
    #                titles (a scrollable list, a bordered sub-panel).
    #   headless  -- a surface with no heading above or below it. These are the
    #                only genuine §22 candidates: a card that never says what
    #                it contains.
    untitled_chrome: int = 0
    untitled_nested: int = 0
    untitled_headless: int = 0

    @property
    def untitled_surfaces(self) -> int:
        return self.untitled_chrome + self.untitled_nested + self.untitled_headless

    def _renders_together(self, first: "CardSite", second: "CardSite") -> bool:
        """Do two same-titled cards ever appear on screen at once?

        A card and its empty state share a title by design --
        ``{% if selected %}`` renders the populated card and ``{% else %}`` the
        "Select a conversation…" one. They are the same card, and §31 asks for
        exactly that pairing.

        The test has to be about *branches of the same conditional*, not about
        any intervening ``{% else %}``. An earlier version asked only whether a
        branch keyword fell between the two lines, which any unrelated
        ``{% if %}`` elsewhere on the page satisfies -- and that suppressed the
        genuine duplicate on the Admin dashboard, where two identical "Team
        Target Progress" cards sat 78 lines and several unrelated conditionals
        apart. Missing a real duplicate is worse than reporting a false one.
        """
        shared = dict(first.branch_path).keys() & dict(second.branch_path).keys()
        a, b = dict(first.branch_path), dict(second.branch_path)
        return not any(a[block] != b[block] for block in shared)

    def duplicate_titles_within_a_template(self) -> dict[str, list[str]]:
        """Two cards claiming the same thing on one page (mandate §6).

        Keyed by template, because "the same page" is what the rule is about.
        """
        out: dict[str, list[str]] = {}
        by_template: dict[str, dict[str, list[CardSite]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for card in self.cards:
            if card.title_key:
                by_template[card.template][card.title_key].append(card)

        for template, titles in sorted(by_template.items()):
            repeated = sorted(
                title
                for title, sites in titles.items()
                if len(sites) > 1
                and any(
                    self._renders_together(a, b)
                    for i, a in enumerate(sites)
                    for b in sites[i + 1 :]
                )
            )
            if repeated:
                out[template] = repeated
        return out

    def titles_used_in_several_templates(self) -> dict[str, list[str]]:
        by_title: dict[str, set[str]] = defaultdict(set)
        for card in self.cards:
            if card.title_key:
                by_title[card.title_key].add(card.template)
        return {
            title: sorted(templates)
            for title, templates in sorted(by_title.items())
            if len(templates) > 1
        }

    def ambiguous_titles(self) -> list[CardSite]:
        return [c for c in self.cards if c.title_key in AMBIGUOUS_TITLES]

    def summary(self) -> dict:
        return {
            "titled_cards": len(self.cards),
            "templates": len({c.template for c in self.cards}),
            "distinct_titles": len({c.title_key for c in self.cards if c.title_key}),
            "with_card_key": sum(1 for c in self.cards if c.has_card_key),
            "untitled_surfaces": self.untitled_surfaces,
            "untitled_chrome": self.untitled_chrome,
            "untitled_nested": self.untitled_nested,
            "untitled_headless": self.untitled_headless,
            "templates_with_same_title_twice": len(
                self.duplicate_titles_within_a_template()
            ),
            "titles_in_several_templates": len(self.titles_used_in_several_templates()),
            "ambiguous_titles": len(self.ambiguous_titles()),
        }

    def as_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "same_page_duplicate_titles": self.duplicate_titles_within_a_template(),
            "titles_in_several_templates": self.titles_used_in_several_templates(),
            "ambiguous_titles": [asdict(c) for c in self.ambiguous_titles()],
            "cards": [asdict(c) for c in self.cards],
        }


_BRANCH_TAG_RE = re.compile(r"\{%\s*(if|elif|else|endif)\b")


def _branch_paths_by_line(source: str) -> dict[int, tuple[tuple[int, int], ...]]:
    """For each line, the (conditional block, branch index) pairs enclosing it."""
    paths: dict[int, tuple[tuple[int, int], ...]] = {}
    stack: list[list[int]] = []  # [block id, current branch index]
    next_block_id = 0
    cursor = 0

    for match in _BRANCH_TAG_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        for ln in range(cursor, line + 1):
            paths[ln] = tuple((b, i) for b, i in stack)
        cursor = line + 1

        keyword = match.group(1)
        if keyword == "if":
            stack.append([next_block_id, 0])
            next_block_id += 1
        elif keyword in ("elif", "else") and stack:
            stack[-1][1] += 1
        elif keyword == "endif" and stack:
            stack.pop()

    for ln in range(cursor, source.count("\n") + 2):
        paths[ln] = tuple((b, i) for b, i in stack)
    return paths


def _has_identity(source: str, tag_start: int) -> bool:
    """Does the element opening at `tag_start` carry a registry identity?

    The attributes usually arrive through
    ``{% include "components/registered_card_attrs.html" %}`` rather than as a
    literal `data-card-key`, and they sit *after* the class attribute -- so
    looking only at the matched `class="…"` text reported every migrated card
    as unregistered.
    """
    end = source.find(">", tag_start)
    opening = source[tag_start : end if end != -1 else tag_start + 800]
    return "data-card-key" in opening or "registered_card_attrs.html" in opening


def _headings_by_line(source: str) -> dict[int, tuple[int, str]]:
    found: dict[int, tuple[int, str]] = {}
    for match in _HEADING_RE.finditer(source):
        line = source[: match.start()].count("\n") + 1
        text = _clean(match.group("text"))
        if text:
            found.setdefault(line, (int(match.group("level")), text))
    return found


def build_inventory() -> CardInventory:
    inventory = CardInventory()

    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        template = path.relative_to(PROJECT_ROOT).as_posix()
        headings = _headings_by_line(source)
        branch_paths = _branch_paths_by_line(source)

        # A heading belongs to exactly one card. Cards nest -- an icon wrapper,
        # a flex row and the card itself may all carry a surface-ish class, and
        # every one of them sees the same <h3> inside its window. Claiming each
        # heading once, for the outermost surface that reaches it, is what stops
        # one card being reported as three and sending a reader to "de-duplicate"
        # a page that was never duplicated.
        claimed: set[int] = set()

        for match in _SURFACE_RE.finditer(source):
            classes = match.group("cls")
            if not _SURFACE_HINT.search(classes) or _NOT_A_CARD.search(classes):
                continue

            line = source[: match.start()].count("\n") + 1
            heading_line = next(
                (
                    candidate
                    for candidate in range(line, line + _HEADING_WINDOW_LINES + 1)
                    if candidate in headings and candidate not in claimed
                ),
                None,
            )
            if heading_line is None:
                if _CHROME_RE.search(classes):
                    inventory.untitled_chrome += 1
                elif any(
                    candidate in headings
                    for candidate in range(max(1, line - _PARENT_HEADING_LINES), line)
                ):
                    inventory.untitled_nested += 1
                else:
                    inventory.untitled_headless += 1
                continue
            claimed.add(heading_line)
            heading = headings[heading_line]

            level, title = heading
            inventory.cards.append(
                CardSite(
                    template=template,
                    line=line,
                    title=title,
                    heading_level=level,
                    has_card_key=_has_identity(source, match.start()),
                    classes=" ".join(classes.split())[:160],
                    branch_path=branch_paths.get(heading_line, ()),
                )
            )

    return inventory
