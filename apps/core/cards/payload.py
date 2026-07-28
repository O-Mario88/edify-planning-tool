"""Binds a registered card to its records, ready for the shared card shell.

The template must not decide whether a card is empty, whether the reader is
allowed to see it, or what its title is. All three come from the registry, so
that the guard tests and the rendered page cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from apps.core.cards.registry import get_card
from apps.core.cards.spec import CardSpec


class CardNotPermitted(Exception):
    """A role asked for a card its registry entry does not allow it to see."""


@dataclass(frozen=True)
class RenderedCard:
    """Everything the shared card shell needs, and nothing it should infer."""

    card_key: str
    title: str
    purpose: str
    question: str
    card_type: str
    scope: str
    period: str
    records: Sequence[Any]
    is_empty: bool
    empty_message: str
    error: str | None
    drilldown_url: str | None
    does_not_mean: str

    def as_dict(self) -> dict:
        return {
            "card_key": self.card_key,
            "title": self.title,
            "purpose": self.purpose,
            "question": self.question,
            "card_type": self.card_type,
            "scope": self.scope,
            "period": self.period,
            "records": self.records,
            "is_empty": self.is_empty,
            "empty_message": self.empty_message,
            "error": self.error,
            "drilldown_url": self.drilldown_url,
            "does_not_mean": self.does_not_mean,
        }


def render_card(
    key: str,
    records: Sequence[Any] | None = None,
    *,
    role_slug: str | None = None,
    error: str | None = None,
    drilldown_url: str | None = None,
) -> RenderedCard:
    """Bind records to a registered card.

    ``role_slug`` is checked against the registry when supplied, so a card
    cannot leak onto a page for a role its own definition excludes. Passing
    ``None`` skips the check for callers that have already gated the whole page.
    """
    spec: CardSpec = get_card(key)

    if role_slug is not None and not spec.visible_to(role_slug):
        raise CardNotPermitted(
            f"{key} is not available to {role_slug}; allowed: "
            f"{sorted(spec.allowed_roles)}"
        )

    rows = list(records or ())
    return RenderedCard(
        card_key=spec.key,
        title=spec.title,
        purpose=spec.purpose,
        question=spec.question,
        card_type=spec.card_type.value,
        scope=spec.scope,
        period=spec.period.value,
        records=rows,
        # An errored card is not an empty one: "nothing to do" and "we could
        # not find out" must not render the same reassuring message (§34).
        is_empty=not rows and error is None,
        empty_message=spec.empty_message,
        error=error,
        drilldown_url=drilldown_url or spec.drilldown,
        does_not_mean=spec.does_not_mean,
    )
