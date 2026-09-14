"""Audience versions of a frozen impact report (IA review, owner, 2026-09-13).

The role description asks Impact Assessment to communicate evidence-based
findings to Country Directors, international donors and partner schools. They
may not all read the same thing. The only report artefact before this was a
CSV carrying account owners' names, school names and every school, SSA and
project id, which could not responsibly leave the country office.

`redact(snapshot, profile, ...)` is a pure function over the evidence snapshot
frozen when the report was submitted (apps.impact.reports.build_snapshot). It
never queries, so what an audience receives is decided by the snapshot and
these rules alone, and a test can pin them:

  - leadership: the whole snapshot — the country's Country Director reads the
    school rows the report rests on.
  - donor: aggregates only. Cohort, domain, portfolio and evidence figures
    with their denominators and period; any count of 1 to 4 schools, and any
    share or median resting on fewer than SMALL_CELL schools, is suppressed;
    no school, staff or project names, and no ids of any kind. Limitations
    travel verbatim.
  - school: that one school's own before-and-after results, the report's
    findings and limitations with every other school's name and every staff
    name removed, and no assessment, project or staff ids.

Free text is scrubbed of the names and ids the snapshot itself knows (schools,
account owners, the author and reviewer); the reviewer and, for donors, the
approving RVP read the rendered version before it is released.
"""

from __future__ import annotations

import copy
import re

LEADERSHIP = "leadership"
DONOR = "donor"
SCHOOL = "school"
PROFILES = (LEADERSHIP, DONOR, SCHOOL)

#: Owner decision (2026-09-13): donor cells resting on fewer than five
#: schools are suppressed.
SMALL_CELL = 5

SUPPRESSED = "suppressed"

SCHOOL_PLACEHOLDER = "[a school]"
PERSON_PLACEHOLDER = "[a staff member]"
ID_PLACEHOLDER = "[reference]"

#: Status words a school may read about its own results.
SCHOOL_STATE_LABELS = {
    "improved": "Improved",
    "declined": "Declined",
    "maintained_strong": "Kept a strong score",
    "no_change": "No change",
    "baseline_missing": "No starting assessment yet",
    "evidence_review": "Follow-up assessment being checked",
    "not_scheduled": "Follow-up not yet scheduled",
    "overdue": "Follow-up assessment overdue",
    "due": "Follow-up assessment due",
    "upcoming": "Follow-up assessment coming up",
}


def _small(n) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and 0 < n < SMALL_CELL


def count_cell(n):
    """A count a donor may read: suppressed when it names 1 to 4 schools."""
    return SUPPRESSED if _small(n) else n


def share_cell(value, base):
    """A share or median resting on `base` schools: suppressed below
    SMALL_CELL (a share of nothing is not measured, never zero)."""
    if not base:
        return None
    if isinstance(base, int) and base < SMALL_CELL:
        return SUPPRESSED
    return value


def _names_and_ids(snapshot: dict, *, keep_school_id: str = "") -> tuple[set, set]:
    names: set[str] = set()
    ids: set[str] = set()
    for row in snapshot.get("rows") or []:
        if row.get("school_id") != keep_school_id and row.get("school"):
            names.add(str(row["school"]))
        if row.get("owner"):
            names.add(str(row["owner"]))
        for key in (
            "school_id",
            "project_id",
            "baseline_id",
            "follow_up_id",
            "owner_id",
            "assignment_id",
        ):
            if row.get(key):
                ids.add(str(row[key]))
    for person in snapshot.get("people") or []:
        if person:
            names.add(str(person))
    for ref in (snapshot.get("lending") or {}).get("verified_ids") or []:
        ids.add(str(ref))
    for finding in snapshot.get("findings") or []:
        if finding.get("id"):
            ids.add(str(finding["id"]))
    report = snapshot.get("report") or {}
    for key in ("id", "project_id"):
        if report.get(key):
            ids.add(str(report[key]))
    # Never scrub a placeholder-sized fragment: a two-letter "name" would eat
    # ordinary words.
    names = {n for n in names if len(n.strip()) >= 3 and n.strip() != "Unassigned"}
    ids = {i for i in ids if len(i) >= 6}
    return names, ids


def scrub(text: str, *, names=(), ids=(), placeholder=SCHOOL_PLACEHOLDER) -> str:
    """Remove known names and ids from free text, longest first so a school
    called "St Mary's Primary" is not half-replaced by "St Mary's"."""
    out = str(text or "")
    for name in sorted(names, key=len, reverse=True):
        out = re.sub(re.escape(name), placeholder, out, flags=re.IGNORECASE)
    for ref in sorted(ids, key=len, reverse=True):
        out = re.sub(re.escape(ref), ID_PLACEHOLDER, out)
    return out


