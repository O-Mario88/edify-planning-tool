"""Oracle for the Budget ledger: budget_workspace, budget_groups and
planned_lines_for_period.

The 2026-09-24 performance change reads the selected period's cost lines as
plain rows instead of models, looks each activity-type label up once instead
of per line, and sums the four horizons in one query instead of four. The
`_frozen_*` functions below are copies of the implementations before
that change (commit 4425605), renamed and calling each other; every test
asserts the live code returns exactly what they return, on fixtures covering
an empty scope, two fiscal years, legacy month-only rows, missing owners,
excluded and deleted work, mixed rates and equal-total ties.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db.models import Q, Sum
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.services import (
    NON_FUNDABLE_ACTIVITY_STATUSES,
    _calendar_periods,
    _month_start_for_key,
    _workspace_owner_ids,
    budget_groups,
    budget_workspace,
    cost_line_rows,
    planned_lines_for_period,
)
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope
from apps.geography.models import District, Region
from apps.monthly_work_plan.models import AdminBudgetLine, MonthlyWorkPlanBudget
from apps.partners.models import Partner
from apps.schools.models import School

# ── Frozen reference (pre-change implementations, commit 4425605) ───────────


def _frozen_planned_lines_for_period(lines, start, end):
    """Use actual cost dates; legacy month-only rows belong to whole months.

    A legacy monthly amount cannot be assigned to an invented week. Such rows
    remain in monthly/quarterly/annual totals, with their recorded fiscal year.
    """
    import calendar

    months = []
    cursor = start.replace(day=1)
    while cursor <= end:
        last = cursor.replace(day=calendar.monthrange(cursor.year, cursor.month)[1])
        if start <= cursor and last <= end:
            months.append(cursor.month)
        cursor = last + timedelta(days=1)
    return lines.filter(
        Q(planned_date__range=(start, end))
        | Q(planned_date__isnull=True, month__in=months)
    )


def _frozen_budget_groups(
    selected_lines,
    user_names,
    *,
    admin_lines=(),
    selected=None,
    include_admin=False,
    selected_period="week",
):
    """One activity/item ledger for planned budgets and submitted snapshots."""
    # A training or meeting is funded by the headcount confirmed at scheduling
    # time.  Actual attendance takes precedence after completion; historical
    # cost lines remain a fallback for pre-headcount records created before the
    # dedicated Activity.expected_participants field was introduced.
    training_types = {
        "training",
        "in_school_training",
        "school_improvement_training",
        "cluster_training",
        "core_training",
        "cluster_training_ssa_collection",
    }
    meeting_types = {"cluster_meeting", "cluster_meeting_ssa_review"}
    participant_line_types = {
        "participant_meals",
        "cluster_meeting_participant_meals",
        "mobilisation",
    }
    participant_setting_keys = {
        "group_training_participant_meal_cost_per_head",
        "cluster_meeting_participant_meal_cost_per_head",
        "meals_per_participant",
        "mobilisation_per_participant",
        "cluster_meeting_cost",
    }

    def table_kind(activity) -> str:
        # A non-school programme activity keeps the operational workflow type
        # needed by costing (for example ``partner_activity``) as well as the
        # leadership reporting category selected from the governed catalogue.
        # The reporting category must win for an Admin programme item; treating
        # every unfamiliar workflow type as ``standard`` put Admin money in the
        # School Visits tile even though the schedule and catalogue both called
        # it Admin.
        if activity.programme_activity_type == "admin":
            return "admin"
        activity_type = activity.activity_type
        if activity_type in meeting_types:
            return "meeting"
        if activity_type in training_types:
            return "training"
        return "standard"

    scheduled_participants: dict[str, int] = {}
    for line in selected_lines:
        activity = line.activity
        actual_attendance = sum(
            int(value or 0)
            for value in (
                activity.teachers_attended,
                activity.leaders_attended,
                activity.other_participants,
            )
        )
        if actual_attendance:
            scheduled_participants[activity.id] = actual_attendance
            continue
        if activity.expected_participants:
            scheduled_participants[activity.id] = int(activity.expected_participants)
            continue
        if table_kind(activity) in {"training", "meeting"} and (
            line.line_item_type in participant_line_types
            or line.cost_setting_key in participant_setting_keys
        ):
            scheduled_participants[activity.id] = max(
                scheduled_participants.get(activity.id, 0), int(line.quantity or 0)
            )

    groups: dict[str, dict] = {}
    for line in selected_lines:
        activity = line.activity
        activity_label = (
            activity.get_programme_activity_type_display()
            if activity.programme_activity_type
            else activity.get_activity_type_display()
        )
        group = groups.setdefault(
            activity_label,
            {
                "label": activity_label,
                "table_kind": table_kind(activity),
                "rows": {},
                "total": 0,
                "staff_total": 0,
                "vendor_total": 0,
                "activity_ids": set(),
            },
        )
        item_label = line.label or line.cost_setting_key.replace("_", " ").title()
        # A partner-delivered training's lump sum IS the facilitation fee for
        # that session (owner, 2026-08-18): one table row for both delivery
        # channels, with the partner share carried by vendor_total rather than
        # a second look-alike line item. The ledger keys stay distinct — only
        # the display row merges.
        if line.cost_setting_key == "partner_training_lump_sum":
            item_label = "Facilitation fee"
        row = group["rows"].setdefault(
            item_label,
            {
                "item": item_label,
                "dates": set(),
                "activity_ids": set(),
                "activity_people": {},
                "rates": set(),
                "owners": set(),
                "staff_total": 0,
                "vendor_total": 0,
                "total": 0,
            },
        )
        row["dates"].add(line.planned_date)
        participant_count = scheduled_participants.get(activity.id, 1)
        row["activity_people"].setdefault(activity.id, participant_count)
        row["activity_ids"].add(activity.id)
        row["rates"].add(int(line.unit_cost or 0))
        if line.responsible_user:
            row["owners"].add(user_names.get(line.responsible_user, "Staff"))
        is_vendor = activity.delivery_type == "partner" or line.partner_id is not None
        amount = int(line.amount or 0)
        if is_vendor:
            row["vendor_total"] += amount
            group["vendor_total"] += amount
        else:
            row["staff_total"] += amount
            group["staff_total"] += amount
        row["total"] += amount
        group["total"] += amount
        group["activity_ids"].add(activity.id)

    if include_admin and selected_period != "week":
        admin_group = None
        for line in admin_lines:
            planned = _month_start_for_key(line.monthly_budget.month_key)
            if not planned or not (selected["start"] <= planned <= selected["end"]):
                continue
            if admin_group is None:
                admin_group = {
                    "label": "Country Admin Plan",
                    "table_kind": "admin",
                    "rows": {},
                    "total": 0,
                    "staff_total": 0,
                    "vendor_total": 0,
                    "activity_ids": set(),
                    "is_admin": True,
                }
                groups[admin_group["label"]] = admin_group
            item_label = (
                line.description or line.cost_category.replace("_", " ").title()
            )
            row = admin_group["rows"].setdefault(
                item_label,
                {
                    "item": item_label,
                    "dates": set(),
                    "activity_ids": set(),
                    "activity_people": {},
                    "rates": set(),
                    "owners": {"Country admin"},
                    "staff_total": 0,
                    "vendor_total": 0,
                    "total": 0,
                    "admin_quantity": 0,
                },
            )
            amount = int(line.total_cost or 0)
            row["dates"].add(planned)
            row["rates"].add(int(line.unit_cost or 0))
            row["admin_quantity"] += line.quantity
            row["staff_total"] += amount
            row["total"] += amount
            admin_group["staff_total"] += amount
            admin_group["total"] += amount

    formatted_groups = []
    for group in groups.values():
        rows = []
        for row in group["rows"].values():
            rates = sorted(row["rates"])
            rows.append(
                {
                    "item": row["item"],
                    "days": row.get("admin_quantity") or len(row["dates"]),
                    "activity_count": len(row["activity_ids"]),
                    "people": sum(row["activity_people"].values()) or "—",
                    "rate": rates[0] if len(rates) == 1 else None,
                    "mixed_rate": len(rates) > 1,
                    "owners": ", ".join(sorted(row["owners"])) or "—",
                    "staff_total": row["staff_total"],
                    "vendor_total": row["vendor_total"],
                    "total": row["total"],
                }
            )
        formatted_groups.append(
            {
                "label": group["label"],
                "table_kind": group["table_kind"],
                "rows": sorted(rows, key=lambda item: (-item["total"], item["item"])),
                "total": group["total"],
                "staff_total": group["staff_total"],
                "vendor_total": group["vendor_total"],
                "activity_count": len(group["activity_ids"]),
                "is_admin": group.get("is_admin", False),
            }
        )
    formatted_groups.sort(key=lambda item: (-item["total"], item["label"]))

    return formatted_groups


def _frozen_budget_workspace(principal, query: dict) -> dict:
    """Return a role-scoped budget ledger backed by authoritative cost rows.

    Canonical schedule cost lines supply every amount.  Weekly and monthly
    fund requests are snapshots of those lines, so their counts are surfaced
    for traceability but their totals are never added again. This keeps the
    page mathematically correct while still showing that scheduled work has
    reached the funding workflow.
    """
    from apps.accounts.models import User
    from apps.activities.models import ActivityScheduleCostLine
    from apps.fund_requests.models import (
        FundRequest,
        FundRequestPeriod,
        WeeklyFundRequest,
    )
    from apps.monthly_work_plan.models import AdminBudgetLine

    scope = resolve_user_scope(principal)
    try:
        anchor = (
            date.fromisoformat(str(query.get("date"))[:10])
            if query.get("date")
            else None
        )
    except ValueError:
        anchor = None
    anchor = anchor or timezone.localdate()
    fy = query.get("fy") or get_operational_fy(anchor)
    periods = _calendar_periods(fy, anchor)
    selected_period = query.get("period") if query.get("period") in periods else "week"
    selected = periods[selected_period]
    is_program_lead = scope.active_role == "Program Lead"
    requested_scope = query.get("budget_scope")
    # The Consolidated Fund Allocation page asks for the whole-country roll-up.
    # Honour it only for roles authorised to see national finance data, so a
    # personal My Budget page cannot be widened by a query parameter.
    country_allowed = scope.country_scope or getattr(principal, "active_role", "") in (
        "CountryDirector",
        "Admin",
        "RegionalVicePresident",
        "Accountant",
    )
    admin_allowed = getattr(principal, "active_role", "") in (
        "CountryDirector",
        "Admin",
    )
    if requested_scope == "admin" and admin_allowed:
        budget_scope = "admin"
    elif requested_scope == "country" and country_allowed:
        budget_scope = "country"
    elif is_program_lead and requested_scope == "team":
        budget_scope = "team"
    else:
        budget_scope = "my"

    if budget_scope == "country":
        # No owner filter → every scheduled, costed activity nationally.
        # The CD's administrative plan is included as its own "Country Admin
        # Plan" category so the Monthly Fund Request shows the full monthly
        # envelope the RVP is approving.
        owner_ids = None
        include_admin = True
    elif budget_scope == "admin":
        # The CD's operating budget is a separate ledger.  It is deliberately
        # empty of activity cost lines so "Admin Budget" cannot quietly become
        # another country-programme total.
        owner_ids = []
        include_admin = True
    else:
        owner_ids = _workspace_owner_ids(
            principal, scope, include_team=budget_scope == "team"
        )
        include_admin = False

    # A manager reviewing one member at a time: `staff` narrows the ledger to
    # that owner. Validated here, never trusted from the URL — outside country
    # scope only the viewer themselves or someone they supervise is honoured,
    # so a query parameter cannot widen a personal budget.
    requested_staff = str(query.get("staff") or "").strip()
    if requested_staff and budget_scope != "admin":
        if country_allowed:
            staff_ok = True
        else:
            team_ids = _workspace_owner_ids(principal, scope, include_team=True) or []
            staff_ok = requested_staff in team_ids
        if staff_ok:
            from apps.accounts.models import StaffProfile

            owner_ids = [
                requested_staff,
                *StaffProfile.objects.filter(user_id=requested_staff).values_list(
                    "id", flat=True
                ),
            ]

    base_lines = (
        ActivityScheduleCostLine.objects.filter(
            fiscal_year=fy,
            activity__deleted_at__isnull=True,
        )
        .filter(
            Q(activity__scheduled_date__isnull=False)
            | Q(activity__planned_date__isnull=False)
        )
        .exclude(activity__status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
        .select_related("activity", "partner")
    )
    if owner_ids is not None:
        base_lines = base_lines.filter(
            Q(responsible_user__in=owner_ids)
            | Q(
                activity__delivery_type="partner",
                activity__monitored_by_staff_id__in=owner_ids,
            )
            | (Q(responsible_user__isnull=True) | Q(responsible_user=""))
            & (
                Q(activity__responsible_staff_id__in=owner_ids)
                | Q(
                    activity__delivery_type="partner",
                    activity__monitored_by_staff_id__in=owner_ids,
                )
            )
        )

    # Staff-funds surfaces (the Fund Requests workspace) exclude partner-
    # delivered work entirely: partners are paid directly through the MOU
    # partner-payment channel (50% advance + verified clearance), never
    # through a staff advance. Budget ROLL-UPS (country/monthly views) keep
    # partner costs — they are real money the organisation pays.
    if query.get("exclude_partner"):
        base_lines = base_lines.exclude(activity__delivery_type="partner").filter(
            partner_id__isnull=True
        )

    # CCEO viewers see only the money they personally receive: vendor-direct
    # mission costs (school-visit transport, Finance-booked accommodation)
    # are hidden — they see arrangement status instead of vendor rates.
    if query.get("staff_channel_only"):
        from apps.fund_requests.fundable import vendor_direct_filter

        base_lines = base_lines.exclude(vendor_direct_filter())

    # Budgets are submitted to districts, so every horizon of this ledger can
    # be narrowed to one district. Cost lines carry the school directly; an
    # unknown district id simply yields an empty (honest) ledger. The country
    # admin plan has no district, so a district submission excludes it rather
    # than inventing an allocation.
    requested_district = str(query.get("district") or "").strip()
    if requested_district:
        base_lines = base_lines.filter(
            Q(school__district_id=requested_district)
            | Q(activity__school__district_id=requested_district)
            | Q(activity__cluster__district_id=requested_district)
            | Q(activity__event_district_id=requested_district)
        )
        include_admin = False

    if query.get("plan_only"):
        include_admin = False
    admin_lines = []
    if include_admin:
        admin_lines = list(
            AdminBudgetLine.objects.filter(
                monthly_budget__fy=fy, status="active"
            ).select_related("monthly_budget")
        )

    def admin_total(period):
        # Admin plans are monthly costs. A weekly split would be invented, so
        # show them exactly in the Month, Quarter, and FY where they are planned.
        if not include_admin or period["key"] == "week":
            return 0
        return sum(
            int(line.total_cost or 0)
            for line in admin_lines
            if (planned := _month_start_for_key(line.monthly_budget.month_key))
            and period["start"] <= planned <= period["end"]
        )

    def operational_total(period):
        return int(
            _frozen_planned_lines_for_period(
                base_lines, period["start"], period["end"]
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

    comparison = []
    for key in ("week", "month", "quarter", "fy"):
        period = periods[key]
        program_total = operational_total(period)
        admin_amount = admin_total(period)
        comparison.append(
            {
                **period,
                "program_total": program_total,
                "admin_total": admin_amount,
                "total": program_total + admin_amount,
                "selected": key == selected_period,
            }
        )

    selected_lines = list(
        _frozen_planned_lines_for_period(base_lines, selected["start"], selected["end"])
    )
    user_names = dict(
        User.objects.filter(
            id__in={
                line.responsible_user
                for line in selected_lines
                if line.responsible_user
            }
        ).values_list("id", "name")
    )
    # A supervisor needs a quick view of each person's total without having to
    # scan staff names repeated beneath every cost item.  Keep this separate
    # from the activity/item ledger so the detail table stays easy to read.
    team_summary_by_owner: dict[str, dict] = {}
    if budget_scope == "team":
        for line in selected_lines:
            owner_id = line.responsible_user or "unassigned"
            summary = team_summary_by_owner.setdefault(
                owner_id,
                {
                    "name": user_names.get(owner_id, "Unassigned work"),
                    "activity_ids": set(),
                    "total": 0,
                },
            )
            summary["activity_ids"].add(line.activity_id)
            summary["total"] += int(line.amount or 0)
    formatted_groups = _frozen_budget_groups(
        selected_lines,
        user_names,
        admin_lines=admin_lines,
        selected=selected,
        include_admin=include_admin,
        selected_period=selected_period,
    )

    weekly_requests = WeeklyFundRequest.objects.filter(
        fy=fy,
        week_start_date__lte=selected["end"],
        week_end_date__gte=selected["start"],
    )
    monthly_requests = FundRequest.objects.filter(
        fy=fy, period=FundRequestPeriod.MONTHLY
    )
    if owner_ids is not None:
        weekly_requests = weekly_requests.filter(responsible_user__in=owner_ids)
        monthly_requests = monthly_requests.filter(submitted_by_user_id__in=owner_ids)
    if budget_scope == "admin":
        weekly_requests = weekly_requests.none()
        monthly_requests = monthly_requests.none()
    if selected_period in ("week", "month"):
        monthly_requests = monthly_requests.filter(period_key=f"{fy}-M{anchor.month}")

    selected_program_total = sum(
        group["total"] for group in formatted_groups if not group["is_admin"]
    )
    selected_admin_total = sum(
        group["total"] for group in formatted_groups if group["is_admin"]
    )
    selected_staff_total = sum(group["staff_total"] for group in formatted_groups)
    selected_vendor_total = sum(group["vendor_total"] for group in formatted_groups)
    team_summary = [
        {
            "name": summary["name"],
            "activity_count": len(summary["activity_ids"]),
            "total": summary["total"],
        }
        for summary in team_summary_by_owner.values()
    ]
    team_summary.sort(key=lambda item: (-item["total"], item["name"]))
    workspace_title = {
        "admin": "Admin Budget",
        "country": "General Budget",
        "team": "Team Budget",
        "my": "My Budget",
    }[budget_scope]
    source_description = {
        "admin": "Country Director administrative plan",
        "country": "Scheduled planned activities",
        "team": "Team planned activities",
        "my": "My planned activities",
    }[budget_scope]
    empty_title = (
        "No admin budget items in this period"
        if budget_scope == "admin"
        else "No costed planned activities in this period"
    )
    empty_help = (
        "Add an administrative item for the selected month."
        if budget_scope == "admin"
        else "Choose another time view or schedule an activity to create its budget automatically."
    )
    # The budget workspaces carried a box labelled "Search planned activities…"
    # that was wired to nothing, so it fell through to the platform's global
    # search and navigated the user off their budget. The rows are already
    # materialised for the selected period, so the query filters them in place.
    #
    # Item and owner are what the table prints, so they are what a typed query
    # matches. A group that keeps no rows is dropped rather than left as an
    # empty category heading, and the totals below are deliberately untouched:
    # they describe the month's budget, not the current search, and a total
    # that moved with a filter would misreport what was actually committed.
    search_q = str(query.get("q") or "").strip().casefold()
    if search_q:
        narrowed = []
        for group in formatted_groups:
            kept = [
                row
                for row in group["rows"]
                if search_q in str(row.get("item", "")).casefold()
                or search_q in str(row.get("owners", "")).casefold()
            ]
            if kept:
                narrowed.append({**group, "rows": kept})
        formatted_groups = narrowed

    return {
        "fy": fy,
        "anchor": anchor,
        "selected_period": selected_period,
        "selected": selected,
        "comparison": comparison,
        "q": query.get("q") or "",
        "groups": formatted_groups,
        "program_total": selected_program_total,
        "admin_total": selected_admin_total,
        "staff_total": selected_staff_total,
        "vendor_total": selected_vendor_total,
        "total": selected_program_total + selected_admin_total,
        "weekly_request_count": weekly_requests.count(),
        "monthly_request_count": monthly_requests.count(),
        "role": getattr(principal, "active_role", ""),
        "scope_label": {
            "admin": "Administrative",
            "country": "Country",
            "team": "Team",
            "my": "My",
        }[budget_scope],
        "budget_scope": budget_scope,
        "workspace_title": workspace_title,
        "workspace_kind": budget_scope,
        "workspace_base_url": "/budgets/monthly",
        "source_description": source_description,
        "empty_title": empty_title,
        "empty_help": empty_help,
        "is_program_lead": is_program_lead,
        "team_summary": team_summary,
        "admin_weekly_note": include_admin and selected_period == "week",
        "admin_item_count": len(admin_lines),
    }


# ── Fixtures and assertions ──────────────────────────────────────────────────

User = get_user_model()
FY = "2026"


def _user(email, role):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    return user, StaffProfile.objects.create(user=user, title=role)


class BudgetLedgerOracleTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Oracle Region")
        cls.district_a = District.objects.create(
            name="Oracle A", region=region, district_type="primary"
        )
        cls.district_b = District.objects.create(
            name="Oracle B", region=region, district_type="primary"
        )
        school_a = School.objects.create(
            school_id="ORC-A", name="School A", region=region, district=cls.district_a
        )
        school_b = School.objects.create(
            school_id="ORC-B", name="School B", region=region, district=cls.district_b
        )
        cls.cd, _ = _user("oracle-cd@t.org", "CountryDirector")
        cls.accountant, _ = _user("oracle-acct@t.org", "Accountant")
        cls.pl, cls.pl_sp = _user("oracle-pl@t.org", "Program Lead")
        cls.cceo1, cls.cceo1_sp = _user("oracle-c1@t.org", "CCEO")
        cls.cceo2, cls.cceo2_sp = _user("oracle-c2@t.org", "CCEO")
        cls.idle, _ = _user("oracle-idle@t.org", "CCEO")
        for sp in (cls.cceo1_sp, cls.cceo2_sp):
            StaffSupervisorAssignment.objects.create(
                supervisor=cls.pl_sp, supervisee=sp
            )
        partner = Partner.objects.create(name="Oracle Partner")

        def activity(atype, day, owner_sp, **extra):
            planned = date(2026, *day)
            return Activity.objects.create(
                activity_type=atype,
                delivery_type=extra.pop("delivery_type", "staff"),
                status=extra.pop("status", "scheduled"),
                fy=extra.pop("fy", FY),
                planned_date=planned,
                scheduled_date=timezone.make_aware(
                    timezone.datetime(planned.year, planned.month, planned.day, 9)
                ),
                responsible_staff_id=owner_sp.id,
                **extra,
            )

        def line(act, key, label, unit, qty=1, *, owner=None, **extra):
            planned = extra.pop("planned_date", act.planned_date)
            return ActivityScheduleCostLine.objects.create(
                activity=act,
                cost_setting_key=key,
                label=label,
                unit_cost=unit,
                quantity=qty,
                amount=unit * qty,
                planned_date=planned,
                month=extra.pop("month", planned.month if planned else None),
                fiscal_year=extra.pop("fiscal_year", FY),
                catalogue_id="cat-1",
                catalogue_version=1,
                responsible_user=owner,
                **extra,
            )

        visit = activity("school_visit", (4, 10), cls.cceo1_sp, school=school_a)
        line(
            visit, "primary_transport_per_day", "Transport", 60_000, owner=cls.cceo1.id
        )
        line(visit, "lunch", "Lunch", 15_000, 2, owner=cls.cceo1.id, school=school_a)
        # Legacy month-only row: belongs to the whole month, never to a week.
        line(
            visit,
            "legacy_meals",
            "Lunch",
            15_000,
            owner=cls.cceo1.id,
            planned_date=None,
            month=4,
        )
        other_visit = activity("school_visit", (4, 13), cls.cceo2_sp, school=school_b)
        # Same item at a different rate: a mixed-rate row.
        line(
            other_visit,
            "primary_transport_per_day",
            "Transport",
            45_000,
            owner=cls.cceo2.id,
        )
        training = activity(
            "cluster_training",
            (4, 15),
            cls.cceo2_sp,
            teachers_attended=10,
            leaders_attended=2,
            other_participants=None,
        )
        line(
            training,
            "participant_meals",
            "Participant meals",
            8_000,
            12,
            owner=cls.cceo2.id,
        )
        line(training, "venue", "Venue", 50_000, owner=cls.cceo2.id)
        meeting = activity(
            "cluster_meeting", (4, 20), cls.cceo1_sp, expected_participants=25
        )
        # No responsible_user: owned through the activity's responsible staff.
        line(meeting, "cluster_meeting_participant_meals", "", 5_000, 25, owner=None)
        line(meeting, "stationery", "Stationery", 20_000, owner="")
        partner_training = activity(
            "in_school_training",
            (4, 22),
            cls.cceo1_sp,
            delivery_type="partner",
            status="assigned_to_partner",
            monitored_by_staff_id=cls.cceo1_sp.id,
        )
        line(
            partner_training,
            "partner_training_lump_sum",
            "Partner lump sum",
            300_000,
            owner=None,
            partner=partner,
        )
        admin_item = activity(
            "partner_activity", (4, 24), cls.cceo2_sp, programme_activity_type="admin"
        )
        line(
            admin_item, "office_supplies", "Office supplies", 70_000, owner=cls.cceo2.id
        )
        # A school-visit type reported under a programme category: labelled by
        # the category, not the (shared) activity type.
        programme_visit = activity(
            "school_visit",
            (4, 25),
            cls.cceo1_sp,
            programme_activity_type="teacher_training",
        )
        line(programme_visit, "fuel", "Fuel", 35_000, owner=cls.cceo1.id)
        # Two groups with equal totals: ordered by label.
        tie_a = activity("coaching_visit", (4, 27), cls.cceo1_sp)
        line(tie_a, "fuel", "Fuel", 40_000, owner=cls.cceo1.id)
        tie_b = activity("donor_visit", (4, 28), cls.cceo2_sp)
        line(tie_b, "fuel", "Fuel", 40_000, owner=cls.cceo2.id)
        # Excluded: a non-fundable status, a deleted activity, another FY.
        cancelled = activity("school_visit", (4, 11), cls.cceo1_sp, status="cancelled")
        line(cancelled, "lunch", "Lunch", 99_000, owner=cls.cceo1.id)
        deleted = activity("school_visit", (4, 12), cls.cceo1_sp)
        line(deleted, "lunch", "Lunch", 77_000, owner=cls.cceo1.id)
        Activity.objects.filter(id=deleted.id).update(deleted_at=timezone.now())
        old_fy = activity("school_visit", (4, 14), cls.cceo1_sp, fy="2025")
        line(old_fy, "lunch", "Lunch", 11_000, owner=cls.cceo1.id, fiscal_year="2025")
        # Other months of the year, for the quarter and FY horizons.
        may = activity("school_visit", (5, 5), cls.cceo2_sp)
        line(may, "primary_transport_per_day", "Transport", 60_000, owner=cls.cceo2.id)
        november = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=FY,
            planned_date=date(2025, 11, 3),
            scheduled_date=timezone.make_aware(timezone.datetime(2025, 11, 3, 9)),
            responsible_staff_id=cls.cceo1_sp.id,
        )
        line(november, "lunch", "Lunch", 15_000, owner=cls.cceo1.id)

        april = MonthlyWorkPlanBudget.objects.create(
            country_id="Uganda", month_key="2026-04", fy=FY
        )
        for description, status, total in (
            ("Office internet", "active", 25_000),
            ("Old item", "removed", 90_000),
        ):
            AdminBudgetLine.objects.create(
                monthly_budget=april,
                cost_category="operations",
                description=description,
                quantity=1,
                unit_cost=total,
                total_cost=total,
                created_by_user_id=cls.cd.id,
                status=status,
            )

    def assertSameAsFrozen(self, principal, **query):
        query = {"fy": FY, "date": "2026-04-10", **query}
        self.assertEqual(
            budget_workspace(principal, query),
            _frozen_budget_workspace(principal, query),
            query,
        )

    def test_country_ledger_for_every_horizon(self):
        for principal in (self.cd, self.accountant):
            for period in ("week", "month", "quarter", "fy"):
                for plan_only in (True, False):
                    with self.subTest(principal=principal.email, period=period):
                        self.assertSameAsFrozen(
                            principal,
                            period=period,
                            budget_scope="country",
                            plan_only=plan_only,
                        )

    def test_country_ledger_filters(self):
        for extra in (
            {"district": self.district_b.id},
            {"district": "no-such-district"},
            {"q": "transport"},
            {"q": "nothing matches this"},
            {"staff": self.cceo1.id},
            {"budget_scope": "admin"},
            {"exclude_partner": True},
            {"staff_channel_only": True},
            {"date": "2026-04-20", "period": "week"},
            {"date": "2025-11-03", "period": "quarter"},
        ):
            with self.subTest(**extra):
                query = {"budget_scope": "country", "period": "month", **extra}
                self.assertSameAsFrozen(self.cd, **query)

    def test_team_and_personal_ledgers(self):
        for principal, scope in (
            (self.pl, "team"),
            (self.pl, "my"),
            (self.cceo1, "my"),
            (self.cceo2, "my"),
        ):
            for period in ("week", "month", "fy"):
                with self.subTest(
                    principal=principal.email, scope=scope, period=period
                ):
                    self.assertSameAsFrozen(
                        principal, period=period, budget_scope=scope
                    )
        self.assertSameAsFrozen(
            self.pl, period="month", budget_scope="team", staff=self.cceo2.id
        )
        self.assertSameAsFrozen(
            self.pl, period="month", budget_scope="team", staff=self.cd.id
        )

    def test_empty_scope(self):
        for period in ("week", "month", "fy"):
            self.assertSameAsFrozen(self.idle, period=period, budget_scope="my")
        self.assertSameAsFrozen(
            self.cd, period="month", budget_scope="country", fy="2031"
        )

    def test_budget_groups_on_models_and_rows(self):
        april = _calendar_periods(FY, date(2026, 4, 10))["month"]
        admin_lines = list(
            AdminBudgetLine.objects.filter(monthly_budget__fy=FY).select_related(
                "monthly_budget"
            )
        )
        names = {self.cceo1.id: "Officer One", self.cceo2.id: "Officer Two"}
        models = list(
            ActivityScheduleCostLine.objects.filter(fiscal_year=FY).select_related(
                "activity"
            )
        )
        # The model path (weekly request snapshots) and the row path (the
        # ledger) must both give what the frozen code gives for the models.
        expected = _frozen_budget_groups(
            models,
            names,
            admin_lines=admin_lines,
            selected=april,
            include_admin=True,
            selected_period="month",
        )
        self.assertEqual(
            budget_groups(
                models,
                names,
                admin_lines=admin_lines,
                selected=april,
                include_admin=True,
                selected_period="month",
            ),
            expected,
        )
        from apps.budget.services import _LEDGER_ACTIVITY_FIELDS, _LEDGER_LINE_FIELDS

        rows = cost_line_rows(
            ActivityScheduleCostLine.objects.filter(fiscal_year=FY),
            _LEDGER_LINE_FIELDS,
            _LEDGER_ACTIVITY_FIELDS,
        )
        # budget_groups sorts every group and row it returns, so the order the
        # rows arrive in does not matter.
        self.assertEqual(
            budget_groups(
                rows,
                names,
                admin_lines=admin_lines,
                selected=april,
                include_admin=True,
                selected_period="month",
            ),
            expected,
        )
        self.assertEqual(budget_groups([], {}), _frozen_budget_groups([], {}))

    def test_planned_lines_for_period(self):
        lines = ActivityScheduleCostLine.objects.all()
        for start, end in (
            (date(2026, 4, 6), date(2026, 4, 12)),
            (date(2026, 3, 30), date(2026, 4, 5)),
            (date(2026, 4, 1), date(2026, 4, 30)),
            (date(2026, 4, 1), date(2026, 6, 30)),
            (date(2025, 10, 1), date(2026, 9, 30)),
            (date(2026, 4, 15), date(2026, 5, 14)),
        ):
            with self.subTest(start=start, end=end):
                self.assertEqual(
                    sorted(
                        planned_lines_for_period(lines, start, end).values_list(
                            "id", flat=True
                        )
                    ),
                    sorted(
                        _frozen_planned_lines_for_period(lines, start, end).values_list(
                            "id", flat=True
                        )
                    ),
                )
                self.assertEqual(
                    planned_lines_for_period(lines, start, end).aggregate(
                        t=Sum("amount")
                    ),
                    _frozen_planned_lines_for_period(lines, start, end).aggregate(
                        t=Sum("amount")
                    ),
                )

    def test_fixture_exercises_the_edges(self):
        """Guard the fixture itself: the cases above must stay represented."""
        page = budget_workspace(
            self.cd,
            {
                "fy": FY,
                "date": "2026-04-10",
                "period": "month",
                "budget_scope": "country",
                "plan_only": True,
            },
        )
        rows = [row for group in page["groups"] for row in group["rows"]]
        self.assertTrue(any(row["mixed_rate"] for row in rows))
        totals = [group["total"] for group in page["groups"]]
        self.assertNotEqual(len(totals), len(set(totals)), "no equal-total groups")
        self.assertTrue(any(group["table_kind"] == "admin" for group in page["groups"]))
        self.assertGreater(page["vendor_total"], 0)
        comparison = {c["key"]: c["program_total"] for c in page["comparison"]}
        self.assertLess(comparison["week"], comparison["month"])
        self.assertLess(comparison["month"], comparison["quarter"])
        self.assertLess(comparison["quarter"], comparison["fy"])
