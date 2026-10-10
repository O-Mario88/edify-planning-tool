"""The insight rail: a profile's short reads, in a column beside its tables.

Owner, 2026-10-10, of the Staff Activity Log's Team Insights column: "I like
the second column, can you apply on the profiles majorly ... I feel like ssa
performance and other short and small cards can use the second right column."

A profile's wide things (tables, charts, the KPI strip) keep the main column.
What is short — the SSA score and each intervention's, what needs attention,
how the schools moved, how much of the year's work is done — sits in a rail
beside them on every tab, so the reader does not lose it when the tab
changes. Below a laptop's width the rail lies above the tab's content as a
row of the same parts.

`build` only arranges what `profile_intelligence.build` already counted, so a
rail figure is the profile's own figure, and every line opens the tab or the
records it counted (`tab_url`, `records_url`): no figure here is typed, stored
or worked out a second way.
"""

from __future__ import annotations

from collections.abc import Callable

__all__ = ["build"]

#: An SSA score is out of this.
_SCALE = 10


def _signed(value, places: int = 2) -> str:
    return f"{value:+.{places}f}" if value else f"{0:.{places}f}"


def _share(done: int, of: int) -> int:
    return round(done * 100 / of) if of else 0


def build(
    profile: dict,
    *,
    tab_url: Callable[..., str],
    records_url: Callable[..., str],
    lead: tuple[dict, ...] = (),
) -> dict:
    """The rail of ``profile``. ``tab_url(section, show="")`` is the address
    of one of the profile's sections (`schools`, `ssa`, `activities`, …) and
    ``records_url(what, key="")`` that of a figure's records. ``lead`` are
    parts a page puts first (a cluster's own contacts, say)."""
    ssa = profile["ssa"]
    portfolio = profile["portfolio"]
    execution = profile["execution"]
    current = ssa["current"] or 0
    change = ssa["overall"]["change"]

    meters = [
        {
            "label": row["label"],
            "value": f"{row['current'] or 0:.1f}",
            "share": round((row["current"] or 0) * 100 / _SCALE),
            "href": records_url("intervention", row["key"]),
            "tone": row.get("tone", ""),
        }
        for row in ssa["rows"]
    ]
    attention = [
        {
            "label": item["text"],
            "href": records_url(item["what"])
            if item["what"]
            else tab_url(item["tab"], item["show"]),
            "key": item["show"] or item["what"] or item["tab"],
        }
        for item in profile["attention"]
    ]
    schools = [
        {
            "label": "Assessed this year",
            "value": f"{portfolio['assessed']:,} of {portfolio['schools']:,}",
            "href": records_url("ssa"),
        },
        {
            "label": "SSA improved",
            "value": f"{portfolio['improved']:,}",
            "href": tab_url("schools", "improved"),
            "tone": "success" if portfolio["improved"] else "",
        },
        {
            "label": "SSA declined",
            "value": f"{portfolio['declined']:,}",
            "href": tab_url("schools", "declined"),
            "tone": "danger" if portfolio["declined"] else "",
        },
        {
            "label": "No SSA this year",
            "value": f"{portfolio['no_ssa']:,}",
            "href": tab_url("schools", "no_ssa"),
        },
        {
            "label": "Nothing planned",
            "value": f"{portfolio['unplanned']:,}",
            "href": tab_url("schools", "unplanned"),
        },
        {
            "label": "Awaiting a partner's date",
            "value": f"{portfolio['awaiting_partner']:,}",
            "href": tab_url("schools", "awaiting_partner"),
        },
    ]
    work = [
        {
            "label": label,
            "value": f"{execution[key]['completed']:,} / {execution[key]['planned']:,}",
            "share": _share(execution[key]["completed"], execution[key]["planned"]),
            "href": records_url(key),
        }
        for key, label in (
            ("visits", "School visits"),
            ("trainings", "Trainings"),
            ("meetings", "Cluster meetings"),
        )
    ]
    return {
        "title": "Profile Insights",
        "period": profile["fy_label"]
        + (f" · {profile['period_label']}" if profile.get("period_label") else ""),
        "parts": [
            *lead,
            {
                "key": "ssa",
                "title": "SSA Performance",
                "figure": f"{current:.2f}",
                "figure_href": tab_url("ssa"),
                "figure_note": (
                    f"baseline {ssa['previous'] or 0:.2f} · "
                    f"{_signed(change)} since {profile['previous_label']}"
                ),
                "meters": meters,
                "note": f"Each intervention out of {_SCALE}; a line opens its schools.",
            },
            {
                "key": "attention",
                "title": "Needs Attention",
                "links": attention,
                "empty": f"Nothing needs attention in {profile['fy_label']}.",
            },
            {"key": "schools", "title": "Schools", "rows": schools},
            {
                "key": "work",
                "title": "Work Completed Of The Plan",
                "meters": work,
            },
        ],
    }