def _scrub_people_and_schools(text: str, snapshot: dict, *, keep_school_id=""):
    names, ids = _names_and_ids(snapshot, keep_school_id=keep_school_id)
    owners = {
        str(row["owner"])
        for row in snapshot.get("rows") or []
        if row.get("owner") and str(row["owner"]) in names
    } | {str(p) for p in snapshot.get("people") or [] if p}
    text = scrub(text, names=owners, placeholder=PERSON_PLACEHOLDER)
    return scrub(text, names=names - owners, ids=ids)


# ── Donor ────────────────────────────────────────────────────────────────────


def _donor_cohort(cohort: dict) -> dict:
    measured = cohort.get("measured") or 0
    return {
        "enrolments": count_cell(cohort.get("total") or 0),
        "schools": count_cell(cohort.get("unique_schools") or 0),
        "measured": count_cell(measured),
        "measured_schools": count_cell(cohort.get("measured_schools") or 0),
        "improved": count_cell(cohort.get("improved") or 0),
        "improved_pct": share_cell(cohort.get("improved_pct"), measured),
        "declined": count_cell(cohort.get("declined") or 0),
        "declined_pct": share_cell(cohort.get("declined_pct"), measured),
        "no_change": count_cell(cohort.get("no_change") or 0),
        "maintained": count_cell(cohort.get("maintained") or 0),
        "baseline_missing": count_cell(cohort.get("baseline_missing") or 0),
    }


def _donor_domain(domain: dict) -> dict:
    schools = domain.get("schools") or 0
    return {
        "name": domain.get("name", ""),
        "measured": count_cell(domain.get("pairs") or 0),
        "schools": count_cell(schools),
        "improved_pct": share_cell(domain.get("improved_pct"), schools),
        "declined_pct": share_cell(domain.get("declined_pct"), schools),
        "median_change": share_cell(domain.get("delta"), schools),
    }


def _grade_label(block) -> str:
    grade = (block or {}).get("grade") if isinstance(block, dict) else None
    if isinstance(grade, dict):
        return str(grade.get("label") or "")
    return ""


def _donor_portfolio(portfolio: dict) -> dict:
    measured = portfolio.get("measured") or 0
    return {
        "fy": portfolio.get("fy", ""),
        "prev_fy": portfolio.get("prev_fy", ""),
        "schools_in_scope": count_cell(portfolio.get("schools_in_scope") or 0),
        "measured": count_cell(measured),
        "improved_pct": share_cell(portfolio.get("improved_pct"), measured),
        "declined_pct": share_cell(portfolio.get("declined_pct"), measured),
        "median_interval_days": share_cell(
            portfolio.get("median_interval_days"), measured
        ),
        "rule_label": portfolio.get("rule_label", ""),
        "evidence": _grade_label(portfolio),
        "rows": [
            {
                "name": row.get("name", ""),
                "is_area": bool(row.get("is_area")),
                "measured": count_cell(row.get("n") or 0),
                "improved_pct": share_cell(row.get("improved_pct"), row.get("n") or 0),
                "declined_pct": share_cell(row.get("declined_pct"), row.get("n") or 0),
                "median_change": share_cell(
                    row.get("median_change"), row.get("n") or 0
                ),
                "evidence": _grade_label(row),
            }
            for row in portfolio.get("rows") or []
        ],
    }


def _donor_evidence_block(block: dict, keys: tuple[str, ...]) -> dict:
    """An evidence-beyond-SSA block: every figure, or none of them when it
    rests on 1 to 4 schools."""
    block = block or {}
    schools = block.get("schools") or 0
    if _small(schools):
        return {"schools": SUPPRESSED, SUPPRESSED: True}
    out = {"schools": schools, "evidence": _grade_label(block)}
    for key in keys:
        value = block.get(key)
        # A share of no schools is not measured, never zero.
        out[key] = None if not schools and key.endswith("_pct") else value
    return out


def _donor_evidence(evidence: dict) -> dict:
    evidence = evidence or {}
    return {
        "learning": _donor_evidence_block(
            evidence.get("learning"),
            ("comparisons", "improved_pct", "declined_pct"),
        ),
        "discipleship": _donor_evidence_block(
            evidence.get("discipleship"),
            ("with_groups_pct", "with_lead_pct", "learners_in_groups_pct"),
        ),
        "edtech": _donor_evidence_block(
            evidence.get("edtech"),
            ("deployments", "units", "functional_pct"),
        ),
    }


