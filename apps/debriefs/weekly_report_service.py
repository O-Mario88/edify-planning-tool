"""Weekly Debrief Intelligence — consolidation + role-scoped PDF reports.

Daily debriefs stay simple; this module turns a Monday-Sunday week of them
into decision documents: one PL Weekly Team Report per Program Lead, one CD
Country Report compiled from finalized PL reports plus direct country
reports, an RVP strategic view over finalized country reports, and a
restricted HR people-intelligence summary.

The consolidation rule (mandate §8-§11): repeated observations become ONE
insight cluster per theme carrying total mentions, UNIQUE staff / schools /
districts / activities affected, source-debrief links and a confidence
level. Different root causes are never merged (poor roads ≠ vehicle
unavailable ≠ transport late — each is its own theme). Reports snapshot
their data at generation: late debriefs never silently alter a finalized
report — regeneration creates a new version and supersedes the old one.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole

from .field_debrief_service import team_staff_ids
from .models import (
    DailyDebrief,
    DebriefKind,
    DebriefStatus,
    WeeklyDebriefReport,
    WeeklyReportDistribution,
    WeeklyReportScope,
    WeeklyReportStatus,
)

# ── Theme registry ───────────────────────────────────────────────────────────
# key, label, kind, keyword patterns (case-insensitive, word-ish matching).
# Distinct root causes are DISTINCT themes even when they share vocabulary;
# a text mentioning several themes is tagged with each (never merged).
THEMES: list[tuple[str, str, str, list[str]]] = [
    ("poor_roads", "Poor Road Conditions", "challenge",
     [r"\broads?\b.{0,40}\b(bad|poor|flood|impass|terrible|muddy)",
      r"\b(bad|poor|flooded|muddy|impassable)\b.{0,25}\broads?\b", r"\bpotholes?\b"]),
    ("transport_delay", "Transport Delays", "challenge",
     [r"\btransport\b.{0,40}\b(late|delay)", r"\b(boda|vehicle|car|bus)\b.{0,30}\blate\b",
      r"\barrived late\b.{0,40}\btransport\b"]),
    ("no_transport", "Transport Unavailable", "challenge",
     [r"\bno (transport|vehicle|car)\b", r"\b(vehicle|car|transport)\b.{0,30}\b(unavailable|not available|broke down)"]),
    ("long_distance", "Long Travel Distance", "challenge",
     [r"\blong (travel|distance|journey)\b", r"\bdistan(ce|t)\b.{0,30}\b(far|long|hours)\b",
      r"\btook .{0,12}(hour|hrs)"]),
    ("funds_delayed", "Delayed Funding", "challenge",
     [r"\bfunds?\b.{0,40}\b(delay|late|not (yet )?(received|disbursed))", r"\bno (funds|money)\b",
      r"\bdisbursement\b.{0,30}\bdelay"]),
    ("leader_unavailable", "School Leader Unavailable", "challenge",
     [r"\b(head ?teacher|school leader|proprietor|director)\b.{0,50}\b(unavailable|absent|not (there|present|available|around)|away)"]),
    ("teacher_absence", "Teacher Absence", "challenge",
     [r"\bteachers?\b.{0,40}\b(absent|did not attend|failed to attend|missing|few)"]),
    ("low_attendance", "Low Attendance", "challenge",
     [r"\blow (attendance|turnout)\b", r"\battendance\b.{0,30}\b(low|poor)\b", r"\bfew (participants|attendees)\b"]),
    ("school_closed", "School Closure", "challenge",
     [r"\bschool\b.{0,30}\bclosed\b", r"\bclosure\b"]),
    ("weather", "Weather Disruption", "challenge",
     [r"\b(heavy )?rain\b", r"\bstorm\b", r"\bweather\b"]),
    ("network", "Poor Network / Connectivity", "challenge",
     [r"\b(poor|no|bad|weak)\b.{0,15}\b(network|internet|signal|connectivity)\b"]),
    ("electricity", "Electricity Problems", "challenge",
     [r"\b(no |load.?shed|power (cut|outage|off)|electricity)\b"]),
    ("facilities", "Poor Facilities", "challenge",
     [r"\b(classroom|facility|facilities|building)\b.{0,40}\b(poor|bad|leak|broken|double.?booked|unavailable)"]),
    ("partner_delay", "Partner Delays", "challenge",
     [r"\bpartner\b.{0,50}\b(delay|late|did not|failed|no.?show|not schedule)"]),
    ("workload", "Workload Pressure", "challenge",
     [r"\b(overload|too (many|much)|workload|overwhelm|stretched|back.?to.?back)\b"]),
    ("safety", "Safety Concern", "challenge",
     [r"\b(unsafe|safety|insecur|robbery|accident)\b"]),
    ("health", "Health / Wellbeing", "challenge",
     [r"\b(sick|unwell|ill|malaria|fatigue[d]?|exhaust|burn.?out)\b"]),
    ("materials", "Materials Unavailable", "challenge",
     [r"\bmaterials?\b.{0,30}\b(unavailable|missing|not (there|available)|lack)", r"\bno materials\b"]),
    ("data_tech", "Data / Technology Problems", "challenge",
     [r"\b(system|app|salesforce|data|laptop|phone|tablet)\b.{0,40}\b(problem|error|fail|crash|not work|slow)"]),
    ("ssa_need", "SSA Refresh Needed", "challenge",
     [r"\bssa\b.{0,50}\b(refresh|outdated|missing|needed|expired|stale)", r"\b(fresh|new) ssa\b"]),
    # positives
    ("leader_engaged", "School Leadership Engaged", "positive",
     [r"\b(head ?teacher|school leader|proprietor|leadership)\b.{0,60}\b(available|engaged|supportive|present|welcom|cooperat)"]),
    ("teacher_participation", "Strong Teacher Participation", "positive",
     [r"\bteachers?\b.{0,50}\b(engaged|participat|active|attentive|enthusias)"]),
    ("good_attendance", "Strong Attendance", "positive",
     [r"\b(good|strong|high|full)\b.{0,15}\b(attendance|turnout)\b"]),
    ("partner_coordination", "Good Partner Coordination", "positive",
     [r"\bpartner\b.{0,50}\b(coordinat|on time|delivered|support|well)"]),
    ("transport_on_time", "Transport On Time", "positive",
     [r"\btransport\b.{0,30}\b(on time|early|smooth)"]),
    ("team_support", "Good Team Support", "positive",
     [r"\bteam\b.{0,40}\b(support|helped|collaborat)"]),
]

_COMPILED = [
    (key, label, kind, [re.compile(p, re.IGNORECASE) for p in pats])
    for key, label, kind, pats in THEMES
]


def classify_text(text: str) -> list[str]:
    """Theme keys present in the text. Multi-theme text gets every match —
    consolidation happens per theme, so different root causes never merge."""
    if not text:
        return []
    return [key for key, _label, _kind, pats in _COMPILED if any(p.search(text) for p in pats)]


def theme_label(key: str) -> str:
    for k, label, _kind, _p in _COMPILED:
        if k == key:
            return label
    return key.replace("_", " ").title()


def week_bounds(anchor: date | None = None) -> tuple[date, date]:
    """The canonical Edify reporting week: Monday → Sunday. With no anchor,
    the most recently COMPLETED week (report weeks close on Sunday night)."""
    today = anchor or (timezone.localdate() - timedelta(days=7))
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


# ── Consolidation ────────────────────────────────────────────────────────────


def _consolidate(debriefs: list[DailyDebrief]) -> list[dict]:
    """Build insight clusters from a week of daily debriefs. Each cluster
    carries total mentions AND unique-record counts (mandate §11): one staff
    member repeating an issue five times is five mentions, one staff."""
    from apps.schools.models import School

    school_ids = set()
    for d in debriefs:
        school_ids.update(d.linked_school_ids or [])
    districts = dict(
        School.objects.filter(id__in=school_ids).values_list("id", "district__name")
    )

    clusters: dict[str, dict] = {}
    field_kinds = [
        ("challenges_faced", "challenge"),
        ("what_did_not_go_well", "challenge"),
        ("what_went_well", "positive"),
        ("recommendations", "suggestion"),
    ]
    for d in debriefs:
        for field, want_kind in field_kinds:
            text = getattr(d, field, None)
            if not text:
                continue
            for key in classify_text(text):
                kind = next(k for tk, _l, k, _p in _COMPILED if tk == key)
                # A challenge keyword inside "what worked well" (or vice
                # versa) is ambiguous — record it at low confidence rather
                # than dropping or mis-merging it.
                mismatched = (want_kind == "positive") != (kind == "positive")
                c = clusters.setdefault(
                    key,
                    {
                        "theme": key,
                        "label": theme_label(key),
                        "kind": kind,
                        "mentions": 0,
                        "staff": set(),
                        "schools": set(),
                        "districts": set(),
                        "activities": set(),
                        "dates": set(),
                        "sources": [],
                        "low_confidence_hits": 0,
                    },
                )
                c["mentions"] += 1
                c["staff"].add(d.submitted_by_user_id)
                c["schools"].update(d.linked_school_ids or [])
                c["districts"].update(
                    districts.get(s) for s in (d.linked_school_ids or []) if districts.get(s)
                )
                c["activities"].update(d.linked_activity_ids or [])
                c["dates"].add(str(d.date.date()))
                if mismatched:
                    c["low_confidence_hits"] += 1
                if len(c["sources"]) < 5:
                    c["sources"].append(
                        {"debrief_id": d.id, "excerpt": text.strip()[:180]}
                    )

    out = []
    for c in clusters.values():
        unique_staff = len(c["staff"])
        confidence = (
            "low"
            if c["low_confidence_hits"] >= c["mentions"]
            else "high"
            if unique_staff >= 2
            else "medium"
        )
        out.append(
            {
                "theme": c["theme"],
                "label": c["label"],
                "kind": c["kind"],
                "mentions": c["mentions"],
                "unique_staff": unique_staff,
                "schools_affected": len(c["schools"]),
                "school_ids": sorted(c["schools"]),
                "districts_affected": sorted(c["districts"]),
                "activities_affected": len(c["activities"]),
                "dates": sorted(c["dates"]),
                "confidence": confidence,
                "sources": c["sources"],
                "severity": (
                    "high"
                    if c["kind"] == "challenge" and unique_staff >= 3
                    else "medium"
                    if c["kind"] == "challenge"
                    else "info"
                ),
            }
        )
    # Challenges first, ranked by reach; then suggestions; positives last.
    kind_rank = {"challenge": 0, "suggestion": 1, "positive": 2}
    out.sort(key=lambda c: (kind_rank[c["kind"]], -c["unique_staff"], -c["mentions"]))
    return out


def _trend(clusters: list[dict], previous: WeeklyDebriefReport | None) -> None:
    prev_themes = {}
    if previous:
        for c in previous.snapshot.get("clusters", []):
            prev_themes[c["theme"]] = c
    for c in clusters:
        p = prev_themes.get(c["theme"])
        if not p:
            c["trend"] = "new"
        elif c["unique_staff"] > p.get("unique_staff", 0):
            c["trend"] = "worsening"
        elif c["unique_staff"] < p.get("unique_staff", 0):
            c["trend"] = "improving"
        else:
            c["trend"] = "repeated"


# ── Report generation ────────────────────────────────────────────────────────


class WeeklyDebriefReportService:
    @staticmethod
    def _week_debriefs(user_ids: list[str], start: date, end: date):
        return list(
            DailyDebrief.objects.filter(
                submitted_by_user_id__in=user_ids,
                kind=DebriefKind.DAILY,
                date__date__range=(start, end),
                deleted_at__isnull=True,
                is_restricted_incident=False,  # §24 — never in general reports
            )
            .exclude(status=DebriefStatus.DRAFT)
            .order_by("date")
        )

    @staticmethod
    def _pl_member_users(pl_user) -> list[tuple[str, str]]:
        """(user_id, name) for the PL and every supervised team member."""
        from apps.accounts.models import StaffProfile

        sp = StaffProfile.objects.filter(user=pl_user).first()
        members = [(pl_user.user_id, pl_user.name)]
        if sp:
            supervised = StaffProfile.objects.filter(
                id__in=team_staff_ids(sp.id)
            ).select_related("user")
            members += [(s.user.user_id, s.user.name) for s in supervised if s.user]
        return members

    @staticmethod
    def _previous_finalized(scope_kind, scope_id, week_start) -> WeeklyDebriefReport | None:
        return (
            WeeklyDebriefReport.objects.filter(
                scope_kind=scope_kind,
                scope_id=scope_id,
                week_start=week_start - timedelta(days=7),
                status=WeeklyReportStatus.FINALIZED,
            )
            .order_by("-version")
            .first()
        )

    # ── PL team report ───────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def generate_pl_report(pl_user, week_start: date | None = None, generated_by=None):
        start, end = week_bounds(week_start)
        members = WeeklyDebriefReportService._pl_member_users(pl_user)
        debriefs = WeeklyDebriefReportService._week_debriefs(
            [uid for uid, _ in members], start, end
        )
        submitted_ids = {d.submitted_by_user_id for d in debriefs}
        clusters = _consolidate(debriefs)
        _trend(
            clusters,
            WeeklyDebriefReportService._previous_finalized(
                WeeklyReportScope.PL_TEAM, pl_user.user_id, start
            ),
        )

        schools, activities, work_days = set(), set(), set()
        for d in debriefs:
            schools.update(d.linked_school_ids or [])
            activities.update(d.linked_activity_ids or [])
            work_days.add((d.submitted_by_user_id, str(d.date.date())))

        snapshot = {
            "week_start": str(start),
            "week_end": str(end),
            "team": [{"user_id": u, "name": n, "submitted": u in submitted_ids} for u, n in members],
            "totals": {
                "members": len(members),
                "reporting": len(submitted_ids),
                "debriefs": len(debriefs),
                "activities_worked": len(activities),
                "schools_supported": len(schools),
                "person_days": len(work_days),
            },
            "clusters": clusters,
            "source_debrief_ids": [d.id for d in debriefs],
        }
        return WeeklyDebriefReportService._store(
            WeeklyReportScope.PL_TEAM, pl_user.user_id, start, end, snapshot,
            generated_by or pl_user,
        )

    # ── Country report (compiled from finalized PL reports + direct) ─────────
    @staticmethod
    @transaction.atomic
    def generate_country_report(cd_user, week_start: date | None = None):
        from apps.accounts.models import StaffProfile, User

        country = getattr(
            StaffProfile.objects.filter(user=cd_user).first(), "country", None
        ) or "Unknown"
        start, end = week_bounds(week_start)

        pl_users = list(
            User.objects.filter(
                active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
                staff_profile__country=country,
                is_active=True,
            )
        )
        pl_reports, missing_teams = [], []
        for pl in pl_users:
            r = (
                WeeklyDebriefReport.objects.filter(
                    scope_kind=WeeklyReportScope.PL_TEAM,
                    scope_id=pl.user_id,
                    week_start=start,
                )
                .exclude(status=WeeklyReportStatus.SUPERSEDED)
                .order_by("-version")
                .first()
            )
            if r and r.status == WeeklyReportStatus.FINALIZED:
                pl_reports.append((pl, r))
            else:
                missing_teams.append({"pl": pl.name, "status": r.status if r else "missing"})

        # Direct country reports (no PL team of their own): PC, IA, Accountant.
        direct_roles = (
            EdifyRole.PROJECT_COORDINATOR.value,
            EdifyRole.IMPACT_ASSESSMENT.value,
            EdifyRole.PROGRAM_ACCOUNTANT.value,
        )
        direct_ids = list(
            User.objects.filter(
                active_role__in=direct_roles,
                staff_profile__country=country,
                is_active=True,
            ).values_list("id", flat=True)
        )
        direct_debriefs = WeeklyDebriefReportService._week_debriefs(direct_ids, start, end)

        # Merge PL clusters + direct-report clusters by theme (§5): counts stay
        # unique because staff/school id SETS are merged, never summed blindly.
        merged: dict[str, dict] = {}
        for pl, r in pl_reports:
            for c in r.snapshot.get("clusters", []):
                m = merged.setdefault(
                    c["theme"],
                    {**c, "staff_set": set(), "school_set": set(),
                     "district_set": set(), "pl_teams": set(), "mentions": 0,
                     "activities_affected": 0, "sources": []},
                )
                m["mentions"] += c["mentions"]
                m["activities_affected"] += c["activities_affected"]
                m["pl_teams"].add(pl.name)
                m["school_set"].update(c.get("school_ids", []))
                m["district_set"].update(c.get("districts_affected", []))
                # unique staff can't be re-derived from counts — carry the max
                # lower bound and the union where ids are present.
                m["staff_set"].update(
                    s["debrief_id"] for s in c.get("sources", [])
                )
                m["sources"] += c.get("sources", [])[:2]
        direct_clusters = _consolidate(direct_debriefs)
        for c in direct_clusters:
            m = merged.setdefault(
                c["theme"],
                {**c, "staff_set": set(), "school_set": set(),
                 "district_set": set(), "pl_teams": set(), "mentions": 0,
                 "activities_affected": 0, "sources": []},
            )
            m["mentions"] += c["mentions"]
            m["activities_affected"] += c["activities_affected"]
            m["pl_teams"].add("Direct reports")
            m["school_set"].update(c.get("school_ids", []))
            m["district_set"].update(c.get("districts_affected", []))
            m["sources"] += c.get("sources", [])[:2]

        clusters = []
        for m in merged.values():
            unique_staff_floor = max(
                m.get("unique_staff", 0), len(m.pop("staff_set"))
            )
            schools = m.pop("school_set")
            districts = m.pop("district_set")
            teams = m.pop("pl_teams")
            clusters.append(
                {
                    **{k: v for k, v in m.items() if k not in ("school_ids",)},
                    "unique_staff": unique_staff_floor,
                    "schools_affected": max(m.get("schools_affected", 0), len(schools)),
                    "districts_affected": sorted(districts),
                    "pl_teams": sorted(teams),
                }
            )
        kind_rank = {"challenge": 0, "suggestion": 1, "positive": 2}
        clusters.sort(key=lambda c: (kind_rank[c["kind"]], -c["unique_staff"]))
        _trend(
            clusters,
            WeeklyDebriefReportService._previous_finalized(
                WeeklyReportScope.COUNTRY, country, start
            ),
        )

        totals = {
            "pl_reports_included": len(pl_reports),
            "pl_reports_missing": len(missing_teams),
            "direct_debriefs": len(direct_debriefs),
            "debriefs": sum(
                r.snapshot["totals"]["debriefs"] for _, r in pl_reports
            )
            + len(direct_debriefs),
            "schools_supported": len(
                set().union(
                    *(
                        set(
                            s
                            for c in r.snapshot.get("clusters", [])
                            for s in c.get("school_ids", [])
                        )
                        for _, r in pl_reports
                    ),
                    {s for d in direct_debriefs for s in (d.linked_school_ids or [])},
                )
            )
            if (pl_reports or direct_debriefs)
            else 0,
        }
        snapshot = {
            "week_start": str(start),
            "week_end": str(end),
            "country": country,
            "totals": totals,
            "missing_teams": missing_teams,
            "pl_reports": [
                {"pl": pl.name, "report_id": r.id, "version": r.version}
                for pl, r in pl_reports
            ],
            "clusters": clusters,
        }
        return WeeklyDebriefReportService._store(
            WeeklyReportScope.COUNTRY, country, start, end, snapshot, cd_user
        )

    @staticmethod
    def _store(scope_kind, scope_id, start, end, snapshot, by) -> WeeklyDebriefReport:
        """Versioned upsert: a draft regenerates in place; a finalized report
        is superseded by a NEW version (mandate §17 — never overwrite)."""
        current = (
            WeeklyDebriefReport.objects.filter(
                scope_kind=scope_kind, scope_id=scope_id, week_start=start
            )
            .exclude(status=WeeklyReportStatus.SUPERSEDED)
            .order_by("-version")
            .first()
        )
        if current and current.status == WeeklyReportStatus.DRAFT:
            current.snapshot = snapshot
            current.generated_by_user_id = by.user_id
            current.save(update_fields=["snapshot", "generated_by_user_id", "updated_at"])
            return current
        version = (current.version + 1) if current else 1
        if current:
            current.status = WeeklyReportStatus.SUPERSEDED
            current.save(update_fields=["status", "updated_at"])
        return WeeklyDebriefReport.objects.create(
            fy=get_operational_fy(),
            scope_kind=scope_kind,
            scope_id=scope_id,
            week_start=start,
            week_end=end,
            version=version,
            snapshot=snapshot,
            generated_by_user_id=by.user_id,
        )

    # ── Sign-off ─────────────────────────────────────────────────────────────
    @staticmethod
    def sign(report: WeeklyDebriefReport, principal, commentary: str | None = None):
        role = getattr(principal, "active_role", "")
        owns = (
            report.scope_kind == WeeklyReportScope.PL_TEAM
            and report.scope_id == principal.user_id
        ) or (
            report.scope_kind == WeeklyReportScope.COUNTRY
            and role == EdifyRole.COUNTRY_DIRECTOR.value
        )
        if not (owns or role == EdifyRole.ADMIN.value):
            raise Forbidden("Only the report owner may sign it.")
        if report.status == WeeklyReportStatus.FINALIZED:
            raise BadRequest("This report is already finalized.")
        if commentary:
            report.commentary = commentary
        report.status = WeeklyReportStatus.FINALIZED
        report.signed_by_user_id = principal.user_id
        report.signed_at = timezone.now()
        report.save(
            update_fields=["status", "signed_by_user_id", "signed_at", "commentary", "updated_at"]
        )
        return report

    # ── Read scope ───────────────────────────────────────────────────────────
    @staticmethod
    def visible_report(principal, week_start: date | None = None):
        """The report this principal's role lands on (RVP/HR read country
        reports; employee-level drill-down stays scope-controlled)."""
        from apps.accounts.models import StaffProfile

        role = getattr(principal, "active_role", "")
        start, _end = week_bounds(week_start)
        if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
            q = {"scope_kind": WeeklyReportScope.PL_TEAM, "scope_id": principal.user_id}
        elif role in (
            EdifyRole.COUNTRY_DIRECTOR.value,
            EdifyRole.HUMAN_RESOURCES.value,
            EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            EdifyRole.ADMIN.value,
        ):
            country = getattr(
                StaffProfile.objects.filter(user=principal).first(), "country", None
            )
            q = {"scope_kind": WeeklyReportScope.COUNTRY}
            if country and role == EdifyRole.COUNTRY_DIRECTOR.value:
                q["scope_id"] = country
        else:
            return None
        qs = WeeklyDebriefReport.objects.filter(week_start=start, **q).exclude(
            status=WeeklyReportStatus.SUPERSEDED
        )
        # RVP and HR consume the finalized country intelligence only —
        # never a CD's in-progress draft (mandate §6).
        if role in (
            EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            EdifyRole.HUMAN_RESOURCES.value,
        ):
            qs = qs.filter(status=WeeklyReportStatus.FINALIZED)
        return qs.order_by("-version").first()

    # ── PDF (fpdf2 — A4, branded, print-ready; mandate §16) ─────────────────
    @staticmethod
    def _pdf_safe(text: str) -> str:
        """Core PDF fonts are latin-1; transliterate typographic characters
        rather than crash on an em-dash in someone's narrative."""
        table = {"\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'",
                 "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00b7": " - "}
        for k, v in table.items():
            text = text.replace(k, v)
        return text.encode("latin-1", "replace").decode("latin-1")

    @staticmethod
    def pdf_bytes(report: WeeklyDebriefReport) -> bytes:
        from fpdf import FPDF

        s = report.snapshot
        title = {
            WeeklyReportScope.PL_TEAM: "Weekly Team Debrief Report",
            WeeklyReportScope.COUNTRY: "Weekly Country Debrief Report",
        }.get(report.scope_kind, "Weekly Debrief Report")

        pdf = FPDF(format="A4")
        pdf.set_auto_page_break(auto=True, margin=18)
        pdf.add_page()

        def h(text, size=13, top=4):
            pdf.ln(top)
            pdf.set_font("Helvetica", "B", size)
            pdf.set_text_color(13, 91, 158)  # --brand-primary
            pdf.cell(0, 8, WeeklyDebriefReportService._pdf_safe(text), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(23, 35, 43)

        def p(text, size=9.5, style=""):
            pdf.set_font("Helvetica", style, size)
            pdf.multi_cell(0, 5, WeeklyDebriefReportService._pdf_safe(text), new_x="LMARGIN", new_y="NEXT")

        # Cover header
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(0, 29, 57)
        pdf.cell(0, 10, "Edify", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(95, 112, 122)
        pdf.cell(
            0, 6,
            f"Reporting week {report.week_start.strftime('%-d %b')} - "
            f"{report.week_end.strftime('%-d %b %Y')}  -  Version {report.version}"
            f"  -  Generated {timezone.localdate().strftime('%-d %b %Y')}",
            new_x="LMARGIN", new_y="NEXT",
        )
        pdf.set_text_color(23, 35, 43)

        totals = s.get("totals", {})
        h("Week at a Glance")
        glance = [
            f"Debriefs submitted: {totals.get('debriefs', 0)}",
            f"Activities worked on: {totals.get('activities_worked', totals.get('direct_debriefs', 0))}",
            f"Schools supported: {totals.get('schools_supported', 0)}",
        ]
        if report.scope_kind == WeeklyReportScope.PL_TEAM:
            glance.insert(
                0,
                f"Team reporting: {totals.get('reporting', 0)} of {totals.get('members', 0)}",
            )
        else:
            glance.insert(
                0,
                f"PL reports included: {totals.get('pl_reports_included', 0)}"
                f" · missing: {totals.get('pl_reports_missing', 0)}",
            )
        p("   ".join(glance))

        if s.get("missing_teams"):
            h("Data Completeness", 11)
            for m in s["missing_teams"]:
                p(f"- {m['pl']}: team report {m['status']}", style="I")

        def cluster_block(kind, heading):
            rows = [c for c in s.get("clusters", []) if c["kind"] == kind]
            if not rows:
                return
            h(heading)
            for c in rows:
                pdf.set_font("Helvetica", "B", 10.5)
                trend = {"new": "New", "repeated": "Repeated", "worsening": "Worsening", "improving": "Improving"}.get(c.get("trend", ""), "")
                pdf.multi_cell(0, 5.5, WeeklyDebriefReportService._pdf_safe(f"{c['label']}" + (f"  [{trend}]" if trend else "")), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 9)
                pdf.set_text_color(95, 112, 122)
                scope_bits = [
                    f"{c['mentions']} mention(s)",
                    f"{c['unique_staff']} staff",
                    f"{c['schools_affected']} school(s)",
                ]
                if c.get("districts_affected"):
                    scope_bits.append(
                        f"districts: {', '.join(c['districts_affected'][:4])}"
                    )
                if c.get("pl_teams"):
                    scope_bits.append(f"teams: {', '.join(c['pl_teams'][:4])}")
                scope_bits.append(f"confidence: {c['confidence']}")
                pdf.multi_cell(0, 4.5, WeeklyDebriefReportService._pdf_safe(" - ".join(scope_bits)), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(23, 35, 43)
                for src in c.get("sources", [])[:2]:
                    p(f'  "{src["excerpt"]}"', size=8.5, style="I")
                pdf.ln(1.5)

        cluster_block("challenge", "Key Challenges")
        cluster_block("suggestion", "Staff Suggestions")
        cluster_block("positive", "What Worked Well")

        if report.scope_kind == WeeklyReportScope.PL_TEAM and s.get("team"):
            h("Team Submission Status", 11)
            for m in s["team"]:
                p(f"- {m['name']}: {'submitted' if m['submitted'] else 'NOT submitted'}", size=9)

        if report.commentary:
            h("Leadership Commentary", 11)
            p(report.commentary)

        pdf.set_y(-24)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(95, 112, 122)
        signed = (
            f"Signed and finalized {report.signed_at.strftime('%-d %b %Y %H:%M')}"
            if report.signed_at
            else "Draft - not yet signed"
        )
        pdf.cell(0, 5, WeeklyDebriefReportService._pdf_safe(f"Edify Planning & Monitoring  -  {signed}  -  Internal use"), align="C")

        return bytes(pdf.output())

    @staticmethod
    def generate_pdf(report: WeeklyDebriefReport) -> bytes:
        data = WeeklyDebriefReportService.pdf_bytes(report)
        report.pdf_checksum = hashlib.sha256(data).hexdigest()
        report.pdf_generated_at = timezone.now()
        report.save(update_fields=["pdf_checksum", "pdf_generated_at", "updated_at"])
        return data

    # ── Email distribution (§19) ─────────────────────────────────────────────
    @staticmethod
    def send_email(report, principal, to: list[str], subject: str, message: str):
        from django.core.mail import EmailMessage

        role = getattr(principal, "active_role", "")
        allowed = (
            report.scope_kind == WeeklyReportScope.PL_TEAM
            and report.scope_id == principal.user_id
        ) or role in (
            EdifyRole.COUNTRY_DIRECTOR.value,
            EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            EdifyRole.ADMIN.value,
        )
        if not allowed:
            raise Forbidden("You cannot distribute this report.")
        to = [t.strip() for t in to if t and t.strip()]
        if not to:
            raise BadRequest("Add at least one recipient.")
        # Repeated-click guard: identical version+recipients within 5 minutes.
        recent = WeeklyReportDistribution.objects.filter(
            report=report,
            report_version=report.version,
            recipients=to,
            succeeded=True,
            created_at__gte=timezone.now() - timedelta(minutes=5),
        ).exists()
        if recent:
            raise BadRequest("This report was just sent to those recipients.")

        data = WeeklyDebriefReportService.generate_pdf(report)
        start, end = report.week_start, report.week_end
        scope_slug = re.sub(r"[^A-Za-z0-9]+", "_", str(report.scope_id))[:40]
        filename = (
            f"Edify_{'PL' if report.scope_kind == WeeklyReportScope.PL_TEAM else 'Country'}"
            f"_Weekly_Debrief_{scope_slug}_{start}_to_{end}.pdf"
        )
        dist = WeeklyReportDistribution.objects.create(
            report=report,
            sent_by_user_id=principal.user_id,
            recipients=to,
            subject=subject,
            report_version=report.version,
        )
        try:
            email = EmailMessage(subject=subject, body=message, to=to)
            email.attach(filename, data, "application/pdf")
            email.send(fail_silently=False)
            dist.succeeded = True
            dist.save(update_fields=["succeeded", "updated_at"])
        except Exception as exc:  # record, surface, allow safe retry
            dist.error = str(exc)[:500]
            dist.save(update_fields=["error", "updated_at"])
            raise BadRequest(f"Email failed to send: {exc}") from exc
        return dist
