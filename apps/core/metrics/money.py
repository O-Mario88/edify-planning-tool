"""The one compact-UGX formatter for money shown on a KPI tile.

Twelve private copies of this function existed, and they disagreed. Three that
were compared directly:

    UGX 1,234,567  ->  "UGX 1.2M"   (fund_requests/pl_approval_service._ugx)
                       "UGX 1.2M"   (frontend/views/finance_operating_views)
                       "UGX 1.23M"  (frontend/views/budget_views)

    UGX 2,500      ->  "UGX 2K"     /  "UGX 2K"  /  "UGX 2.50K"

`finance_operating_views.format_ugx_compact` even carried the docstring "same
as apps/frontend/views/budget_views.py", which was not true at either the
million or the billion scale.

The chosen precision is one decimal place at M and B and none at K. Compact
notation exists to make a magnitude scannable; "UGX 2.50K" spends three
characters to say "about two thousand", and a second decimal at the million
scale implies a precision the underlying figure rarely has. Callers that need
the exact number should show the exact number -- `format_value` in
`apps.core.metrics.payload` renders full `UGX 1,234,567`.
"""

from __future__ import annotations

BILLION = 1_000_000_000
MILLION = 1_000_000
THOUSAND = 1_000


def format_ugx_compact(amount: int | float | None) -> str:
    """Compact UGX for a KPI tile: `UGX 1.2M`, `UGX 850K`, `UGX 640`.

    ``None`` and ``0`` both render as ``UGX 0``. That is deliberate here and
    *not* a data-state decision: a caller that needs to distinguish "no
    requests exist" from "requests totalling zero" must carry a
    ``MetricValue`` and let ``render_metric`` say so in words. This function
    only formats a number it has been given.
    """
    value = int(amount or 0)
    negative = value < 0
    magnitude = abs(value)

    if magnitude >= BILLION:
        text = f"UGX {magnitude / BILLION:.1f}B"
    elif magnitude >= MILLION:
        text = f"UGX {magnitude / MILLION:.1f}M"
    elif magnitude >= THOUSAND:
        text = f"UGX {magnitude / THOUSAND:.0f}K"
    else:
        text = f"UGX {magnitude:,}"

    return f"-{text}" if negative else text
