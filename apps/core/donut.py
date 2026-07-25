"""Concentric-ring donut geometry.

One ring per series, each on its own radius, drawn clockwise from twelve
o'clock with a rounded cap — rather than a single ring cut into segments. The
arithmetic lives here because a Django template cannot compute a radius, a
circumference or a dash offset, and doing it in the view would repeat it at
every call site.

Nothing here invents a number: a series with no value renders as no arc, and
`share_of` is the caller's own denominator, so an empty dataset produces an
empty ring set rather than a full circle of zeroes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Tuned against the reference: the rings occupy a shallow outer band and leave
# the middle clear, because the headline lives there. Four rings at a wider
# step march inward far enough to collide with it.
DEFAULT_SIZE = 300
DEFAULT_STROKE = 12
DEFAULT_GAP = 5
DEFAULT_MARGIN = 30  # room outside the widest ring for its value label
# Share of the radius kept clear in the middle for the headline.
MIN_CLEAR_CENTRE = 0.38


@dataclass
class Ring:
    """One series, resolved to the geometry the template needs."""

    key: str
    label: str
    value: float
    color: str
    radius: float
    circumference: float
    dash: str
    display: str
    percent: float
    label_x: float
    label_y: float
    has_arc: bool = field(default=True)


def build_rings(
    series,
    *,
    share_of: float | None = None,
    size: int = DEFAULT_SIZE,
    stroke: int = DEFAULT_STROKE,
    gap: int = DEFAULT_GAP,
    margin: int = DEFAULT_MARGIN,
) -> dict:
    """Resolve `series` into concentric ring geometry.

    `series` is an iterable of dicts with `key`, `label`, `value` and `color`,
    and an optional `display` — the string to print on the ring and its chip.
    Money needs it: a raw 13152000 on a ring is unreadable where "UGX 13.2M"
    is not. Without it the value prints as-is.
    `share_of` is the denominator each value is a share of; when omitted the
    largest value is used, so the biggest ring reads full and the rest are
    proportional to it.

    Returns the viewBox, centre, and one Ring per series — outermost first, so
    the first series is the most prominent.
    """
    items = [s for s in series if s is not None]
    centre = size / 2

    denominator = share_of
    if denominator is None:
        values = [float(s.get("value") or 0) for s in items]
        denominator = max(values) if values else 0

    rings: list[Ring] = []
    for index, item in enumerate(items):
        radius = centre - margin - index * (stroke + gap)
        # The middle is reserved for the headline. A ring that reaches into it
        # sits under the number and its value label lands on top of it, so the
        # ring is dropped rather than drawn illegibly — the legend below still
        # carries the series and its value.
        if radius - stroke / 2 <= centre * MIN_CLEAR_CENTRE:
            break

        value = float(item.get("value") or 0)
        percent = (value / denominator * 100) if denominator else 0.0
        percent = max(0.0, min(100.0, percent))
        circumference = 2 * math.pi * radius
        arc = circumference * percent / 100

        rings.append(
            Ring(
                key=str(item.get("key") or item.get("label") or index),
                label=str(item.get("label") or ""),
                value=value,
                color=str(item.get("color") or "currentColor"),
                display=str(
                    item["display"]
                    if item.get("display") not in (None, "")
                    else (int(value) if float(value).is_integer() else value)
                ),
                radius=round(radius, 2),
                circumference=round(circumference, 2),
                # An arc of 0 must not render a rounded cap sitting at twelve
                # o'clock pretending to be a sliver of progress.
                dash=f"{round(arc, 2)} {round(circumference - arc, 2)}",
                percent=round(percent, 1),
                # The value sits just outside its own ring's twelve o'clock,
                # which is what stacks the labels the way the reference does.
                label_x=round(centre - 11, 2),
                label_y=round(centre - radius, 2),
                has_arc=arc > 0.01,
            )
        )

    return {
        "size": size,
        "centre": round(centre, 2),
        "stroke": stroke,
        "rings": rings,
    }


# A gauge is one ring at list scale: no legend, no value label outside the
# arc — the centre already carries the number — so it needs no room for one.
GAUGE_SIZE = 100
GAUGE_STROKE = 9
GAUGE_MARGIN = 6


def build_gauge(
    value,
    *,
    label: str,
    color: str,
    share_of: float | None = 100,
    display: str | None = None,
) -> dict:
    """One-series ring, sized for a table cell or a card corner.

    Returns the same shape as `build_rings`, so the same template renders it;
    `share_of` defaults to 100 because the usual caller already holds a
    percentage. Pass `None` for a value with no known denominator and the ring
    reads full — which is why every caller here passes one.
    """
    return build_rings(
        [{"key": "gauge", "label": label, "value": value, "color": color,
          "display": display}],
        share_of=share_of,
        size=GAUGE_SIZE,
        stroke=GAUGE_STROKE,
        margin=GAUGE_MARGIN,
    )
