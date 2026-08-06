"""RecurringIssueDetectionService — finds patterns across debriefs (§15).

Runs as a periodic scan (management command `detect_field_debrief_insights`,
mirroring the PD app's cron-less `send_pd_reminders` — nothing in-app
schedules it, an external cron must call it). Idempotent: re-scanning the
same window updates the existing open insight for a (scope, scope_id,
challenge_type) key instead of duplicating it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from apps.core.exceptions import Forbidden, NotFoundError
from apps.debriefs.models import (
    DailyDebriefChallenge,
    DailyDebriefInsight,
    InsightEscalationLevel,
    InsightScope,
)

WINDOW_DAYS = 30
MIN_OCCURRENCES = 3
TEAM_ESCALATION_THRESHOLD = 3  # same challenge across 3+ PL teams -> CD
COUNTRY_ESCALATION_THRESHOLD = 3  # same challenge across 3+ countries -> RVP

# Manager roles that review detected insights — the same leadership set the
# Field Debrief detail page's `can_manage` flag uses.
INSIGHT_REVIEWER_ROLES = (
    "Program Lead",
    "CountryDirector",
    "HumanResources",
    "ImpactAssessment",
    "RegionalVicePresident",
    "Admin",
)


class InsightReviewService:
    """Acknowledge/dismiss lifecycle for detected insights (§15). An
    acknowledged or dismissed insight automatically leaves every open-insight
    surface (dashboard highlights, weekly rollup recurring-issue counts)."""

    @staticmethod
    def acknowledge(principal, insight_id: str) -> DailyDebriefInsight:
        return InsightReviewService._set_status(principal, insight_id, "acknowledged")

    @staticmethod
    def dismiss(principal, insight_id: str) -> DailyDebriefInsight:
        return InsightReviewService._set_status(principal, insight_id, "dismissed")

    @staticmethod
    def _set_status(principal, insight_id: str, status: str) -> DailyDebriefInsight:
        role = getattr(principal, "active_role", "")
        if role not in INSIGHT_REVIEWER_ROLES:
            raise Forbidden("Only a manager may review a recurring-issue insight.")
        insight = DailyDebriefInsight.objects.filter(id=insight_id).first()
        if not insight:
            raise NotFoundError("Insight not found.")
        insight.status = status
        insight.save(update_fields=["status"])
        return insight


class RecurringIssueDetectionService:
    @staticmethod
    def scan(today: date | None = None) -> dict:
        today = today or date.today()
        window_start = today - timedelta(days=WINDOW_DAYS)
        created, updated = 0, 0

        by_school = defaultdict(list)
        by_staff = defaultdict(list)
        by_partner = defaultdict(list)
        challenges = DailyDebriefChallenge.objects.filter(
            debrief__date__date__gte=window_start,
            debrief__date__date__lte=today,
            debrief__deleted_at__isnull=True,
            debrief__is_restricted_incident=False,
        ).select_related("debrief")
        for c in challenges:
            d = c.debrief
            for school_id in d.linked_school_ids:
                by_school[(school_id, c.challenge_type)].append(d)
            if d.staff_id:
                by_staff[(d.staff_id, c.challenge_type)].append(d)
            if d.partner_id:
                by_partner[(d.partner_id, c.challenge_type)].append(d)

        for (scope_id, challenge_type), debriefs in {**by_school}.items():
            if len(debriefs) < MIN_OCCURRENCES:
                continue
            c, u = RecurringIssueDetectionService._upsert(
                InsightScope.SCHOOL,
                scope_id,
                challenge_type,
                debriefs,
                window_start,
                today,
            )
            created += c
            updated += u

        for (scope_id, challenge_type), debriefs in by_staff.items():
            if len(debriefs) < MIN_OCCURRENCES:
                continue
            c, u = RecurringIssueDetectionService._upsert(
                InsightScope.STAFF,
                scope_id,
                challenge_type,
                debriefs,
                window_start,
                today,
            )
            created += c
            updated += u

        for (scope_id, challenge_type), debriefs in by_partner.items():
            if len(debriefs) < MIN_OCCURRENCES:
                continue
            c, u = RecurringIssueDetectionService._upsert(
                InsightScope.PARTNER,
                scope_id,
                challenge_type,
                debriefs,
                window_start,
                today,
            )
            created += c
            updated += u

        RecurringIssueDetectionService._scan_team_and_country_escalations(
            window_start, today
        )
        return {
            "created": created,
            "updated": updated,
            "window_start": window_start,
            "window_end": today,
        }

    @staticmethod
    def _upsert(
        scope, scope_id, challenge_type, debriefs, window_start, window_end
    ) -> tuple[int, int]:
        debrief_ids = [d.id for d in debriefs]
        existing = DailyDebriefInsight.objects.filter(
            scope=scope,
            scope_id=scope_id,
            challenge_type=challenge_type,
            status="open",
        ).first()
        label = DailyDebriefChallenge(
            challenge_type=challenge_type
        ).get_challenge_type_display()
        title = f"Recurring issue: {label} ({scope})"
        description = f'"{label}" reported in {len(debrief_ids)} debriefs over the last {WINDOW_DAYS} days.'
        if existing:
            existing.occurrence_count = len(debrief_ids)
            existing.debrief_ids = debrief_ids
            existing.window_start, existing.window_end = window_start, window_end
            existing.description = description
            existing.save(
                update_fields=[
                    "occurrence_count",
                    "debrief_ids",
                    "window_start",
                    "window_end",
                    "description",
                ]
            )
            return 0, 1
        DailyDebriefInsight.objects.create(
            scope=scope,
            scope_id=scope_id,
            challenge_type=challenge_type,
            title=title,
            description=description,
            occurrence_count=len(debrief_ids),
            window_start=window_start,
            window_end=window_end,
            debrief_ids=debrief_ids,
            escalation_level=InsightEscalationLevel.TEAM,
        )
        RecurringIssueDetectionService._notify_pl(debriefs[0])
        return 1, 0

    @staticmethod
    def _scan_team_and_country_escalations(window_start, window_end) -> None:
        """Same challenge across 3+ PL teams -> notify CD. Across 3+
        countries -> add to RVP Regional Field Intelligence."""
        from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

        by_challenge_team = defaultdict(set)
        by_challenge_country = defaultdict(set)
        challenges = DailyDebriefChallenge.objects.filter(
            debrief__date__date__gte=window_start,
            debrief__date__date__lte=window_end,
            debrief__deleted_at__isnull=True,
            debrief__is_restricted_incident=False,
            debrief__staff_id__isnull=False,
        ).select_related("debrief")
        supervisor_by_staff = dict(
            StaffSupervisorAssignment.objects.values_list(
                "supervisee_id", "supervisor_id"
            )
        )
        country_by_staff = dict(StaffProfile.objects.values_list("id", "country"))
        for c in challenges:
            staff_id = c.debrief.staff_id
            team = supervisor_by_staff.get(staff_id)
            if team:
                by_challenge_team[c.challenge_type].add(team)
            country = country_by_staff.get(staff_id)
            if country:
                by_challenge_country[c.challenge_type].add(country)

        for challenge_type, teams in by_challenge_team.items():
            if len(teams) < TEAM_ESCALATION_THRESHOLD:
                continue
            insight = DailyDebriefInsight.objects.filter(
                scope=InsightScope.COUNTRY,
                challenge_type=challenge_type,
                status="open",
            ).first()
            if insight and insight.escalation_level == InsightEscalationLevel.COUNTRY:
                continue
            label = DailyDebriefChallenge(
                challenge_type=challenge_type
            ).get_challenge_type_display()
            if not insight:
                insight = DailyDebriefInsight.objects.create(
                    scope=InsightScope.COUNTRY,
                    challenge_type=challenge_type,
                    title=f"Cross-team recurring issue: {label}",
                    description=f'"{label}" reported across {len(teams)} Program Lead teams.',
                    occurrence_count=len(teams),
                    window_start=window_start,
                    window_end=window_end,
                    escalation_level=InsightEscalationLevel.COUNTRY,
                )
            else:
                insight.escalation_level = InsightEscalationLevel.COUNTRY
                insight.occurrence_count = len(teams)
                insight.save(update_fields=["escalation_level", "occurrence_count"])
            RecurringIssueDetectionService._notify_role(insight, "CountryDirector")

        for challenge_type, countries in by_challenge_country.items():
            if len(countries) < COUNTRY_ESCALATION_THRESHOLD:
                continue
            label = DailyDebriefChallenge(
                challenge_type=challenge_type
            ).get_challenge_type_display()
            insight = DailyDebriefInsight.objects.filter(
                scope=InsightScope.REGION,
                challenge_type=challenge_type,
                status="open",
            ).first()
            if not insight:
                insight = DailyDebriefInsight.objects.create(
                    scope=InsightScope.REGION,
                    challenge_type=challenge_type,
                    title=f"Regional recurring issue: {label}",
                    description=f'"{label}" reported across {len(countries)} countries.',
                    occurrence_count=len(countries),
                    window_start=window_start,
                    window_end=window_end,
                    escalation_level=InsightEscalationLevel.REGION,
                )
            else:
                insight.occurrence_count = len(countries)
                insight.save(update_fields=["occurrence_count"])
            RecurringIssueDetectionService._notify_role(
                insight, "RegionalVicePresident"
            )

    @staticmethod
    def _notify_pl(sample_debrief) -> None:
        from apps.debriefs.field_debrief_service import supervising_pl
        from apps.notifications.services import WorkflowNotificationService

        if not sample_debrief.staff_id:
            return
        from apps.accounts.models import StaffProfile

        sp = StaffProfile.objects.filter(id=sample_debrief.staff_id).first()
        pl = supervising_pl(sp) if sp else None
        if not pl or not pl.user_id:
            return
        WorkflowNotificationService.trigger(
            event_type="field_debrief_recurring_issue",
            category="field_debrief",
            priority="normal",
            title="A recurring field issue was detected on your team",
            body="Check Recurring Field Issues for details.",
            context_type="field_debrief",
            context_id=sample_debrief.id,
            recipients=[pl.user_id],
        )

    @staticmethod
    def _notify_role(insight: DailyDebriefInsight, role: str) -> None:
        from apps.debriefs.field_debrief_service import _users_with_role
        from apps.notifications.services import WorkflowNotificationService

        user_ids = _users_with_role(role)
        if not user_ids:
            return
        insight.notified_user_ids = list(set(insight.notified_user_ids) | set(user_ids))
        insight.save(update_fields=["notified_user_ids"])
        WorkflowNotificationService.trigger(
            event_type="field_debrief_recurring_issue_escalated",
            category="field_debrief",
            priority="high",
            title=insight.title,
            body=insight.description,
            context_type="field_debrief_insight",
            context_id=insight.id,
            recipients=user_ids,
        )