def _donor_lending(lending: dict) -> dict:
    lending = lending or {}
    return {
        "verified_conclusions": count_cell(len(lending.get("verified_ids") or [])),
        "by_classification": {
            str(label): count_cell(n)
            for label, n in (lending.get("by_classification") or {}).items()
        },
    }


def _count_suppressed(value) -> int:
    if value == SUPPRESSED:
        return 1
    if isinstance(value, dict):
        return sum(_count_suppressed(v) for k, v in value.items() if k != SUPPRESSED)
    if isinstance(value, list):
        return sum(_count_suppressed(v) for v in value)
    return 0


def donor_payload(snapshot: dict, *, narrative: dict, recommendations=()) -> dict:
    report = snapshot.get("report") or {}

    def clean(text):
        return _scrub_people_and_schools(text, snapshot)

    payload = {
        "profile": DONOR,
        "small_cell_threshold": SMALL_CELL,
        "report": {
            "title": clean(report.get("title", "")),
            "country": report.get("country", ""),
            "fy": report.get("fy", ""),
            "period_start": report.get("period_start") or "",
            "period_end": report.get("period_end") or "",
            "programme_areas": list(report.get("programme_area_labels") or []),
            "version": report.get("version", 1),
        },
        "narrative": {
            key: clean(narrative.get(key, ""))
            for key in ("methodology", "findings", "limitations")
        },
        "recommendations": [
            {"text": clean(r.get("text", "")), "owner": r.get("owner_label", "")}
            for r in recommendations
        ],
        "cohort": _donor_cohort(snapshot.get("cohort") or {}),
        "domains": [_donor_domain(d) for d in snapshot.get("domains") or []],
        "portfolio": _donor_portfolio(snapshot.get("portfolio") or {}),
        "evidence": _donor_evidence(snapshot.get("evidence") or {}),
        "lending": _donor_lending(snapshot.get("lending") or {}),
        "limitations": [
            text
            for text in (
                snapshot.get("limitation"),
                (snapshot.get("portfolio") or {}).get("limitation"),
            )
            if text
        ],
    }
    payload["suppressed_cells"] = _count_suppressed(payload)
    return payload


# ── School ───────────────────────────────────────────────────────────────────


def school_payload(
    snapshot: dict, school_id: str, *, school_name: str, narrative: dict
) -> dict:
    report = snapshot.get("report") or {}
    rows = [r for r in snapshot.get("rows") or [] if r.get("school_id") == school_id]

    def clean(text):
        return _scrub_people_and_schools(text, snapshot, keep_school_id=school_id)

    return {
        "profile": SCHOOL,
        "school": {"name": school_name},
        "report": {
            "title": clean(report.get("title", "")),
            "fy": report.get("fy", ""),
            "period_start": report.get("period_start") or "",
            "period_end": report.get("period_end") or "",
            "version": report.get("version", 1),
        },
        "results": [
            {
                "area": row.get("intervention", ""),
                "programme": row.get("project", ""),
                "baseline": row.get("baseline"),
                "follow_up": row.get("follow_up"),
                "change": row.get("delta"),
                "baseline_date": row.get("baseline_date", ""),
                "follow_up_date": row.get("follow_up_date", ""),
                "status": SCHOOL_STATE_LABELS.get(
                    row.get("state", ""), row.get("status", "")
                ),
            }
            for row in rows
        ],
        "narrative": {
            key: clean(narrative.get(key, "")) for key in ("findings", "limitations")
        },
        "limitations": [snapshot.get("limitation")]
        if snapshot.get("limitation")
        else [],
    }


# ── Entry point ──────────────────────────────────────────────────────────────


def redact(
    snapshot: dict,
    profile: str,
    *,
    narrative: dict | None = None,
    recommendations=(),
    school_id: str = "",
    school_name: str = "",
) -> dict:
    """The version of `snapshot` an audience receives."""
    narrative = narrative or {}
    if profile == LEADERSHIP:
        return {
            "profile": LEADERSHIP,
            "snapshot": copy.deepcopy(snapshot),
            "narrative": dict(narrative),
            "recommendations": [dict(r) for r in recommendations],
        }
    if profile == DONOR:
        return donor_payload(
            snapshot, narrative=narrative, recommendations=recommendations
        )
    if profile == SCHOOL:
        if not school_id:
            raise ValueError("A school version names its school.")
        return school_payload(
            snapshot, school_id, school_name=school_name, narrative=narrative
        )
    raise ValueError(f"Unknown redaction profile {profile!r}.")
