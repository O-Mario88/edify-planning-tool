"""The Cluster Page's operational summary.

Owner's brief, 2026-10-10: "The Cluster Page manages the cluster. The Cluster
Profile explains the cluster." The page answers "what does the CCEO need to
manage or act on now?": the running year's work (in the plan, completed,
upcoming, past its date), the schools that need something, and one compact
SSA figure that opens the profile's deep read.

Every number is the profile engine's own (`apps.analytics.profile_intelligence`
over the cluster's schools, for the running year) plus the attendance
register's run of missed sessions, so a figure on the page and the same
figure on the profile cannot differ; each opens the list it counted.
"""

from __future__ import annotations

from urllib.parse import quote

__all__ = ["operational_summary"]

#: Where an engine section is on the Cluster Profile's address.
_TAB_OF = {
    "schools": "school_ssa",
    "activities": "work",
    "ssa": "ssa",
    "overview": "portfolio",
}
_WORK = ("visits", "trainings", "meetings")


def operational_summary(cluster) -> dict:
    """What the Cluster Page shows above its roster, for the running year."""
    from apps.analytics import profile_intelligence as engine
    from apps.clusters import profile_insights as insights

    from apps.core.fy import get_operational_fy

    profile = engine.build(engine.cluster_scope(cluster), str(get_operational_fy()))
    fy = profile["fy"]
    base = f"/clusters/{quote(str(cluster.id))}/profile"
    records = f"{base}?fy={fy}&what="
    execution = profile["execution"]

    def total(key: str) -> int:
        return sum(execution[kind][key] for kind in _WORK)

    def parts(key: str) -> str:
        return (
            f"{execution['visits'][key]:,} visits · "
            f"{execution['trainings'][key]:,} trainings · "
            f"{execution['meetings'][key]:,} meetings"
        )

    attention = []
    for item in profile["attention"]:
        href = (
            f"{records}{item['what']}"
            if item["what"]
            else f"{base}?tab={_TAB_OF.get(item['tab'], item['tab'])}&fy={fy}"
            + (f"&show={item['show']}" if item["show"] else "")
        )
        attention.append(
            {
                "text": item["text"],
                "href": href,
                "key": item["show"] or item["what"] or item["tab"],
            }
        )
    # Schools that missed the cluster's sessions three times running: the
    # register's own alert, which the profile's Meetings tab lists.
    drifting = len(insights.cluster_attendance(cluster, fy=fy)["drifting"])
    if drifting:
        attention.append(
            {
                "text": f"{drifting:,} school"
                f"{' has' if drifting == 1 else 's have'} missed "
                f"{insights.MISSED_IN_A_ROW_ALERT} cluster sessions in a row",
                "href": f"{base}?tab=attendance&fy={fy}&show={insights.SHOW_MISSING}",
                "key": "absent",
            }
        )
    ssa = profile["ssa"]
    # The short reads beside the roster (owner, 2026-10-10: "I like the
    # second column"): the profile's own rail, its lines opening the profile.
    from apps.analytics import profile_rail

    rail = profile_rail.build(
        profile,
        tab_url=lambda section, show="": (
            f"{base}?tab={_TAB_OF.get(section, section)}&fy={fy}"
            + (f"&show={show}" if show else "")
        ),
        records_url=lambda what, key="": (
            f"{records}{what}" + (f"&key={quote(str(key))}" if key else "")
        ),
    )
    rail["title"] = "Cluster Insights"
    for part in rail["parts"]:
        if part["key"] == "attention":
            # The page's own list: the profile's lines and the register's.
            part["title"] = "Needs Attention Now"
            part["links"] = [
                {"name": i["text"], "href": i["href"], "key": i["key"]}
                for i in attention
            ]
    return {
        "rail": rail,
        "fy": fy,
        "fy_label": profile["fy_label"],
        "previous_label": profile["previous_label"],
        "profile_url": base,
        "records": records,
        "schools": profile["portfolio"]["schools"],
        # By type: the roster below keeps Champion schools in their own list,
        # so the two counts are told apart here.
        "school_types": " · ".join(
            f"{t['count']:,} {t['label']}" for t in profile["portfolio"]["types"]
        ),
        "planned": total("planned"),
        "planned_parts": parts("planned"),
        "completed": total("completed"),
        "completed_parts": parts("completed"),
        "upcoming": total("upcoming"),
        "upcoming_parts": parts("upcoming"),
        "overdue": total("overdue"),
        "overdue_parts": parts("overdue"),
        "outstanding": len(attention),
        "ssa_current": ssa["current"],
        "ssa_previous": ssa["previous"],
        "ssa_change": ssa["overall"]["change"],
        "ssa_tone": ssa["overall"]["tone"],
        "assessed": profile["portfolio"]["assessed"],
        "attention": attention,
    }
