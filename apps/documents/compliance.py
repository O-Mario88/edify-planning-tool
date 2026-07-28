"""Policy and manual compliance reporting for the People dashboards.

Who has answered, who has not, and who is overdue — inside the asking role's
own scope. Four roles read this and each sees a different slice:

    HR   — every employee and partner in their remit
    CD   — their country
    RVP  — a regional summary, and drill-down where permitted
    PL   — supervised staff and managed partners, status only

The last one is the important distinction. A Program Lead can see *whether*
their team answered, because chasing that is their job. They cannot read what
anyone wrote beside their answer: a private comment routed to HR stops being
private the moment a line manager can read it.

Engagement figures travel with each row, under their own names — Active Reading
Time, Viewer Completion. Never "proof of reading": the platform can observe that
a document was open and visible, and nothing at all about whether it was
understood.
"""

from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import Forbidden
from apps.documents.models import (
    AcknowledgementState,
    DocumentAcknowledgement,
    DocumentAsset,
    READABLE_STATUSES,
)

VIEWS = ("policy", "user", "role", "team", "country", "status", "due_date")


def _scope_user_ids(principal) -> set[str] | None:
    """The users this role may report on. ``None`` means no restriction.

    A Program Lead's scope is their supervisees; anything wider would let a
    line manager audit the whole country from a page built for their team.
    """
    role = getattr(principal, "active_role", "")
    if role in ("HumanResources", "Admin", "RegionalVicePresident"):
        return None
    if role == "CountryDirector":
        from apps.accounts.models import StaffProfile

        from apps.documents.services import country_of

        country = country_of(principal)
        if not country:
            return None
        return set(
            StaffProfile.objects.filter(country=country)
            .exclude(user_id=None)
            .values_list("user_id", flat=True)
        )
    if role in ("Program Lead", "ProgramLead"):
        from apps.accounts.models import StaffSupervisorAssignment

        profile = getattr(principal, "staff_profile", None)
        if profile is None:
            return set()
        ids = set()
        for assignment in StaffSupervisorAssignment.objects.filter(
            supervisor_id=profile.id
        ).select_related("supervisee"):
            if assignment.supervisee and assignment.supervisee.user_id:
                ids.add(assignment.supervisee.user_id)
        return ids
    raise Forbidden("You do not have policy compliance visibility.")


class PolicyComplianceService:
    @staticmethod
    def report(principal, query: dict | None = None) -> dict:
        query = query or {}
        scope_ids = _scope_user_ids(principal)

        qs = DocumentAcknowledgement.objects.select_related(
            "document", "version"
        ).filter(document__status__in=READABLE_STATUSES)
        if scope_ids is not None:
            qs = qs.filter(user_id__in=scope_ids)
        if query.get("document"):
            qs = qs.filter(document_id=query["document"])
        if query.get("state"):
            qs = qs.filter(state=query["state"])
        if query.get("role"):
            qs = qs.filter(role_at_acknowledgement=query["role"])

        records = list(qs[:1000])
        names = _names({r.user_id for r in records})
        today = timezone.localdate()

        rows = []
        for ack in records:
            overdue = bool(
                ack.due_date
                and ack.due_date < today
                and ack.state == AcknowledgementState.PENDING
            )
            rows.append(
                {
                    "user": names.get(ack.user_id, ack.user_id),
                    "user_id": ack.user_id,
                    "role": ack.role_at_acknowledgement or "—",
                    "policy": ack.document.title,
                    "document_id": ack.document_id,
                    "version": f"v{ack.version.version_number}",
                    "state": ack.get_state_display(),
                    "state_key": ack.state,
                    # Named for what it is. The platform can see that a viewer
                    # was open and visible; it cannot see comprehension.
                    "active_reading_time": _humanise(ack.active_reading_seconds),
                    "viewer_completion": (
                        "Completed"
                        if ack.viewer_completed
                        else (
                            "Attested outside the viewer"
                            if ack.offline_attestation
                            else "Partial"
                        )
                    ),
                    "first_opened": ack.created_at,
                    "comment_status": _comment_status(ack),
                    "due_date": ack.due_date,
                    "overdue": overdue,
                    "next_action": _next_action(ack, overdue),
                }
            )

        return {
            "rows": rows,
            "kpis": PolicyComplianceService.kpis(principal, records, today),
            "counts": PolicyComplianceService.counts(records, today),
            "views": VIEWS,
            "filters": query,
            "policies": list(
                DocumentAsset.objects.filter(
                    acknowledgement_required=True, status__in=READABLE_STATUSES
                ).values("id", "title")
            ),
            "scope_note": _scope_note(principal),
        }

    @staticmethod
    def kpis(principal, records, today=None) -> list[dict]:
        """The compliance strip, built through the metric registry.

        Accepted and Overdue carry registered identities; the remaining
        counts are context for them and stay as plain figures the template
        renders beside the strip rather than as unregistered tiles pretending
        to the same authority.
        """
        from apps.core.metrics import MetricValue, render_metric, render_strip

        today = today or timezone.localdate()
        accepted = sum(1 for r in records if r.state == AcknowledgementState.AGREED)
        overdue = sum(
            1
            for r in records
            if r.state == AcknowledgementState.PENDING
            and r.due_date
            and r.due_date < today
        )
        return render_strip(
            [
                render_metric(
                    "policy_acknowledgements_accepted",
                    MetricValue.measured(accepted, denominator=len(records) or None),
                    drilldown_url="/policy-compliance?state=agreed",
                ),
                render_metric(
                    "policy_acknowledgements_overdue",
                    MetricValue.measured(overdue),
                    drilldown_url="/policy-compliance?state=pending",
                ),
            ]
        )

    @staticmethod
    def counts(records, today=None) -> dict:
        """Plain supporting figures shown beside the strip."""
        today = today or timezone.localdate()
        return {
            "required": len(records),
            "pending": sum(
                1 for r in records if r.state == AcknowledgementState.PENDING
            ),
            "declined": sum(
                1 for r in records if r.state == AcknowledgementState.DISAGREED
            ),
        }


def _names(user_ids: set[str]) -> dict[str, str]:
    from apps.accounts.models import User

    return {
        u.id: u.name for u in User.objects.filter(id__in=user_ids).only("id", "name")
    }


def _comment_status(ack) -> str:
    comment = ack.comment_records.first()
    if comment is None:
        return "—" if not ack.comment else "Recorded"
    return comment.get_status_display()


def _next_action(ack, overdue: bool) -> str:
    if ack.state == AcknowledgementState.DISAGREED:
        return "HR review"
    if ack.state == AcknowledgementState.PENDING:
        return "Send reminder" if overdue else "Awaiting the user"
    return "—"


def _humanise(seconds: int) -> str:
    if not seconds:
        return "—"
    minutes, remainder = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s" if minutes else f"{remainder}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _scope_note(principal) -> str:
    role = getattr(principal, "active_role", "")
    return {
        "HumanResources": "Every employee and partner in your remit.",
        "CountryDirector": "Staff and partners in your country.",
        "RegionalVicePresident": "Regional summary across your deployment.",
        "Program Lead": (
            "Your supervised staff and managed partners. Acknowledgement status "
            "only — the private comment a person writes with their answer goes "
            "to HR."
        ),
    }.get(role, "Your authorised scope.")
