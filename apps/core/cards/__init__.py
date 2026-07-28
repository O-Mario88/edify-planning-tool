"""Canonical card definitions for every information surface the platform shows.

Why this package exists
-----------------------

``manage.py build_card_inventory`` finds **555 titled card surfaces across 202
templates**, carrying 525 distinct titles and **not one identifier**.
``templates/components/card.html`` describes itself as "the single source for
all card surfaces" and is included **twice**; everything else is a hand-rolled
stack of utilities.

Without an identity per card, none of the platform's card rules can be checked
by a test:

* Two cards showing the same records can only be spotted by comparing their
  wording. That is how ``pages/dashboards/main.html`` shipped two identical
  "Team Target Progress" panels 78 lines apart, each looping the same
  ``team_targets`` and rendering the same rows -- announced twice to a screen
  reader.
* A card cannot declare which roles may see it, so scope depends on whichever
  view happens to render it.
* A card cannot declare its drill-down, so nothing verifies that its count
  matches the list it links to.
* A card cannot say what it means when empty, so "nothing to do" and "this
  failed to load" look identical.

Usage
-----

    from apps.core.cards import render_card

    card = render_card(
        "admin_priority_schools",
        priority_schools,
        role_slug="ADMIN",
    )

then render it through ``components/registered_card.html``, which stamps
``data-card-key`` and friends and picks the empty or error state for you.
"""

from apps.core.cards.payload import (
    CardNotPermitted,
    RenderedCard,
    render_card,
)
from apps.core.cards.registry import (
    CARD_REGISTRY,
    all_cards,
    cards_for_page,
    cards_for_role,
    check,
    get_card,
)
from apps.core.cards.spec import (
    AMBIGUOUS_TITLES,
    CardSpec,
    CardType,
)

__all__ = [
    "AMBIGUOUS_TITLES",
    "CARD_REGISTRY",
    "CardNotPermitted",
    "CardSpec",
    "CardType",
    "RenderedCard",
    "all_cards",
    "cards_for_page",
    "cards_for_role",
    "check",
    "get_card",
    "render_card",
]
