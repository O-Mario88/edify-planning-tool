"""School loan intake, follow-up, reminders, and monthly reporting."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole
from apps.notifications.services import (
    WorkflowNotificationService,
    resolve_condition,
    role_recipients,
)

from .models import (
    LoanApplication,
    LoanApplicationFollowUp,
    LoanApplicationStatus,
    LoanStatus,
    LoanTrackingDeliveryLog,
    MfiLoan,
    OPEN_LOAN_APPLICATION_STATUSES,
    RepaymentTransaction,
    RepaymentTransactionKind,
)


APPLICATION_RECIPIENT_ROLES = (
    EdifyRole.COUNTRY_DIRECTOR.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value,
)
APPLICATION_UPDATE_ROLES = {
    EdifyRole.CCEO.value,
    EdifyRole.COUNTRY_DIRECTOR.value,
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value,
}
GLOBAL_APPLICATION_ROLES = APPLICATION_UPDATE_ROLES - {EdifyRole.CCEO.value}
TERMINAL_APPLICATION_STATUSES = {
    LoanApplicationStatus.DECLINED,
    LoanApplicationStatus.WITHDRAWN,
    LoanApplicationStatus.CONVERTED,
}
APPLICATION_TRANSITIONS = {
    LoanApplicationStatus.SUBMITTED: (
        LoanApplicationStatus.SUBMITTED,
        LoanApplicationStatus.UNDER_REVIEW,
        LoanApplicationStatus.DECLINED,
        LoanApplicationStatus.WITHDRAWN,
    ),
    LoanApplicationStatus.UNDER_REVIEW: (
        LoanApplicationStatus.UNDER_REVIEW,
        LoanApplicationStatus.REFERRED,
        LoanApplicationStatus.DECLINED,
        LoanApplicationStatus.WITHDRAWN,
    ),
    LoanApplicationStatus.REFERRED: (
        LoanApplicationStatus.REFERRED,
        LoanApplicationStatus.PROCESSING,
        LoanApplicationStatus.DECLINED,
        LoanApplicationStatus.WITHDRAWN,
    ),
    LoanApplicationStatus.PROCESSING: (
        LoanApplicationStatus.PROCESSING,
        LoanApplicationStatus.APPROVED,
        LoanApplicationStatus.DECLINED,
        LoanApplicationStatus.WITHDRAWN,
    ),
    LoanApplicationStatus.APPROVED: (
        LoanApplicationStatus.APPROVED,
        LoanApplicationStatus.CONVERTED,
        LoanApplicationStatus.WITHDRAWN,
    ),
    LoanApplicationStatus.DECLINED: (LoanApplicationStatus.DECLINED,),
    LoanApplicationStatus.WITHDRAWN: (LoanApplicationStatus.WITHDRAWN,),
    LoanApplicationStatus.CONVERTED: (LoanApplicationStatus.CONVERTED,),
}


def _actor_id(principal) -> str:
    return str(
        getattr(principal, "user_id", None)
        or getattr(principal, "id", None)
        or "system"
    )


def _portfolio_owner(school):
    if not school.account_owner_id:
        return None
    profile = (
        StaffProfile.objects.select_related("user")
        .filter(
            id=school.account_owner_id,
            deleted_at__isnull=True,
            user__is_active=True,
            user__deleted_at__isnull=True,
        )
        .first()
    )
    if profile:
        return profile.user
    # A small amount of legacy school data stores the User id directly rather
    # than the StaffProfile id. Keep those schools on the notification chain.
    from apps.accounts.models import User

    return User.objects.filter(
        id=school.account_owner_id,
        roles__contains=[EdifyRole.CCEO.value],
        is_active=True,
        deleted_at__isnull=True,
    ).first()


def application_recipients(school, *, include_ia: bool = True):
    recipients = []
    owner = _portfolio_owner(school)
    if owner:
        recipients.append(owner)
    country = (
        school.region.country
        if getattr(school, "region_id", None) and school.region
        else "Uganda"
    )
    for role in APPLICATION_RECIPIENT_ROLES:
        if not include_ia and role == EdifyRole.IMPACT_ASSESSMENT.value:
            continue
        recipients.extend(role_recipients(role, country=country))
    return list({str(user.id): user for user in recipients}.values())


def scoped_applications(principal):
    queryset = LoanApplication.objects.select_related(
        "school", "school__district", "school__region", "purpose", "preferred_mfi"
    ).prefetch_related("follow_ups")
    role = getattr(principal, "active_role", "")
    if (
        role in GLOBAL_APPLICATION_ROLES
        or role == EdifyRole.REGIONAL_VICE_PRESIDENT.value
        or role == EdifyRole.CCEO.value
    ):
        from apps.core.scoping import resolve_user_scope, scoped_school_queryset

        schools = scoped_school_queryset(resolve_user_scope(principal))
        if schools is not None:
            return queryset.filter(school_id__in=schools.values("id"))
    return queryset.none()


@transaction.atomic
def submit_application(form) -> LoanApplication:
    """Persist a validated public form and notify the responsible team."""

    application = form.save(commit=False)
    application.school = form.cleaned_data["school"]
    application.status = LoanApplicationStatus.SUBMITTED
    application.submitted_at = timezone.now()
    application.consent_recorded_at = timezone.now()
    application.next_follow_up_on = timezone.localdate() + timedelta(days=3)
    try:
        # Keep the database uniqueness constraint as the final arbiter. The
        # form's pre-check is useful feedback but two simultaneous requests can
        # both pass it before either inserts.
        with transaction.atomic():
            application.save()
    except IntegrityError as exc:
        raise BadRequest(
            "This school already has an open loan application. Contact your Edify portfolio owner for an update."
        ) from exc
    LoanApplicationFollowUp.objects.create(
        application=application,
        new_status=LoanApplicationStatus.SUBMITTED,
        note="Application submitted directly by the school.",
        next_follow_up_on=application.next_follow_up_on,
        recorded_by="school",
    )

    recipients = application_recipients(application.school)
    if recipients:
        WorkflowNotificationService.trigger(
            event_type="bt.loan_application.submitted",
            category="business_transformation",
            priority="high",
            title=f"New loan application · {application.school.name}",
            body=(
                f"{application.applicant_name} requested {application.currency} "
                f"{application.requested_amount:,.0f} for {application.purpose.label}. "
                "Review and record the next follow-up."
            ),
            context_type="loan_application",
            context_id=str(application.id),
            recipients=recipients,
        )
    return application


@transaction.atomic
def update_application(application_id: str, data: dict, principal) -> LoanApplication:
    role = getattr(principal, "active_role", "")
    if role not in APPLICATION_UPDATE_ROLES:
        raise Forbidden("Your active role cannot update loan applications.")
    visible_id = (
        scoped_applications(principal)
        .filter(id=application_id)
        .values_list("id", flat=True)
        .first()
    )
    application = (
        LoanApplication.objects.select_for_update()
        .select_related("school", "purpose")
        .filter(id=visible_id)
        .first()
        if visible_id
        else None
    )
    if application is None:
        raise NotFoundError("Loan application not found in your scope.")

    new_status = (data.get("status") or "").strip()
    if new_status not in LoanApplicationStatus.values:
        raise BadRequest("Choose a valid application status.")
    if new_status not in APPLICATION_TRANSITIONS.get(application.status, ()):
        raise BadRequest(
            f"A {application.get_status_display().lower()} application cannot move directly to "
            f"{dict(LoanApplicationStatus.choices)[new_status].lower()}."
        )
    note = (data.get("note") or "").strip()
    if not note:
        raise BadRequest("Add a follow-up note so the next person has context.")

    next_follow_up_on = None
    raw_next = (data.get("nextFollowUpOn") or "").strip()
    if new_status not in TERMINAL_APPLICATION_STATUSES:
        if not raw_next:
            raise BadRequest("Set the next follow-up date for an open application.")
        try:
            next_follow_up_on = date.fromisoformat(raw_next)
        except ValueError as exc:
            raise BadRequest("Next follow-up date must be valid.") from exc

    linked_loan = application.linked_loan
    linked_loan_id = (data.get("linkedLoanId") or "").strip()
    if new_status == LoanApplicationStatus.CONVERTED:
        if not linked_loan_id:
            raise BadRequest("Select the processed loan before marking this converted.")
        linked_loan = MfiLoan.objects.filter(
            id=linked_loan_id,
            school=application.school,
            purpose=application.purpose,
            deleted_at__isnull=True,
        ).first()
        if linked_loan is None:
            raise BadRequest(
                "The linked loan must belong to the same school and loan purpose."
            )
        if (
            application.preferred_mfi_id
            and linked_loan.mfi_id != application.preferred_mfi_id
        ):
            raise BadRequest("The linked loan must use the selected lending partner.")
        if linked_loan.status == LoanStatus.CANCELED:
            raise BadRequest("A cancelled loan cannot be linked to an application.")
    else:
        linked_loan = None

    previous_status = application.status
    application.status = new_status
    application.next_follow_up_on = next_follow_up_on
    application.reviewed_by = _actor_id(principal)
    application.reviewed_at = timezone.now()
    application.linked_loan = linked_loan
    if new_status in TERMINAL_APPLICATION_STATUSES:
        application.processed_at = timezone.now()
    else:
        application.processed_at = None
    application.save(
        update_fields=[
            "status",
            "next_follow_up_on",
            "reviewed_by",
            "reviewed_at",
            "linked_loan",
            "processed_at",
            "updated_at",
        ]
    )
    LoanApplicationFollowUp.objects.create(
        application=application,
        previous_status=previous_status,
        new_status=new_status,
        note=note,
        next_follow_up_on=next_follow_up_on,
        recorded_by=_actor_id(principal),
    )

    if new_status in TERMINAL_APPLICATION_STATUSES:
        resolve_condition(
            ["bt.loan_application.submitted", "bt.loan_application.follow_up"],
            "loan_application",
            str(application.id),
        )
    return application


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _derived_due_date(loan: MfiLoan, today: date) -> date | None:
    latest_snapshot = loan.repayment_snapshots.order_by(
        "-as_of_date", "-created_at"
    ).first()
    if latest_snapshot and latest_snapshot.next_payment_date:
        return latest_snapshot.next_payment_date

    latest_version = loan.repayment_installments.aggregate(
        version=Max("schedule_version")
    )["version"]
    if latest_version:
        from .lending_ledger import loan_position

        position = loan_position(loan, as_of=today)
        if position["amountOverdue"] > 0:
            return (
                loan.repayment_installments.filter(
                    schedule_version=latest_version, due_date__lte=today
                )
                .order_by("due_date")
                .values_list("due_date", flat=True)
                .first()
            )
        return (
            loan.repayment_installments.filter(
                schedule_version=latest_version, due_date__gte=today
            )
            .order_by("due_date")
            .values_list("due_date", flat=True)
            .first()
        )

    if not loan.disbursement_date:
        return None
    frequency = (loan.repayment_frequency or "").lower()
    if "term" in frequency or "quarter" in frequency:
        step = 3
    elif "month" in frequency:
        step = 1
    else:
        return None
    due = _add_months(loan.disbursement_date, step)
    maturity = loan.maturity_date or _add_months(
        loan.disbursement_date, loan.term_months or step
    )
    while due < today and due < maturity:
        due = _add_months(due, step)
    return min(due, maturity)


def _claim_delivery(kind: str, subject_id: str, period_key: str, recipient) -> bool:
    _, created = LoanTrackingDeliveryLog.objects.get_or_create(
        delivery_kind=kind,
        subject_id=subject_id,
        period_key=period_key,
        recipient_id=str(recipient.id),
    )
    return created


@transaction.atomic
def send_application_follow_up_reminders(today: date | None = None) -> int:
    today = today or timezone.localdate()
    sent = 0
    due = LoanApplication.objects.filter(
        deleted_at__isnull=True,
        status__in=OPEN_LOAN_APPLICATION_STATUSES,
        next_follow_up_on__lte=today,
    ).select_related("school", "purpose")
    for application in due:
        days_overdue = (today - application.next_follow_up_on).days
        period_key = f"{application.next_follow_up_on.isoformat()}:w{days_overdue // 7}"
        for recipient in application_recipients(application.school):
            if not _claim_delivery(
                "application_follow_up", str(application.id), period_key, recipient
            ):
                continue
            WorkflowNotificationService.trigger(
                event_type="bt.loan_application.follow_up",
                category="business_transformation",
                priority="high",
                title=f"Loan application follow-up · {application.school.name}",
                body=(
                    f"The {application.get_status_display().lower()} application is due "
                    f"for follow-up ({days_overdue} day(s) overdue)."
                ),
                context_type="loan_application",
                context_id=str(application.id),
                recipients=[recipient],
            )
            sent += 1
    return sent


@transaction.atomic
def send_repayment_follow_up_reminders(today: date | None = None) -> int:
    today = today or timezone.localdate()
    sent = 0
    loans = MfiLoan.objects.filter(
        deleted_at__isnull=True,
        status__in=[LoanStatus.DISBURSED, LoanStatus.ACTIVE, LoanStatus.DEFAULTED],
    ).select_related("school", "mfi")
    for loan in loans:
        due_date = _derived_due_date(loan, today)
        if due_date is None or due_date > today + timedelta(days=7):
            continue
        days_until = (due_date - today).days
        stage = (
            f"upcoming:{due_date.isoformat()}"
            if days_until >= 0
            else f"overdue:{due_date.isoformat()}:w{abs(days_until) // 7}"
        )
        for recipient in application_recipients(loan.school):
            if not _claim_delivery(
                "repayment_follow_up", str(loan.id), stage, recipient
            ):
                continue
            timing = (
                f"due in {days_until} day(s)"
                if days_until > 0
                else "due today"
                if days_until == 0
                else f"{abs(days_until)} day(s) overdue"
            )
            WorkflowNotificationService.trigger(
                event_type="bt.loan_repayment.follow_up",
                category="business_transformation",
                priority="high",
                title=f"Loan repayment follow-up · {loan.school.name}",
                body=(
                    f"The {loan.get_repayment_frequency_display() if hasattr(loan, 'get_repayment_frequency_display') else loan.repayment_frequency or 'scheduled'} "
                    f"payment to {loan.mfi.name} is {timing}. Contact the school and record the repayment position."
                ),
                context_type="loan",
                context_id=str(loan.id),
                recipients=[recipient],
            )
            sent += 1
    return sent


def previous_calendar_month(today: date | None = None) -> tuple[date, date]:
    today = today or timezone.localdate()
    end = today.replace(day=1)
    start = (end - timedelta(days=1)).replace(day=1)
    return start, end


def monthly_report_summary(start: date, end: date, principal) -> dict:
    from .services import scoped_loans

    applications = scoped_applications(principal).filter(
        submitted_at__date__gte=start, submitted_at__date__lt=end
    )
    loans = scoped_loans(principal).filter(
        disbursement_date__gte=start,
        disbursement_date__lt=end,
    )
    repayment_totals = RepaymentTransaction.objects.filter(
        loan__in=scoped_loans(principal),
        value_date__gte=start,
        value_date__lt=end,
    ).aggregate(
        payments=Sum("amount", filter=Q(kind=RepaymentTransactionKind.PAYMENT)),
        reversals=Sum("amount", filter=Q(kind=RepaymentTransactionKind.REVERSAL)),
    )
    return {
        "applications": applications.count(),
        "disbursed_loans": loans.count(),
        "disbursed_value": loans.aggregate(total=Sum("disbursed_amount"))["total"]
        or Decimal("0"),
        "repayments": (repayment_totals["payments"] or Decimal("0"))
        - (repayment_totals["reversals"] or Decimal("0")),
    }


@transaction.atomic
def send_monthly_rvp_report(today: date | None = None) -> int:
    start, end = previous_calendar_month(today)
    period_key = start.strftime("%Y-%m")
    sent = 0
    for recipient in role_recipients(EdifyRole.REGIONAL_VICE_PRESIDENT.value):
        if not _claim_delivery("monthly_rvp_report", period_key, period_key, recipient):
            continue
        summary = monthly_report_summary(start, end, recipient)
        WorkflowNotificationService.trigger(
            event_type="bt.loan_report.monthly",
            category="business_transformation",
            priority="normal",
            title=f"Monthly loan report ready · {start.strftime('%B %Y')}",
            body=(
                f"{summary['applications']} application(s), {summary['disbursed_loans']} "
                f"loan(s) disbursed worth UGX {summary['disbursed_value']:,.0f}, and "
                f"UGX {summary['repayments']:,.0f} in repayments. Export CSV or Excel from the loan dashboard."
            ),
            context_type="loan_report_month",
            context_id=period_key,
            recipients=[recipient],
        )
        sent += 1
    return sent


def run_loan_tracking_notifications(today: date | None = None) -> int:
    return (
        send_application_follow_up_reminders(today)
        + send_repayment_follow_up_reminders(today)
        + send_monthly_rvp_report(today)
    )
