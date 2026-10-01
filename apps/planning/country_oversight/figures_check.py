"""The figures check: today's dashboard beside the same year by the rulebook.

Owner, 2026-10-01: the dashboard's cards, charts and table change to the
rulebook (``rules``) only once the Country Director has seen the new figures
against production. These are the sheets that show them — added to the page's
own workbook for the Country Director and the Admin, read from the same
records, and writing nothing. They go when the page itself reads the rulebook.

Every sheet reads the whole fiscal year for the reader's country: a period or
a school filter narrows the dashboard's own sheets, not these.
"""

from __future__ import annotations

from apps.planning.country_oversight import people, rules

#: Who is shown the check.
CHECK_ROLES = ("CountryDirector", "Admin")


def may_check(user) -> bool:
    return (getattr(user, "active_role", "") or "") in CHECK_ROLES


def _share(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "—"


def _kinds(counts: dict | None) -> str:
    counts = counts or {}
    return ", ".join(
        f"{rules.KIND_LABELS[kind]} × {counts[kind]}"
        for kind in rules.KIND_ORDER
        if counts.get(kind)
    )


def sheets(user, snapshot) -> list[dict]:
    """The four check sheets for the snapshot's fiscal year.

    ``snapshot`` is the dashboard's own unfiltered fold for the year, so
    "today" on these sheets is exactly what the page shows.
    """
    fy = snapshot.tree.window.fy
    plan = people.people_plan(user, fy)
    year = people.school_year(user, fy)
    by_type = people.summarise_by_type(year)
    return [
        _cards_sheet(snapshot, plan, by_type),
        _people_sheet(snapshot, plan),
        _types_sheet(by_type),
        _duplicates_sheet(snapshot, year),
    ]


# ── The six cards ────────────────────────────────────────────────────────────
def _cards_sheet(snapshot, plan, by_type) -> dict:
    today = snapshot.tree.country
    leads = plan.headcount(rules.PROGRAM_LEAD_ROLE)
    cceos = plan.headcount(rules.CCEO_ROLE)
    target = plan.total("target")
    visit_slots = sum(row.visit_slots for row in by_type)
    visits = sum(row.visits_planned for row in by_type)
    training_slots = sum(row.training_slots for row in by_type)
    trainings = sum(row.trainings for row in by_type)
    schools = sum(row.schools for row in by_type)
    clustered = sum(row.clustered for row in by_type)
    in_meeting = sum(row.in_meeting for row in by_type)
    twice = sum(row.duplicates for row in by_type)
    lead_target = rules.VISIT_TARGETS[rules.PROGRAM_LEAD_ROLE]
    cceo_target = rules.VISIT_TARGETS[rules.CCEO_ROLE]

    def row(card, old_part, old_whole, new_part, new_whole, how):
        return [
            card,
            old_part,
            old_whole,
            _share(old_part, old_whole),
            new_part,
            new_whole,
            _share(new_part, new_whole),
            how,
        ]

    rows = [
        row(
            "Staff Visit Planning",
            today.staff,
            today.staff_expected,
            plan.total("visits_planned"),
            target,
            f"Follow up, In-school Training and SSA Support visits planned by "
            f"staff, over {cceos} CCEOs × {cceo_target} + {leads} Programme "
            f"Leads × {lead_target}. Counted for the person who planned them.",
        ),
        row(
            "Partner Planning",
            today.partner_assigned,
            today.partner_expected,
            plan.total("partner_planned"),
            plan.total("partner_assigned"),
            "Work Partners have dated themselves, over the work staff assigned "
            f"to Partners ({plan.total('partner_schools')} schools). Nothing "
            "counts until a Partner sets a date.",
        ),
        row(
            "Total Visit Coverage",
            today.planned,
            today.visit_slots,
            visits,
            visit_slots,
            "Visit slots planned by staff or dated by a Partner, over what the "
            "schools need: 4 per Core school, 1 per Client, Core Trained and "
            "Core Graduate school. Champion schools are outside it.",
        ),
        row(
            "Training Planning",
            today.training,
            today.training_slots,
            trainings,
            training_slots,
            "Training slots planned, over what the schools need: 4 per Core "
            "school (2 staff + 2 Partner), 1 per Client and Core Trained "
            "school, none for Core Graduate and Champion schools.",
        ),
        row(
            "Cluster Membership",
            today.clustered,
            today.schools,
            clustered,
            schools,
            "Schools in an active cluster, over every operating school.",
        ),
        row(
            "Cluster Meeting Planning",
            today.meeting_covered,
            today.schools,
            in_meeting,
            schools,
            "Schools on the roster of a planned cluster meeting. Cluster "
            f"meetings staff have planned: {plan.total('meetings')}.",
        ),
        [
            "Schools planned twice",
            "",
            "",
            "",
            twice,
            "",
            "",
            "Client, Core Trained and Core Graduate schools planned by staff "
            "and held by a Partner, or with the same kind of visit twice. "
            "Listed on the last sheet.",
        ],
        [
            "Visits planned and not counted",
            "",
            "",
            "",
            plan.total("outreach"),
            "",
            "",
            "Donor, content/story, invitation and social visits staff planned. "
            "They are not among the visits a person is expected to plan.",
        ],
    ]
    return {
        "title": "Check 1 - the cards",
        "headers": [
            "Card",
            "Today: planned",
            "Today: expected",
            "Today: %",
            "New rules: planned",
            "New rules: expected",
            "New rules: %",
            "How the new figure is counted",
        ],
        "rows": rows,
        "widths": [30, 14, 14, 10, 16, 16, 12, 110],
    }


# ── One row per person ───────────────────────────────────────────────────────
PEOPLE_HEADERS = [
    "Level",
    "Programme Lead",
    "Person",
    "Role",
    "Role in use now (if different)",
    "Visit target",
    "New rules: visits planned",
    "New rules: % of target",
    "Follow up",
    "In-school Training",
    "SSA Support",
    "Not counted (donor, story, social, invitation)",
    "Today: staff planned",
    "Today: staff expected",
    "Schools held",
    "Core",
    "Client",
    "Core Trained",
    "Core Graduate",
    "Champion",
    "Visits these schools allow",
    "Short of target by",
    "Trainings planned",
    "Cluster trainings planned",
    "Cluster meetings planned",
    "Schools assigned to Partners",
    "Partner work assigned",
    "Partner planned (dated by the Partner)",
    "Today: Partner assigned",
    "Today: Partner scheduled",
]


def _today_by_person(snapshot) -> dict[str, object]:
    """The dashboard's own row for each holder, by StaffProfile id."""
    rows = {}
    for lead in snapshot.tree.leads:
        for owner in lead.owners:
            rows[owner.key] = owner.tally
    return rows


def _person_cells(person, today) -> list:
    schools = person.schools
    return [
        person.target,
        person.visits_planned,
        _share(person.visits_planned, person.target),
        person.visits.get(rules.KIND_FOLLOW_UP, 0),
        person.visits.get(rules.KIND_IN_SCHOOL, 0),
        person.visits.get(rules.KIND_SSA, 0),
        person.outreach,
        today.staff if today is not None else 0,
        today.staff_expected if today is not None else 0,
        person.school_count,
        *(schools.get(school_type, 0) for school_type in rules.TYPE_ORDER),
        person.reach,
        person.shortfall,
        person.trainings,
        person.cluster_trainings,
        person.meetings,
        person.partner_schools,
        person.partner_assigned,
        person.partner_planned,
        today.partner_assigned if today is not None else 0,
        today.partner_scheduled if today is not None else 0,
    ]


def _total_cells(group, today_rows, country=None) -> list:
    """A team's or the country's totals, in ``_person_cells`` order.

    ``country`` is the dashboard's own country total, which also holds the
    schools of anyone these rows do not name.
    """
    members = group.people
    schools = {
        school_type: sum(p.schools.get(school_type, 0) for p in members)
        for school_type in rules.TYPE_ORDER
    }
    today = (
        [country]
        if country is not None
        else [today_rows[p.key] for p in members if p.key in today_rows]
    )
    planned, target = group.total("visits_planned"), group.total("target")
    return [
        target,
        planned,
        _share(planned, target),
        group.visits_of(rules.KIND_FOLLOW_UP),
        group.visits_of(rules.KIND_IN_SCHOOL),
        group.visits_of(rules.KIND_SSA),
        group.total("outreach"),
        sum(t.staff for t in today),
        sum(t.staff_expected for t in today),
        group.total("school_count"),
        *(schools[school_type] for school_type in rules.TYPE_ORDER),
        group.total("reach"),
        group.total("shortfall"),
        group.total("trainings"),
        group.total("cluster_trainings"),
        group.total("meetings"),
        group.total("partner_schools"),
        group.total("partner_assigned"),
        group.total("partner_planned"),
        sum(t.partner_assigned for t in today),
        sum(t.partner_scheduled for t in today),
    ]


def _people_sheet(snapshot, plan) -> dict:
    today_rows = _today_by_person(snapshot)
    rows = [
        [
            "Country",
            "",
            "All teams",
            "",
            "",
            *_total_cells(plan, today_rows, snapshot.tree.country),
        ]
    ]
    for team in plan.teams:
        rows.append(
            ["Team", team.name, "Team total", "", "", *_total_cells(team, today_rows)]
        )
        for person in team.people:
            rows.append(
                [
                    "Person",
                    team.name,
                    person.name,
                    person.role_label
                    or person.role_in_use
                    or "Not a Programme Lead or CCEO",
                    person.role_in_use if person.role else "",
                    *_person_cells(person, today_rows.get(person.key)),
                ]
            )
    return {
        "title": "Check 2 - by person",
        "headers": PEOPLE_HEADERS,
        "rows": rows,
    }


# ── One row per school type ──────────────────────────────────────────────────
def _types_sheet(by_type) -> dict:
    rows = []
    for row in by_type:
        # A type the rulebook asks nothing of has no "not yet planned".
        requirement = rules.requirement_for(row.school_type)
        rows.append(
            [
                row.label,
                row.schools,
                row.visit_slots,
                row.staff_slots,
                row.partner_slots,
                _share(row.visits_planned, row.visit_slots),
                row.schools_with_visit,
                row.schools_without_visit if requirement.visits else "—",
                row.with_partner,
                row.training_slots,
                row.trainings,
                _share(row.trainings, row.training_slots),
                row.schools_with_training,
                row.schools_without_training if requirement.trainings else "—",
                row.clustered,
                row.in_meeting,
                row.duplicates,
            ]
        )
    return {
        "title": "Check 3 - by school type",
        "headers": [
            "School type",
            "Schools",
            "Visits needed",
            "Planned by staff",
            "Planned by Partners",
            "Visits planned %",
            "Schools with a visit planned",
            "Schools not yet planned",
            "Schools in a Partner's hands",
            "Trainings needed",
            "Trainings planned",
            "Trainings planned %",
            "Schools with a training planned",
            "Schools with no training planned",
            "In an active cluster",
            "On a planned cluster meeting",
            "Planned twice",
        ],
        "rows": rows,
    }


# ── Client-rule schools planned twice ────────────────────────────────────────
def _duplicates_sheet(snapshot, year) -> dict:
    from apps.planning.country_oversight.service import _names

    found = people.duplicates(year)
    partner_names = _names(
        "partners.Partner", {pid for s in found for pid in (s.partner_ids or ())}
    )
    holders = _holders({s.owner_id for s in found})
    rows = []
    for school in found:
        holder, lead = holders.get(str(school.owner_id or ""), ("No account owner", ""))
        waiting = school.partner_waiting or {}
        rows.append(
            [
                school.code,
                school.name,
                rules.type_label(school.school_type),
                lead,
                holder,
                "; ".join(
                    rules.DUPLICATE_LABELS[reason]
                    for reason in school.duplicate_reasons
                ),
                _kinds(school.staff),
                _kinds(school.partner_planned),
                sum(waiting.values()),
                ", ".join(
                    sorted(
                        partner_names.get(pid, "Unrecorded Partner")
                        for pid in (school.partner_ids or ())
                    )
                ),
            ]
        )
    return {
        "title": "Check 4 - planned twice",
        "headers": [
            "School ID",
            "School",
            "School type",
            "Programme Lead",
            "CCEO / holder",
            "Why",
            "Staff visits planned",
            "Partner visits dated",
            "Partner visits assigned, not dated",
            "Partner(s)",
        ],
        "rows": rows,
    }


def _holders(owner_ids) -> dict[str, tuple[str, str]]:
    """raw owner id → (holder name, Programme Lead name)."""
    from apps.planning.country_oversight.requirements import owner_directory

    return {
        raw: (info.name, info.lead_name if not info.is_lead_personal else info.name)
        for raw, info in owner_directory(owner_ids).items()
    }
