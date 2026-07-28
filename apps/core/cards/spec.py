"""What a card has to declare about itself before it may render.

``manage.py build_card_inventory`` finds 555 titled card surfaces across 202
templates. None carries an identifier. ``templates/components/card.html``
describes itself as "the single source for all card surfaces" and is included
**twice** -- every other card is a hand-rolled stack of utilities, so there is
no component to enumerate, no attribute to key on, and no place a rule could
live.

The consequence is not untidiness. Without an identity per card:

* two cards showing the same records cannot be detected except by comparing
  their wording, which is how the Admin dashboard shipped two identical "Team
  Target Progress" panels 78 lines apart;
* a card cannot state which roles may see it, so scope is enforced only by
  whichever view happens to render it;
* a card cannot declare its drill-down, so nothing can check that the count on
  the card matches the list it links to;
* a card cannot say what it means when it is empty, so an empty card is
  indistinguishable from a broken one.

``CardSpec`` is that identity. Each field is a question that was previously
answered implicitly, and each is checked -- either by ``registry.check()`` or
by the guard tests in ``apps/core/tests/test_card_registry.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from apps.core.metrics.spec import FilterBehaviour, Period
from apps.core.navigation import ALL_ROLES


class CardType(str, Enum):
    """The controlled component family (mandate §10).

    A new card picks one of these. Inventing a type per page is how 555
    hand-rolled surfaces happened.
    """

    KPI = "kpi"
    OPERATIONAL_QUEUE = "operational_queue"
    INSIGHT = "insight"
    RISK = "risk"
    RECOMMENDATION = "recommendation"
    ENTITY_SUMMARY = "entity_summary"
    CHART = "chart"
    COMPARISON = "comparison"
    TIMELINE = "timeline"
    PROGRESS = "progress"
    ACTION = "action"
    CONTEXT = "context"
    PREVIEW = "preview"
    COMPLIANCE = "compliance"
    FINANCIAL = "financial"


# Titles that name no information (mandate §22). A card called "Summary" has
# not said what it summarises.
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


@dataclass(frozen=True)
class CardSpec:
    """One card, defined once, for the whole platform."""

    # ── Identity ─────────────────────────────────────────────────────────────
    key: str
    title: str
    # What the card says, in one sentence. The "communication contract" of §9.
    purpose: str
    # The question the reader opens this card to answer. A card that cannot
    # complete "the reader looks at this in order to ..." is decoration.
    question: str
    card_type: CardType

    # ── Ownership and scope ──────────────────────────────────────────────────
    owner_page: str
    allowed_roles: frozenset[str]
    scope: str

    # ── Data ─────────────────────────────────────────────────────────────────
    service: str
    source_models: tuple[str, ...]
    period: Period
    filter_behaviour: FilterBehaviour

    # ── States (§31, §33, §34) ───────────────────────────────────────────────
    # What the card says when it has no records. Required: an empty card that
    # explains nothing is indistinguishable from one that failed to load.
    empty_message: str

    # ── Optional but load-bearing ────────────────────────────────────────────
    # What the reader should do with what the card says.
    action: str = ""
    # What the card explicitly does *not* mean (§9). Worth stating whenever a
    # reader could reasonably widen the claim.
    does_not_mean: str = ""
    drilldown: str | None = None
    no_drilldown_reason: str | None = None
    # Pages other than the owner that may show this card, each justified by a
    # different role, scope, period, decision or action (§7).
    secondary_pages: tuple[str, ...] = ()
    refresh_events: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.key or self.key != self.key.lower().strip():
            raise ValueError(f"card key must be lower-case and trimmed: {self.key!r}")
        if " " in self.key:
            raise ValueError(f"card key must not contain spaces: {self.key!r}")

        if self.title.strip().casefold() in AMBIGUOUS_TITLES:
            raise ValueError(
                f"{self.key}: {self.title!r} names no information -- say what "
                f"it is a summary/overview/status *of*"
            )
        if not self.question.strip():
            raise ValueError(f"{self.key}: name the question this card answers")
        if not self.purpose.strip():
            raise ValueError(f"{self.key}: state what the card communicates")
        if not self.empty_message.strip():
            raise ValueError(
                f"{self.key}: say what it means when this card has no records; "
                f"a blank card reads as a broken one"
            )

        unknown = set(self.allowed_roles) - ALL_ROLES
        if unknown:
            raise ValueError(f"{self.key}: unknown role(s) {sorted(unknown)}")
        if not self.allowed_roles:
            raise ValueError(f"{self.key}: name the roles allowed to see this card")

        if self.drilldown is None and not self.no_drilldown_reason:
            raise ValueError(
                f"{self.key}: give a drilldown, or say why this card is purely "
                f"contextual"
            )
        if self.drilldown and self.no_drilldown_reason:
            raise ValueError(f"{self.key}: it has a drilldown or it does not")

        if self.owner_page in self.secondary_pages:
            raise ValueError(f"{self.key}: owner_page repeated in secondary_pages")

    def approved_pages(self) -> tuple[str, ...]:
        return (self.owner_page, *self.secondary_pages)

    def visible_to(self, role_slug: str) -> bool:
        return role_slug in self.allowed_roles
