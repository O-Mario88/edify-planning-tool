"""Cluster Management: the sections of the one workspace.

Owner brief, 2026-10-08 ("Suggested final navigation ... Cluster Management:
Command Center, My Clusters, Clusters, Meetings, Training, Attendance,
Schools, SSA Performance, Teacher Impact, Leader Impact, Student Impact,
Academic Impact, Loans & BT, MSCS, Impact Analytics, Planning, Evidence,
Reports"), and of the whole: "one operating system, not a separate cluster
application ... Cluster Management becomes the integration, aggregation,
analysis and impact layer".

The sections are the tabs of ONE page behind ONE sidebar entry: the sidebar
stays the length the owner set it to on 2026-10-02, and a section is a link
that can be bookmarked and sent.

Every section is a table over the clusters the reader may see
(``cluster_queryset``), built from one set of reads (``scores.gather``) — the
reads the cluster profile's tabs make — so a figure here is the figure its
link opens on the profile, and no section keeps a number of its own. A
section that already has an authoritative page elsewhere (the Cluster
Directory) is a door to it, not a second copy.

A table is described, not drawn: columns and rows of cells, which one
template renders and the same rows export as CSV (the Reports section).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import interventions, outcomes, scores
from . import profile_insights as insights

DASH = "—"


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    description: str
    #: A section whose records already have their own page opens it.
    url: str = ""


SECTIONS = (
    Section(
        "command",
        "Command Center",
        "Every cluster on one line: who holds it, how its schools take part, "
        "what moved, and its health, impact and maturity.",
    ),
    Section("my", "My Clusters", "The clusters you are responsible for."),
    Section(
        "directory",
        "Clusters",
        "The cluster directory: create, edit and open a cluster.",
        url="/clusters",
    ),
    Section("meetings", "Meetings", "Cluster meetings held, and who came."),
    Section("training", "Training", "Group trainings held, and who came."),
    Section(
        "attendance",
        "Attendance",
        "Schools that have missed three or more sessions in a row.",
    ),
    Section("schools", "Schools", "Every school with its cluster's context."),
    Section("ssa", "SSA Performance", "Each cluster's SSA movement, area by area."),
    Section("teachers", "Teacher Impact", "The Teacher Impact index by cluster."),
    Section(
        "leaders", "Leader Impact", "The School Leadership Impact index by cluster."
    ),
    Section("students", "Student Impact", "Enrolment by cluster, year on year."),
    Section("academic", "Academic Impact", "Confirmed learning results by cluster."),
    Section(
        "loans",
        "Loans & BT",
        "Loans to each cluster's schools and its Business Transformation SSA.",
    ),
    Section("stories", "MSCS", "Most Significant Change stories by cluster."),
    Section(
        "impact",
        "Impact Analytics",
        "Clusters compared on every part of Cluster Impact, and which "
        "trainings their schools' SSA rose after.",
    ),
    Section("planning", "Planning", "What each cluster has planned and delivered."),
    Section(
        "evidence", "Evidence", "Where a cluster's figures are missing their record."
    ),
    Section("reports", "Reports", "Every section as a download."),
)
SECTION_BY_KEY = {s.key: s for s in SECTIONS}
DEFAULT_SECTION = "command"


# ── A table, described ───────────────────────────────────────────────────────


@dataclass
class Table:
    name: str
    title: str
    summary: str = ""
    caption: str = ""
    columns: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    note: str = ""
    empty: str = "Nothing to show."

    def as_csv_rows(self) -> list[list[str]]:
        return [[c["label"] for c in self.columns]] + [
            [cell["text"] for cell in row["cells"]] for row in self.rows
        ]


def col(label: str, *, numeric: bool = False) -> dict:
    return {"label": label, "numeric": numeric}


def cell(value, *, tone: str = "") -> dict:
    return {"text": DASH if value in (None, "") else str(value), "tone": tone}


def cluster_cell(value, cluster_id, query: str = "", *, tone: str = "") -> dict:
    """A figure that opens the cluster profile at the tab that explains it."""
    out = cell(value, tone=tone)
    if out["text"] != DASH:
        out["cluster"] = cluster_id
        out["query"] = query
    return out


def school_cell(name, school_pk) -> dict:
    return {"text": name, "tone": "", "school": school_pk}


def signed(value, digits: int = 1, suffix: str = "") -> str | None:
    if value is None:
        return None
    return f"{'+' if value > 0 else ''}{value:.{digits}f}{suffix}"


def tone_of(value) -> str:
    if value is None or value == 0:
        return "neutral" if value == 0 else ""
    return "success" if value > 0 else "danger"


def pct(value) -> str | None:
    return None if value is None else f"{round(value)}%"


def number(value) -> str | None:
    return None if value is None else f"{value:,}"


def _score_cell(composite, cluster_id, fy) -> dict:
    label, tone = composite.band
    return cluster_cell(
        DASH if composite.score is None else f"{composite.score} · {label}",
        cluster_id,
        f"?tab=scores&fy={fy}&part={composite.key}",
        tone="" if composite.score is None else tone,
    )


# ── The reader's clusters and everything read about them ─────────────────────


@dataclass
class Workspace:
    fy: str
    clusters: list
    facts: dict
    cards: dict
    owners: dict
    my_ids: set
    may_read_loans: bool
    settings: object

    def owner_of(self, cluster) -> str:
        from .oversight_service import _label

        profile = self.owners.get((cluster.responsible_staff_id or "").strip())
        return _label(profile) if profile else "Unassigned"

    @property
    def ssa_years(self) -> tuple[str, str]:
        ssa_fy = self.facts["ssa_fy"]
        return str(int(ssa_fy) - 1), ssa_fy


def load(principal, *, fy: str, today: date | None = None) -> Workspace:
    """The clusters ``principal`` may see and every read the sections share."""
    from apps.core.permissions import RolePermissionService
    from apps.core.scoping import cluster_queryset, owner_ids, resolve_user_scope

    from .models import Cluster
    from .oversight_service import _staff_directory

    scope = resolve_user_scope(principal)
    queryset = cluster_queryset(scope, base=Cluster.objects.all())
    clusters = (
        list(queryset.select_related("district").order_by("name"))
        if queryset is not None
        else []
    )
    ids = [c.id for c in clusters]
    facts = scores.gather(ids, fy=fy, principal=principal, today=today)
    settings = scores.current_settings()
    mine = set(owner_ids(principal))
    return Workspace(
        fy=str(fy),
        clusters=clusters,
        facts=facts,
        cards=scores.scorecards(ids, fy=fy, facts=facts, settings=settings),
        owners=_staff_directory({c.responsible_staff_id for c in clusters}),
        my_ids={c.id for c in clusters if c.responsible_staff_id in mine},
        may_read_loans=RolePermissionService.can_view_page(principal, "loans"),
        settings=settings,
    )


# ── Sections ─────────────────────────────────────────────────────────────────


def _lead(ws: Workspace, cluster, query: str = "") -> list[dict]:
    """The three cells every cluster table opens with."""
    return [
        cluster_cell(cluster.name, cluster.id, query),
        cell(getattr(cluster.district, "name", "")),
        cell(ws.owner_of(cluster)),
    ]


LEAD_COLUMNS = [col("Cluster"), col("District"), col("CCEO")]


def _command(ws: Workspace, clusters, *, name: str, title: str) -> Table:
    before, after = ws.ssa_years
    rows = []
    invited = attended = absent = schools = 0
    for c in clusters:
        att = ws.facts["attendance"][c.id]
        moved = ws.facts["movement"][c.id]["overall"]
        enrol = ws.facts["enrolment"][c.id]
        learn = ws.facts["learning"][c.id]
        stories = ws.facts["stories"][c.id]
        card = ws.cards[c.id]
        funded = ws.facts["funded_schools"].get(c.id, 0)
        school_count = len(ws.facts["members"].get(c.id, []))
        invited += att["invited_total"]
        attended += att["attended_total"]
        absent += len(att["drifting"])
        schools += school_count
        rows.append(
            {
                "key": c.id,
                "cells": _lead(ws, c)
                + [
                    cell(school_count),
                    cluster_cell(pct(att["rate"]), c.id, f"?tab=attendance&fy={ws.fy}"),
                    cluster_cell(
                        len(att["drifting"]) or None,
                        c.id,
                        f"?tab=attendance&fy={ws.fy}&show=missing",
                        tone="danger",
                    )
                    if att["drifting"]
                    else cell(0),
                    cluster_cell(
                        signed(moved.change),
                        c.id,
                        f"?tab=ssa&fy={after}",
                        tone=tone_of(moved.change),
                    ),
                    cluster_cell(
                        signed(enrol.growth_pct, suffix="%"),
                        c.id,
                        f"?tab=students&fy={ws.fy}",
                        tone=tone_of(enrol.growth_pct),
                    ),
                    cluster_cell(
                        signed(learn.change),
                        c.id,
                        f"?tab=learning&fy={ws.fy}",
                        tone=tone_of(learn.change),
                    ),
                    cluster_cell(funded, c.id, "?tab=loans")
                    if ws.may_read_loans and funded
                    else cell(funded),
                    cluster_cell(stories.approved, c.id, "?tab=stories")
                    if stories.story_count
                    else cell(0),
                    _score_cell(card.health, c.id, ws.fy),
                    _score_cell(card.impact, c.id, ws.fy),
                    cluster_cell(
                        f"{card.maturity['level']} · {card.maturity['label']}",
                        c.id,
                        f"?tab=scores&fy={ws.fy}&part=maturity",
                    ),
                ],
            }
        )
    rate = round(100 * attended / invited) if invited else None
    return Table(
        name=name,
        title=title,
        summary=(
            f"{len(clusters)} cluster{'' if len(clusters) == 1 else 's'} · "
            f"{schools:,} schools · "
            f"{pct(rate) or 'no'} attendance · {absent} schools absent "
            f"{insights.MISSED_IN_A_ROW_ALERT}+ sessions"
        ),
        caption=(
            "Each cluster with its district and officer, its schools, this "
            "year's attendance, schools absent three or more sessions in a row, "
            f"SSA change FY {before} to FY {after}, enrolment growth, learning "
            "change, schools holding a loan, approved change stories, Cluster "
            "Health, Cluster Impact and maturity level. Each figure opens the "
            "cluster profile at the tab that lists what is behind it."
        ),
        columns=LEAD_COLUMNS
        + [
            col("Schools", numeric=True),
            col("Attendance", numeric=True),
            col(f"Absent {insights.MISSED_IN_A_ROW_ALERT}+ Sessions", numeric=True),
            col("SSA Change", numeric=True),
            col("Enrolment Growth", numeric=True),
            col("Learning Change", numeric=True),
            col("Schools With Loans", numeric=True),
            col("Approved Stories", numeric=True),
            col("Health"),
            col("Impact"),
            col("Maturity"),
        ],
        rows=rows,
        note=(
            "Health says whether the cluster is operating; Impact says whether "
            "its schools' outcomes are moving. They are kept apart on purpose: "
            "a cluster can be strong on one and weak on the other. A dash is a "
            "figure the records cannot yet give, never a zero."
        ),
        empty="No cluster is in your scope.",
    )


def command(ws: Workspace, **_) -> Table:
    return _command(ws, ws.clusters, name="cm-command", title="Command Center")


def my(ws: Workspace, **_) -> Table:
    mine = [c for c in ws.clusters if c.id in ws.my_ids]
    table = _command(ws, mine, name="cm-my", title="My Clusters")
    table.empty = "You are not the responsible officer for any cluster."
    return table


def _sessions(ws: Workspace, *, trainings: bool) -> Table:
    labels = _area_labels()
    rows = []
    without = 0
    for c in ws.clusters:
        att = ws.facts["attendance"][c.id]
        without += att["without_register"]
        for s in att["sessions"]:
            if s.is_training != trainings:
                continue
            rows.append(
                {
                    "key": s.id,
                    "sort": s.held_on or date.min,
                    "cells": [
                        cell(f"{s.held_on:%-d %b %Y}" if s.held_on else None),
                        cluster_cell(
                            c.name, c.id, f"?tab=attendance&fy={ws.fy}&show=sessions"
                        ),
                        cell(s.name),
                        cell(labels.get(s.area, "")),
                        cell(s.invited),
                        cell(s.attended),
                        cell(pct(s.rate)),
                        cell(s.teachers),
                        cell(s.leaders),
                    ],
                }
            )
    rows.sort(key=lambda r: r["sort"], reverse=True)
    word = "Group Trainings" if trainings else "Cluster Meetings"
    return Table(
        name="cm-training" if trainings else "cm-meetings",
        title=f"{word} Held, FY {ws.fy}",
        summary=f"{len(rows)} with a register",
        caption=(
            f"{word} held in FY {ws.fy} that have a register: the date, the "
            "cluster, the session, the SSA area it was aimed at, schools invited "
            "and attended, the attendance rate, and teachers and school leaders "
            "who came."
        ),
        columns=[
            col("Date"),
            col("Cluster"),
            col("Training" if trainings else "Meeting"),
            col("SSA Area"),
            col("Schools Invited", numeric=True),
            col("Schools Attended", numeric=True),
            col("Attendance", numeric=True),
            col("Teachers", numeric=True),
            col("School Leaders", numeric=True),
        ],
        rows=rows,
        note=(
            f"{without} delivered session{'' if without == 1 else 's'} across "
            "these clusters have no register (nobody was ticked as attending) "
            "and are not listed."
            if without
            else ""
        ),
        empty=f"No {word.lower()} with a register in this year.",
    )


def meetings(ws: Workspace, **_) -> Table:
    return _sessions(ws, trainings=False)


def training(ws: Workspace, **_) -> Table:
    return _sessions(ws, trainings=True)


def attendance(ws: Workspace, **_) -> Table:
    rows = []
    clusters_hit = 0
    for c in ws.clusters:
        drifting = ws.facts["attendance"][c.id]["drifting"]
        clusters_hit += bool(drifting)
        for s in drifting:
            rows.append(
                {
                    "key": s.id,
                    "sort": (-s.missed_in_a_row, c.name, s.name),
                    "cells": [
                        cluster_cell(
                            c.name, c.id, f"?tab=attendance&fy={ws.fy}&show=missing"
                        ),
                        cell(ws.owner_of(c)),
                        cell(s.code),
                        school_cell(s.name, s.id),
                        cell(s.invited),
                        cell(s.attended),
                        cell(pct(s.rate)),
                        cell(
                            f"{s.last_attended:%-d %b %Y}"
                            if s.last_attended
                            else "Never"
                        ),
                        cell(s.missed_in_a_row, tone="danger"),
                    ],
                }
            )
    rows.sort(key=lambda r: r["sort"])
    return Table(
        name="cm-attendance",
        title=f"Schools Absent {insights.MISSED_IN_A_ROW_ALERT} or More Sessions in a Row",
        summary=(
            f"{len(rows)} school{'' if len(rows) == 1 else 's'} in "
            f"{clusters_hit} cluster{'' if clusters_hit == 1 else 's'}"
        ),
        caption=(
            "Schools that have missed three or more cluster sessions in a row: "
            "the cluster and its officer, School ID, school, sessions invited "
            f"to and attended in FY {ws.fy}, the attendance rate, the date last "
            "attended and the number of sessions missed in a row."
        ),
        columns=[
            col("Cluster"),
            col("CCEO"),
            col("School ID"),
            col("School Name"),
            col("Invited", numeric=True),
            col("Attended", numeric=True),
            col("Attendance", numeric=True),
            col("Last Attended"),
            col("Consecutive Misses", numeric=True),
        ],
        rows=rows,
        note=(
            "Invited and Attended count this year's sessions; Consecutive "
            "Misses counts back from the school's latest invitation, across "
            "years. The officer who holds the cluster has a To-Do for these "
            "schools."
        ),
        empty="No school has missed that many sessions in a row.",
    )


def schools(ws: Workspace, **_) -> Table:
    before, after = ws.ssa_years
    rows = []
    for c in ws.clusters:
        att = {s.id: s for s in ws.facts["attendance"][c.id]["schools"]}
        ssa = {
            r["id"]: r
            for r in ws.facts["movement"][c.id]["schools_by_area"][insights.OVERALL]
        }
        enrol = {r["id"]: r for r in ws.facts["enrolment"][c.id].rows}
        learn = {r["id"]: r for r in ws.facts["learning"][c.id].rows}
        loans: dict[str, int] = {}
        for loan in ws.facts["loans"][c.id].rows:
            loans[loan["school_pk"]] = loans.get(loan["school_pk"], 0) + 1
        for school in ws.facts["members"].get(c.id, []):
            sid = school["id"]
            a, s, e, lr = (
                att.get(sid),
                ssa.get(sid, {}),
                enrol.get(sid, {}),
                learn.get(sid, {}),
            )
            cells = [
                cluster_cell(c.name, c.id),
                cell(school["school_id"]),
                school_cell(school["name"], sid),
                cell(signed(s.get("change")), tone=s.get("tone", "")),
                cell(s.get("verdict_label")),
                cell(pct(a.rate) if a else None),
                cell(
                    a.missed_in_a_row if a else None,
                    tone="danger" if a and a.is_drifting else "",
                ),
                cell(number(e.get("latest"))),
                cell(
                    signed(e.get("growth_pct"), suffix="%"),
                    tone=tone_of(e.get("growth_pct")),
                ),
                cell(signed(lr.get("change")), tone=tone_of(lr.get("change"))),
            ]
            if ws.may_read_loans:
                cells.append(cell(loans.get(sid, 0)))
            rows.append({"key": sid, "cells": cells})
    columns = [
        col("Cluster"),
        col("School ID"),
        col("School Name"),
        col("SSA Change", numeric=True),
        col("SSA Verdict"),
        col("Attendance", numeric=True),
        col("Consecutive Misses", numeric=True),
        col("Latest Enrolment", numeric=True),
        col("Enrolment Growth", numeric=True),
        col("Learning Change", numeric=True),
    ]
    if ws.may_read_loans:
        columns.append(col("Loans", numeric=True))
    return Table(
        name="cm-schools",
        title="Schools in Their Clusters",
        summary=f"{len(rows):,} school{'' if len(rows) == 1 else 's'}",
        caption=(
            "Every school of these clusters: its cluster, School ID, name, SSA "
            f"change FY {before} to FY {after} and its verdict, this year's "
            "attendance at cluster sessions and sessions missed in a row, the "
            "latest enrolment and its growth, and the change in its learning "
            "results."
        ),
        columns=columns,
        rows=rows,
        empty="No school is in a cluster in your scope.",
    )


def _area_labels() -> dict[str, str]:
    from apps.core.enums import SsaIntervention

    return dict(SsaIntervention.choices)


def ssa(ws: Workspace, *, area: str = "", **_) -> Table:
    before, after = ws.ssa_years
    labels = _area_labels()
    key = area if area in labels else insights.OVERALL
    rows = []
    totals = {"compared": 0, "improved": 0, "declined": 0}
    for c in ws.clusters:
        movement = ws.facts["movement"][c.id]
        a = next(x for x in movement["areas"] if x.key == key)
        base = f"?tab=ssa&fy={after}&area={key}&verdict="
        totals["compared"] += a.compared
        totals["improved"] += a.improved
        totals["declined"] += a.declined
        rows.append(
            {
                "key": c.id,
                "cells": _lead(ws, c, f"?tab=ssa&fy={after}")
                + [
                    cell(movement["school_count"]),
                    cell(a.compared),
                    cell(None if a.before is None else f"{a.before:.1f}"),
                    cell(None if a.after is None else f"{a.after:.1f}"),
                    cell(signed(a.change), tone=tone_of(a.change)),
                    cluster_cell(a.improved, c.id, base + "improved")
                    if a.improved
                    else cell(0),
                    cluster_cell(a.held, c.id, base + "no_change")
                    if a.held
                    else cell(0),
                    cluster_cell(a.declined, c.id, base + "declined", tone="danger")
                    if a.declined
                    else cell(0),
                    cluster_cell(a.not_compared, c.id, base + "not_compared")
                    if a.not_compared
                    else cell(0),
                ],
            }
        )
    return Table(
        name="cm-ssa",
        title=f"SSA Performance: {labels.get(key, 'All SSA Areas')}, FY {before} to FY {after}",
        summary=(
            f"{totals['compared']:,} schools compared · {totals['improved']:,} "
            f"improved · {totals['declined']:,} declined"
        ),
        caption=(
            f"Each cluster's SSA on {labels.get(key, 'all areas')}: its schools, "
            "those with a confirmed SSA in both years, the average in each "
            "year, the change, and how many schools improved, did not change, "
            "declined or could not be compared. Each count opens its schools."
        ),
        columns=LEAD_COLUMNS
        + [
            col("Schools", numeric=True),
            col("Schools Compared", numeric=True),
            col(f"FY {before}", numeric=True),
            col(f"FY {after}", numeric=True),
            col("Change", numeric=True),
            col("Improved", numeric=True),
            col("No Change", numeric=True),
            col("Declined", numeric=True),
            col("Not Compared", numeric=True),
        ],
        rows=rows,
        note=ws.facts["movement"][ws.clusters[0].id]["rule_sentence"]
        if ws.clusters
        else "",
        empty="No cluster is in your scope.",
    )


def _index(
    ws: Workspace, key: str, *, name: str, reached: str, reached_label: str
) -> Table:
    title, dimensions = scores.SCORES[key]
    rows = []
    for c in ws.clusters:
        composite = getattr(ws.cards[c.id], key)
        rows.append(
            {
                "key": c.id,
                "sort": -(composite.score if composite.score is not None else -1),
                "cells": _lead(ws, c, f"?tab=scores&fy={ws.fy}&part={key}")
                + [cell(number(ws.facts["attendance"][c.id][reached]))]
                + [cell(pct(d.score)) for d in composite.dimensions]
                + [_score_cell(composite, c.id, ws.fy)],
            }
        )
    rows.sort(key=lambda r: r["sort"])
    return Table(
        name=name,
        title=f"{title} by Cluster, FY {ws.fy}",
        summary=f"{len(rows)} cluster{'' if len(rows) == 1 else 's'}",
        caption=(
            f"Each cluster's {title} index: {reached_label.lower()} this year, "
            "each part of the index as a share out of 100, and the index with "
            "its band. The index opens its parts and what each is read from."
        ),
        columns=LEAD_COLUMNS
        + [col(reached_label, numeric=True)]
        + [col(label, numeric=True) for _key, label, _w in dimensions]
        + [col(title)],
        rows=rows,
        note=(
            "Not collected on the platform yet, so not in this index: "
            + "; ".join(scores.NOT_COLLECTED[key])
            + "."
        ),
        empty="No cluster is in your scope.",
    )


def teachers(ws: Workspace, **_) -> Table:
    return _index(
        ws,
        "teacher",
        name="cm-teachers",
        reached="teachers",
        reached_label="Teachers Reached",
    )


def leaders(ws: Workspace, **_) -> Table:
    return _index(
        ws,
        "leader",
        name="cm-leaders",
        reached="leaders",
        reached_label="School Leaders Reached",
    )


def students(ws: Workspace, **_) -> Table:
    rows = []
    before_total = after_total = compared = 0
    previous = str(int(ws.fy) - 1)
    for c in ws.clusters:
        e = ws.facts["enrolment"][c.id]
        compared += e.compared
        before_total += e.before
        after_total += e.after
        rows.append(
            {
                "key": c.id,
                "cells": _lead(ws, c, f"?tab=students&fy={ws.fy}")
                + [
                    cell(e.school_count),
                    cell(e.compared),
                    cell(number(e.before) if e.compared else None),
                    cell(number(e.after) if e.compared else None),
                    cell(
                        signed(e.change, 0) if e.change is not None else None,
                        tone=tone_of(e.change),
                    ),
                    cell(signed(e.growth_pct, suffix="%"), tone=tone_of(e.growth_pct)),
                    cell(number(e.latest_total)),
                ],
            }
        )
    growth = outcomes._growth_pct(before_total, after_total) if compared else None
    return Table(
        name="cm-students",
        title=f"Enrolment by Cluster, FY {previous} to FY {ws.fy}",
        summary=(
            f"{before_total:,} to {after_total:,} learners "
            f"({signed(growth, suffix='%')}) across {compared:,} schools compared"
            if compared
            else "No school has an enrolment figure in both years"
        ),
        caption=(
            "Each cluster's enrolment: its schools, those with a figure in both "
            "years, the total in each year for those schools, the change and "
            "growth, and the total on the schools' latest figures."
        ),
        columns=LEAD_COLUMNS
        + [
            col("Schools", numeric=True),
            col("Schools Compared", numeric=True),
            col(f"FY {previous}", numeric=True),
            col(f"FY {ws.fy}", numeric=True),
            col("Change", numeric=True),
            col("Growth", numeric=True),
            col("Latest Enrolment", numeric=True),
        ],
        rows=rows,
        note=(
            "Growth counts only schools with a figure in both years, so a "
            "school joining a cluster is never read as growth."
        ),
        empty="No cluster is in your scope.",
    )


def academic(ws: Workspace, **_) -> Table:
    previous = str(int(ws.fy) - 1)
    rows = []
    for c in ws.clusters:
        lr = ws.facts["learning"][c.id]
        rows.append(
            {
                "key": c.id,
                "cells": _lead(ws, c, f"?tab=learning&fy={ws.fy}")
                + [
                    cell(lr.compared),
                    cell(None if lr.before is None else f"{lr.before:.1f}%"),
                    cell(None if lr.after is None else f"{lr.after:.1f}%"),
                    cell(signed(lr.change), tone=tone_of(lr.change)),
                    cell(lr.improved),
                    cell(lr.unchanged),
                    cell(lr.declined, tone="danger" if lr.declined else ""),
                ],
            }
        )
    return Table(
        name="cm-academic",
        title=f"Learning Results by Cluster, FY {previous} to FY {ws.fy}",
        summary=f"{sum(ws.facts['learning'][c.id].compared for c in ws.clusters):,} schools compared",
        caption=(
            "Each cluster's confirmed learning results: schools with a result "
            "in both years, the mean score in each year as a share of the marks "
            "available, the change in percentage points, and schools improved, "
            "unchanged and declined."
        ),
        columns=LEAD_COLUMNS
        + [
            col("Schools Compared", numeric=True),
            col(f"FY {previous}", numeric=True),
            col(f"FY {ws.fy}", numeric=True),
            col("Change", numeric=True),
            col("Improved", numeric=True),
            col("Unchanged", numeric=True),
            col("Declined", numeric=True),
        ],
        rows=rows,
        note=(
            "Confirmed results only. These are the results the schools "
            "recorded, not a measure of what any one activity caused."
        ),
        empty="No cluster is in your scope.",
    )


def loans(ws: Workspace, **_) -> Table:
    rows = []
    for c in ws.clusters:
        card = ws.cards[c.id]
        bt = {d.key: d for d in card.impact.dimensions}
        leader = {d.key: d for d in card.leader.dimensions}
        summary = ws.facts["loans"][c.id]
        cells = _lead(ws, c, "?tab=loans" if ws.may_read_loans else "") + [
            cell(ws.facts["funded_schools"].get(c.id, 0))
        ]
        if ws.may_read_loans:
            cells += [
                cell(summary.loan_count),
                cell(f"{summary.disbursed:,.0f}"),
            ]
        cells += [
            cell(pct(leader["finance_ssa"].score)),
            cell(pct(leader["compliance_ssa"].score)),
            cell(pct(bt["bt"].score)),
        ]
        rows.append({"key": c.id, "cells": cells})
    columns = LEAD_COLUMNS + [col("Schools With Loans", numeric=True)]
    if ws.may_read_loans:
        columns += [col("Loans", numeric=True), col("Disbursed (UGX)", numeric=True)]
    columns += [
        col("Financial Health SSA", numeric=True),
        col("Government Requirements SSA", numeric=True),
        col("Business Transformation", numeric=True),
    ]
    return Table(
        name="cm-loans",
        title="Loans and Business Transformation by Cluster",
        summary=(f"{sum(ws.facts['funded_schools'].values()):,} schools hold a loan"),
        caption=(
            "Each cluster's schools holding a loan"
            + (", its loans and the amount disbursed" if ws.may_read_loans else "")
            + ", and the share of its schools whose Financial Health and "
            "Government Requirements SSA improved."
        ),
        columns=columns,
        rows=rows,
        note=(
            "The SSA columns are the share of compared schools that improved "
            "on the area. Loan records are the loan register's; a reader sees "
            "here what the register shows them."
        ),
        empty="No cluster is in your scope.",
    )


def stories(ws: Workspace, **_) -> Table:
    rows = []
    for c in ws.clusters:
        s = ws.facts["stories"][c.id]
        latest = max((r["date"] for r in s.rows), default=None)
        with_evidence = sum(1 for r in s.rows if r["has_evidence"])
        rows.append(
            {
                "key": c.id,
                "sort": -s.story_count,
                "cells": _lead(ws, c, "?tab=stories")
                + [
                    cell(s.approved),
                    cell(s.waiting),
                    cell(s.story_count),
                    cell(with_evidence),
                    cell(f"{latest:%-d %b %Y}" if latest else None),
                ],
            }
        )
    rows.sort(key=lambda r: r["sort"])
    return Table(
        name="cm-stories",
        title="Most Significant Change Stories by Cluster",
        summary=(
            f"{sum(ws.facts['stories'][c.id].approved for c in ws.clusters)} approved · "
            f"{sum(ws.facts['stories'][c.id].waiting for c in ws.clusters)} with a reviewer"
        ),
        caption=(
            "Each cluster's change stories: approved, with a reviewer, all "
            "submitted, those with evidence attached, and the date of the "
            "latest. The cluster opens its stories."
        ),
        columns=LEAD_COLUMNS
        + [
            col("Approved", numeric=True),
            col("Under Review", numeric=True),
            col("All Stories", numeric=True),
            col("With Evidence", numeric=True),
            col("Latest Story"),
        ],
        rows=rows,
        note="Only an approved story counts as evidence. A draft is not listed.",
        empty="No cluster is in your scope.",
    )


IMPACT_VIEWS = ("clusters", "courses")


def impact(ws: Workspace, *, view: str = "", **_) -> Table:
    if view == "courses":
        return _courses(ws)
    rows = []
    for c in ws.clusters:
        card = ws.cards[c.id]
        rows.append(
            {
                "key": c.id,
                "sort": -(card.impact.score if card.impact.score is not None else -1),
                "cells": _lead(ws, c, f"?tab=scores&fy={ws.fy}&part=impact")
                + [
                    _score_cell(card.health, c.id, ws.fy),
                    _score_cell(card.impact, c.id, ws.fy),
                    cell(f"{card.maturity['level']} · {card.maturity['label']}"),
                ]
                + [cell(pct(d.score)) for d in card.impact.dimensions],
            }
        )
    rows.sort(key=lambda r: r["sort"])
    return Table(
        name="cm-impact",
        title=f"Clusters Compared, FY {ws.fy}",
        summary=f"{len(rows)} cluster{'' if len(rows) == 1 else 's'}, highest Impact first",
        caption=(
            "Clusters side by side: Cluster Health, Cluster Impact, maturity, "
            "and each part of Cluster Impact as a share out of 100."
        ),
        columns=LEAD_COLUMNS
        + [col("Health"), col("Impact"), col("Maturity")]
        + [col(label, numeric=True) for _k, label, _w in scores.IMPACT_DIMENSIONS],
        rows=rows,
        note=(
            "Each part is a share out of 100 from the cluster's own records; a "
            "dash is a part that cannot be measured yet and is left out of the "
            "score. Use this to ask why one cluster moves and another does not."
        ),
        empty="No cluster is in your scope.",
    )


def _courses(ws: Workspace) -> Table:
    before, after = ws.ssa_years
    rows = [
        {
            "key": f"{r['course']}-{r['area']}",
            "cells": [
                cell(r["course"]),
                cell(r["area"]),
                cell(r["sessions"]),
                cell(r["clusters"]),
                cell(r["readings"]),
                cell(f"{r['better']} ({r['better_pct']}%)"),
                cell(signed(r["mean_change"]), tone=tone_of(r["mean_change"])),
            ],
        }
        for r in interventions.course_effectiveness(ws.facts)
    ]
    return Table(
        name="cm-courses",
        title=f"SSA Movement After Each Training, FY {before} to FY {after}",
        summary=f"{len(rows)} training course{'' if len(rows) == 1 else 's'}",
        caption=(
            "Each group training course with a named SSA area: the sessions "
            "held and clusters holding them, the readings of schools that "
            "attended and can be compared on that area, how many rose, and the "
            "mean change."
        ),
        columns=[
            col("Training"),
            col("SSA Area"),
            col("Sessions", numeric=True),
            col("Clusters", numeric=True),
            col("School Readings", numeric=True),
            col("Rose", numeric=True),
            col("Mean SSA Change", numeric=True),
        ],
        rows=rows,
        note=(
            "A school is counted once for each training it attended. This "
            "shows how the area trained moved at the schools that took part; "
            "it does not show that the training caused the movement, and a "
            "course with few readings should be read with care."
        ),
        empty=(
            "No school attended a group training with a named SSA area and "
            "has a confirmed SSA on that area in both years."
        ),
    )


def planning(ws: Workspace, **_) -> Table:
    rows = []
    for c in ws.clusters:
        plan = ws.facts["plan"][c.id]
        att = ws.facts["attendance"][c.id]
        not_seen = sum(1 for s in att["schools"] if not s.attended)
        moved = ws.facts["movement"][c.id]["overall"]

        def yes(flag):
            return cell(
                "Planned" if flag else "Not planned",
                tone="success" if flag else "danger",
            )

        rows.append(
            {
                "key": c.id,
                "cells": _lead(ws, c)
                + [
                    yes(plan["meeting_planned"]),
                    yes(plan["training_planned"]),
                    cell(f"{plan['meetings'][0]} of {plan['meetings'][1]}"),
                    cell(f"{plan['trainings'][0]} of {plan['trainings'][1]}"),
                    cluster_cell(not_seen, c.id, f"?tab=attendance&fy={ws.fy}")
                    if not_seen
                    else cell(0),
                    cluster_cell(
                        len(att["drifting"]),
                        c.id,
                        f"?tab=attendance&fy={ws.fy}&show=missing",
                        tone="danger",
                    )
                    if att["drifting"]
                    else cell(0),
                    cluster_cell(
                        moved.not_compared,
                        c.id,
                        f"?tab=ssa&fy={ws.ssa_years[1]}&area=overall&verdict=not_compared",
                    )
                    if moved.not_compared
                    else cell(0),
                ],
            }
        )
    unplanned = sum(
        1
        for c in ws.clusters
        if not (
            ws.facts["plan"][c.id]["meeting_planned"]
            and ws.facts["plan"][c.id]["training_planned"]
        )
    )
    return Table(
        name="cm-planning",
        title=f"Cluster Planning and Gaps, FY {ws.fy}",
        summary=(
            f"{unplanned} of {len(ws.clusters)} cluster"
            f"{'' if len(ws.clusters) == 1 else 's'} missing a meeting or a group training in the plan"
        ),
        caption=(
            "Each cluster's plan for the year: whether a cluster meeting and a "
            "group training are planned, how many of those due by now were "
            "delivered, schools that have attended no session this year, "
            "schools absent three or more in a row, and schools that cannot be "
            "compared on SSA."
        ),
        columns=LEAD_COLUMNS
        + [
            col("Cluster Meeting"),
            col("Group Training"),
            col("Meetings Delivered", numeric=True),
            col("Trainings Delivered", numeric=True),
            col("Schools With No Session", numeric=True),
            col(f"Absent {insights.MISSED_IN_A_ROW_ALERT}+ Sessions", numeric=True),
            col("SSA Not Compared", numeric=True),
        ],
        rows=rows,
        note=(
            "Planning makes the work; this page only measures it. Schedule a "
            "meeting or a group training from the cluster's profile, which "
            "opens the planning page with the cluster chosen."
        ),
        empty="No cluster is in your scope.",
    )


def evidence(ws: Workspace, **_) -> Table:
    rows = []
    for c in ws.clusters:
        att = ws.facts["attendance"][c.id]
        s = ws.facts["stories"][c.id]
        moved = ws.facts["movement"][c.id]["overall"]
        enrol = ws.facts["enrolment"][c.id]
        without_evidence = sum(
            1 for r in s.rows if not r["has_evidence"] and r["status"] != "rejected"
        )
        rows.append(
            {
                "key": c.id,
                "cells": _lead(ws, c)
                + [
                    cluster_cell(
                        len(att["sessions"]),
                        c.id,
                        f"?tab=attendance&fy={ws.fy}&show=sessions",
                    )
                    if att["sessions"]
                    else cell(0),
                    cell(
                        att["without_register"],
                        tone="danger" if att["without_register"] else "",
                    ),
                    cluster_cell(
                        moved.not_compared,
                        c.id,
                        f"?tab=ssa&fy={ws.ssa_years[1]}&area=overall&verdict=not_compared",
                    )
                    if moved.not_compared
                    else cell(0),
                    cell(enrol.school_count - enrol.compared),
                    cluster_cell(without_evidence, c.id, "?tab=stories")
                    if without_evidence
                    else cell(0),
                ],
            }
        )
    return Table(
        name="cm-evidence",
        title=f"Where the Record Is Missing, FY {ws.fy}",
        summary=(
            f"{sum(ws.facts['attendance'][c.id]['without_register'] for c in ws.clusters)} "
            "delivered sessions without a register"
        ),
        caption=(
            "Each cluster's gaps in the record behind its figures: sessions "
            "with a register, delivered sessions without one, schools that "
            "cannot be compared on SSA, schools without an enrolment figure in "
            "both years, and change stories with no evidence attached."
        ),
        columns=LEAD_COLUMNS
        + [
            col("Registers Taken", numeric=True),
            col("Registers Missing", numeric=True),
            col("SSA Not Compared", numeric=True),
            col("No Enrolment Pair", numeric=True),
            col("Stories Without Evidence", numeric=True),
        ],
        rows=rows,
        note=(
            "A figure on any other section is only as complete as these "
            "records. Activity evidence is reviewed on the Evidence page."
        ),
        empty="No cluster is in your scope.",
    )


BUILDERS = {
    "command": command,
    "my": my,
    "meetings": meetings,
    "training": training,
    "attendance": attendance,
    "schools": schools,
    "ssa": ssa,
    "teachers": teachers,
    "leaders": leaders,
    "students": students,
    "academic": academic,
    "loans": loans,
    "stories": stories,
    "impact": impact,
    "planning": planning,
    "evidence": evidence,
}


def reports(ws: Workspace, **_) -> Table:
    """Every other section as a download."""
    rows = []
    for section in SECTIONS:
        if section.key not in BUILDERS or section.key == "reports":
            continue
        rows.append(
            {
                "key": section.key,
                "cells": [
                    cell(section.label),
                    cell(section.description),
                    {"text": "Download CSV", "tone": "", "download": section.key},
                ],
            }
        )
    return Table(
        name="cm-reports",
        title=f"Reports, FY {ws.fy}",
        summary=f"{len(rows)} downloads",
        caption=(
            "Each Cluster Management section as a file: its name, what it "
            "holds, and the download for the fiscal year shown."
        ),
        columns=[col("Report"), col("What It Holds"), col("Download")],
        rows=rows,
        note=(
            "A download holds the rows the section shows you, for the clusters "
            "in your scope and the year chosen above."
        ),
    )


BUILDERS["reports"] = reports


def build(ws: Workspace, key: str, **options) -> Table:
    return BUILDERS[key](ws, **options)


__all__ = [
    "BUILDERS",
    "DEFAULT_SECTION",
    "IMPACT_VIEWS",
    "SECTIONS",
    "SECTION_BY_KEY",
    "Section",
    "Table",
    "Workspace",
    "build",
    "load",
]
