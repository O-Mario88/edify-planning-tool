#!/usr/bin/env python3
"""Give a scaled, disposable database the rest of a production-shaped estate.

`scale_local_dataset.py` grows schools, clusters, SSA and activities. On its
own that leaves every other surface measuring an empty or toy-sized table:
no cost lines or advances behind 74,000 activities (so finance pages read
nothing), no evidence, a handful of notifications, no loans, no
Business Transformation cases and no leave — and every school split among the
twenty demo CCEOs, about 2,500 each, several times any real portfolio.

Two phases, around the school scaler:

    createdb -T edify_seed_pristine edify_scale_real
    DATABASE_URL=…/edify_scale_real scripts/scale_local_domains.py people
    scripts/scale_local_dataset.py --database edify_scale_real --schools 49300
    DATABASE_URL=…/edify_scale_real scripts/scale_local_domains.py domains
    DATABASE_URL=…/edify_scale_real scripts/scale_local_domains.py salesforce

``people`` adds field officers and Programme Leads (default 130 and 12) so the
schools spread over ~150 portfolios of ~330 schools and ~9 officers per lead.
``domains`` adds, from template rows cloned in bulk SQL: two cost lines per
costed activity and an advance behind each in the state its activity implies;
evidence for every activity whose evidence was submitted; notifications for
every account; Business Transformation cases, MFI loans with repayment
schedules and payments, and loan applications; and leave for every member of
staff. ``salesforce`` reserves the Salesforce ID every submitted staff
activity carries in production, through the canonical service. It is
synthetic data shaped like production, not a copy of it.

Refuses to run unless the database name contains "scale" or "loadtest".
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.loadtest")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth.hashers import make_password  # noqa: E402
from django.db import connection, transaction  # noqa: E402

from scale_local_dataset import clone_sql  # noqa: E402

TEMPLATE_PREFIX = "scale-template"


def _guard() -> None:
    name = settings.DATABASES["default"]["NAME"]
    if "scale" not in name and "loadtest" not in name:
        sys.exit(f"refusing: database {name!r} must contain 'scale' or 'loadtest'")


def _run(cur, sql, params=None, label=""):
    started = time.monotonic()
    # No parameters means no placeholder parsing: the SQL uses % as modulo.
    if params is None:
        cur.execute(sql)
    else:
        cur.execute(sql, params)
    print(f"  {label}: {cur.rowcount:,} rows ({time.monotonic() - started:.1f}s)")


def people(officers: int, leads: int) -> None:
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
    from apps.core.rbac import EdifyRole

    cceo, lead = EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value
    unusable = make_password(None)
    new_users = [
        User(
            email=f"scale-lead{i:03d}@edify.org",
            name=f"Programme Lead {i:03d}",
            roles=[lead],
            active_role=lead,
            status="active",
            is_active=True,
            password=unusable,
        )
        for i in range(leads)
    ] + [
        User(
            email=f"scale-officer{i:03d}@edify.org",
            name=f"Field Officer {i:03d}",
            roles=[cceo],
            active_role=cceo,
            status="active",
            is_active=True,
            password=unusable,
        )
        for i in range(officers)
    ]
    with transaction.atomic():
        User.objects.bulk_create(new_users, batch_size=500)
        StaffProfile.objects.bulk_create(
            [
                StaffProfile(user=u, onboarding_state="active")
                for u in User.objects.filter(email__startswith="scale-")
            ],
            batch_size=500,
        )
        leads_all = list(
            StaffProfile.objects.filter(
                user__active_role=lead, deleted_at__isnull=True
            ).order_by("user__email")
        )
        officers_all = list(
            StaffProfile.objects.filter(
                user__active_role=cceo, deleted_at__isnull=True
            ).order_by("user__email")
        )
        StaffSupervisorAssignment.objects.filter(supervisee__in=officers_all).delete()
        StaffSupervisorAssignment.objects.bulk_create(
            [
                StaffSupervisorAssignment(
                    supervisee=officer, supervisor=leads_all[i % len(leads_all)]
                )
                for i, officer in enumerate(officers_all)
            ],
            batch_size=500,
        )
    print(f"people: {len(leads_all)} Programme Leads, {len(officers_all)} CCEOs")


def _template(model, **fields):
    """One ORM-made row whose NOT NULL columns and defaults are all correct."""
    return model.objects.create(**fields)


def domains() -> None:
    from apps.activities.models import Activity
    from apps.accounts.models import Leave, StaffProfile, User
    from apps.business_transformation.models import (
        LoanApplication,
        LoanPurpose,
        LoanRepaymentInstallment,
        MfiLoan,
        MfiOrganization,
        RepaymentTransaction,
        TransformationCase,
    )
    from apps.evidence.models import EvidenceRecord
    from apps.schools.models import School

    cur = connection.cursor()
    with transaction.atomic():
        # ── Cost lines: two per costed activity, from its cost snapshot ─────
        _run(
            cur,
            clone_sql(
                cur,
                "activity_schedule_cost_line",
                "activity a join activity_cost_snapshot s on s.activity_id = a.id "
                "and s.is_current cross join (values (1, 'transport', 'Transport'), "
                "(2, 'meals', 'Meals')) k(n, key, label) cross join "
                "(select * from activity_schedule_cost_line order by id limit 1) t",
                {
                    "id": "'ccl' || substr(a.id, 4) || k.n",
                    "activity_id": "a.id",
                    "cost_setting_key": "k.key",
                    "label": "k.label",
                    "unit_cost": "greatest(s.operational_cost / 2, 1)",
                    "quantity": "1",
                    "amount": "greatest(s.operational_cost / 2, 1)",
                    "total_cost": "greatest(s.operational_cost / 2, 1)",
                    "planned_date": "a.planned_date",
                    "week_start_date": "a.week_start_date",
                    "week_end_date": "a.week_end_date",
                    "month": "a.planned_month",
                    "quarter": "a.quarter",
                    "fiscal_year": "a.fy",
                    "responsible_user": "a.responsible_staff_id",
                    "school_id": "a.school_id",
                    "cluster_id": "a.cluster_id",
                    "partner_id": "null",
                    "project_id": "null",
                    "created_at": "now()",
                    "updated_at": "now()",
                },
                "where a.id like 'sac%' and a.status <> 'planned'",
            ),
            label="cost lines",
        )

        # ── Advances: one per line, in the state the activity implies ───────
        _run(
            cur,
            clone_sql(
                cur,
                "advance_request",
                "activity_schedule_cost_line l join activity a on a.id = l.activity_id "
                "cross join (select * from advance_request order by id limit 1) t",
                {
                    "id": "'adv' || substr(l.id, 4)",
                    "activity_id": "a.id",
                    "budget_line_id": "l.id",
                    "responsible_user_id": "a.responsible_staff_id",
                    "fy": "a.fy",
                    "quarter": "coalesce(a.quarter, 'Q1')",
                    "month": "a.planned_month",
                    "week": "extract(week from a.planned_date)::int",
                    "planned_date": "a.planned_date::timestamptz",
                    "amount": "l.amount",
                    "status": """(case
                        when a.status = 'scheduled' and right(l.id, 1) = '1' then 'confirmed_for_advance'
                        when a.status = 'scheduled' then 'submitted_to_accountant'
                        when a.status in ('in_progress', 'evidence_uploaded', 'submitted_to_pl', 'returned_by_pl') then 'disbursed'
                        when a.status = 'awaiting_ia_verification' then 'accountability_pending'
                        else 'accounted' end)""",
                    "disbursed_amount": "(case when a.status = 'scheduled' then null else l.amount end)",
                    "disbursed_at": "(case when a.status = 'scheduled' then null else a.planned_date::timestamptz end)",
                    "accounted_amount": "(case when a.status in ('ia_verified', 'accountant_confirmed', 'completed') then l.amount else null end)",
                    "accountability_netsuite_id": "(case when a.status in ('awaiting_ia_verification', 'ia_verified', 'accountant_confirmed', 'completed') then 'NS-' || l.id else null end)",
                    "reimbursed_amount": "null",
                    "created_at": "now()",
                    "updated_at": "now()",
                },
                "where l.id like 'ccl%' and a.status not in ('planned')",
            ),
            label="advances",
        )

        # ── Evidence for every activity whose evidence was submitted ───────
        any_activity = Activity.objects.filter(id__startswith="sac").first()
        evidence = _template(
            EvidenceRecord,
            activity=any_activity,
            kind="visit_form",
            uri=f"{TEMPLATE_PREFIX}.pdf",
            original_name="visit-form.pdf",
            mime_type="application/pdf",
            file_extension="pdf",
            file_size=184_000,
            uploaded_by="scale",
            scan_status="clean",
        )
        _run(
            cur,
            clone_sql(
                cur,
                "evidence_record",
                "activity a cross join (values (1, 'visit_form'), (2, 'photo')) k(n, kind) "
                f"cross join (select * from evidence_record where id = '{evidence.id}') t",
                {
                    "id": "'evd' || substr(a.id, 4) || k.n",
                    "activity_id": "a.id",
                    "kind": "k.kind",
                    "uri": "'scale/' || a.id || '-' || k.n",
                    "uploaded_by": "coalesce(a.responsible_staff_id, 'scale')",
                    "status": "(case a.evidence_status when 'accepted' then 'accepted' when 'returned' then 'returned' else 'uploaded' end)",
                    "created_at": "a.planned_date::timestamptz",
                    "updated_at": "a.planned_date::timestamptz",
                },
                "where a.id like 'sac%' and a.evidence_status in ('uploaded', 'accepted', 'returned')",
            ),
            label="evidence records",
        )
        evidence.delete()

        # ── Notifications: 200 per account over 90 days, a quarter unread ──
        _run(
            cur,
            clone_sql(
                cur,
                "notification",
                'generate_series(1, 200) g cross join "user" u cross join '
                "(select * from notification order by id limit 1) t",
                {
                    "id": "'ntf' || substr(md5(u.id || g::text), 1, 20)",
                    "recipient_id": "u.id",
                    "recipient_role": "u.active_role",
                    "status": "(case when g % 4 = 0 then 'unread' else 'read' end)",
                    "source_event_type": "'scale'",
                    "source_event_id": "null",
                    "context_id": "null",
                    "created_at": "now() - (g * interval '11 hours')",
                    "updated_at": "now() - (g * interval '11 hours')",
                },
                "where u.deleted_at is null",
            ),
            label="notifications",
        )

        # ── Business Transformation: cases, loans, schedules, payments ─────
        mfi = MfiOrganization.objects.first()
        purpose = LoanPurpose.objects.first()
        bt_owner = User.objects.filter(
            email="business-transformation@edify.org"
        ).first()
        owner_staff = getattr(bt_owner, "staff_profile_id", None)
        school = School.objects.filter(id__startswith="scl").order_by("id").first()
        case = _template(
            TransformationCase,
            school=school,
            status="active",
            owner_staff_id=owner_staff,
            opened_fy="2026",
        )
        _run(
            cur,
            clone_sql(
                cur,
                "bt_case",
                f"school s cross join (select * from bt_case where id = '{case.id}') t",
                {
                    "id": "'btc' || substr(s.id, 4)",
                    "school_id": "s.id",
                    "status": "(array['recommended','triage','active','monitoring','deferred'])[1 + (substr(s.id, 4)::int % 5)]",
                    "created_at": "now()",
                    "updated_at": "now()",
                },
                "where s.id like 'scl%' and substr(s.id, 4)::int % 33 = 0 "
                f"and s.id <> '{school.id}'",
            ),
            label="BT cases",
        )
        loan = _template(
            MfiLoan,
            mfi=mfi,
            school=school,
            case=case,
            purpose=purpose,
            external_loan_reference=f"{TEMPLATE_PREFIX}-loan",
            requested_amount=12_000_000,
            approved_amount=12_000_000,
            disbursed_amount=12_000_000,
            term_months=12,
            repayment_frequency="monthly",
            installment_amount=1_000_000,
            status="active",
            registered_by="scale",
            disbursement_date="2025-11-01",
            disbursement_confirmed_at="2025-11-01T08:00:00Z",
        )
        loan_status = (
            "(array['processing','disbursed','active','active','active','repaid',"
            "'defaulted'])[1 + (substr(c.id, 4)::int % 7)]"
        )
        _run(
            cur,
            clone_sql(
                cur,
                "bt_mfi_loan",
                "bt_case c cross join "
                f"(select * from bt_mfi_loan where id = '{loan.id}') t",
                {
                    "id": "'bln' || substr(c.id, 4)",
                    "school_id": "c.school_id",
                    "case_id": "c.id",
                    "external_loan_reference": "'LN-' || substr(c.id, 4)",
                    "salesforce_loan_id": "null",
                    "salesforce_status": "(array['pending','confirmed','returned'])[1 + (substr(c.id, 4)::int % 3)]",
                    "ia_validation_status": "(array['pending','verified','returned'])[1 + (substr(c.id, 4)::int / 7 % 3)]",
                    "status": loan_status,
                    "default_classified_at": f"(case when {loan_status} = 'defaulted' then date '2026-06-01' else null end)",
                    "default_reason": f"(case when {loan_status} = 'defaulted' then 'Missed three consecutive installments' else '' end)",
                    "disbursement_confirmed_at": "(date '2025-10-01' + (substr(c.id, 4)::int % 300))::timestamptz",
                    "disbursement_date": "date '2025-10-01' + (substr(c.id, 4)::int % 300)",
                    "maturity_date": "date '2026-10-01' + (substr(c.id, 4)::int % 300)",
                    "submitted_at": "now() - (substr(c.id, 4)::int % 300) * interval '1 day'",
                    "created_at": "now()",
                    "updated_at": "now()",
                },
                "where c.id like 'btc%' and substr(c.id, 4)::int % 66 = 0",
            ),
            label="MFI loans",
        )
        installment = _template(
            LoanRepaymentInstallment,
            loan=loan,
            installment_number=1,
            due_date="2026-01-01",
            principal_due=1_000_000,
            created_by="scale",
        )
        _run(
            cur,
            clone_sql(
                cur,
                "bt_loan_repayment_installment",
                "bt_mfi_loan l cross join generate_series(1, 12) g cross join "
                f"(select * from bt_loan_repayment_installment where id = '{installment.id}') t",
                {
                    "id": "'bli' || substr(l.id, 4) || lpad(g::text, 2, '0')",
                    "loan_id": "l.id",
                    "installment_number": "g",
                    "due_date": "l.disbursement_date + g * interval '1 month'",
                    "created_at": "now()",
                    "updated_at": "now()",
                },
                "where l.id like 'bln%'",
            ),
            label="loan installments",
        )
        payment = _template(
            RepaymentTransaction,
            loan=loan,
            kind="payment",
            external_reference=f"{TEMPLATE_PREFIX}-pay",
            idempotency_key=f"{TEMPLATE_PREFIX}-pay",
            amount=1_000_000,
            received_on="2026-02-01",
            value_date="2026-02-01",
            evidence_reference="scale",
            posted_by="scale",
            posted_at="2026-02-01T08:00:00Z",
        )
        _run(
            cur,
            clone_sql(
                cur,
                "bt_repayment_transaction",
                "bt_mfi_loan l cross join generate_series(1, 6) g cross join "
                f"(select * from bt_repayment_transaction where id = '{payment.id}') t",
                {
                    "id": "'brp' || substr(l.id, 4) || g",
                    "loan_id": "l.id",
                    "external_reference": "'PAY-' || substr(l.id, 4) || '-' || g",
                    "idempotency_key": "'scale-pay-' || l.id || '-' || g",
                    "received_on": "l.disbursement_date + g * interval '1 month'",
                    "value_date": "l.disbursement_date + g * interval '1 month'",
                    "posted_at": "(l.disbursement_date + g * interval '1 month')::timestamptz",
                    "created_at": "now()",
                    "updated_at": "now()",
                },
                "where l.id like 'bln%' and l.status in ('active', 'repaid', 'defaulted')",
            ),
            label="repayments",
        )
        application = _template(
            LoanApplication,
            school=school,
            purpose=purpose,
            preferred_mfi=mfi,
            applicant_name="Head Teacher",
            applicant_role="Head Teacher",
            applicant_phone="+256700000000",
            requested_amount=8_000_000,
            intended_use="Classroom construction",
            requested_term_months=12,
            repayment_frequency="monthly",
            consent_recorded_at="2026-03-01T08:00:00Z",
            submitted_at="2026-03-01T08:00:00Z",
        )
        _run(
            cur,
            clone_sql(
                cur,
                "bt_loan_application",
                "school s cross join "
                f"(select * from bt_loan_application where id = '{application.id}') t",
                {
                    "id": "'bla' || substr(s.id, 4)",
                    "school_id": "s.id",
                    "linked_loan_id": "null",
                    "submitted_at": "now() - (substr(s.id, 4)::int % 200) * interval '1 day'",
                    "created_at": "now()",
                    "updated_at": "now()",
                },
                "where s.id like 'scl%' and substr(s.id, 4)::int % 97 = 0",
            ),
            label="loan applications",
        )
        for row in (payment, installment):
            type(row).objects.filter(pk=row.pk)._raw_delete(row._state.db)
        application.delete()
        MfiLoan.all_objects.filter(pk=loan.pk).delete()
        TransformationCase.all_objects.filter(pk=case.pk).delete()

        # ── Leave: two requests per member of staff ────────────────────────
        staff = StaffProfile.objects.filter(deleted_at__isnull=True).first()
        leave = _template(
            Leave,
            staff=staff,
            type="personal_time_off",
            start_date="2026-05-04",
            end_date="2026-05-08",
            days=5,
            status="approved",
        )
        _run(
            cur,
            clone_sql(
                cur,
                "leave",
                "staff_profile p cross join generate_series(1, 2) g cross join "
                f"(select * from leave where id = '{leave.id}') t",
                {
                    "id": "'lvr' || substr(md5(p.id || g::text), 1, 20)",
                    "staff_id": "p.id",
                    "status": "(case when g = 1 then 'approved' else 'pending' end)",
                    "start_date": "to_char(date '2026-02-02' + (g * 70 + length(p.id) * 3), 'YYYY-MM-DD')",
                    "end_date": "to_char(date '2026-02-06' + (g * 70 + length(p.id) * 3), 'YYYY-MM-DD')",
                    "covering_staff_id": "null",
                    "created_at": "now()",
                    "updated_at": "now()",
                },
                "where p.deleted_at is null",
            ),
            label="leave",
        )
        leave.delete()

    cur.execute("analyze")
    counts = {}
    for table in (
        "activity_schedule_cost_line",
        "advance_request",
        "evidence_record",
        "notification",
        "bt_case",
        "bt_mfi_loan",
        "bt_loan_repayment_installment",
        "bt_repayment_transaction",
        "bt_loan_application",
        "leave",
    ):
        cur.execute(f'select count(*) from "{table}"')
        counts[table] = cur.fetchone()[0]
    print("domains:", ", ".join(f"{k} {v:,}" for k, v in counts.items()))


#: Where staff work stands once its officer has submitted it. `complete()`
#: reserves the Salesforce ID on the way (apps.activities.services.complete),
#: so no staff activity reaches these states without one.
SUBMITTED_STATUSES = (
    "submitted_to_pl",
    "returned_by_pl",
    "awaiting_ia_verification",
    "ia_verified",
    "accountant_confirmed",
    "completed",
)


def salesforce() -> None:
    """Give submitted staff work the Salesforce ID its completion reserved.

    The school scaler clones activities without one. Real staff work cannot
    be submitted without a reference, and IA's own precondition refuses to
    verify work that has none, so the verification queue held nothing a
    verifier could act on. Reserved through the canonical
    `reserve_salesforce_id`, one activity at a time, recorded as a legacy
    import.
    """
    from django.db.models import Q

    from apps.accounts.models import User
    from apps.activities.models import Activity
    from apps.activities.salesforce import (
        ENTRY_SOURCE_LEGACY_IMPORT,
        reserve_salesforce_id,
    )
    from apps.activities.services import sf_kind_for_activity

    admin = User.objects.get(email="admin@edify.org")
    ids = list(
        Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="staff",
            status__in=SUBMITTED_STATUSES,
        )
        .filter(Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id=""))
        .order_by("id")
        .values_list("id", flat=True)
    )
    started = time.time()
    reserved = skipped = 0
    for offset in range(0, len(ids), 1000):
        for activity in Activity.objects.filter(id__in=ids[offset : offset + 1000]):
            kind = sf_kind_for_activity(activity)
            if kind is None:
                skipped += 1
                continue
            prefix = "TS" if kind == "training" else "SVE"
            reserve_salesforce_id(
                activity=activity,
                raw_value=f"{prefix}-LT-{activity.id.upper()}",
                kind=kind,
                principal=admin,
                entry_source=ENTRY_SOURCE_LEGACY_IMPORT,
            )
            reserved += 1
        print(
            f"  salesforce: {reserved:,} reserved, {skipped:,} exempt "
            f"({time.time() - started:.0f}s)",
            flush=True,
        )


def main() -> int:
    _guard()
    phase = sys.argv[1] if len(sys.argv) > 1 else ""
    if phase == "people":
        officers = int(os.environ.get("SCALE_OFFICERS", "130"))
        leads = int(os.environ.get("SCALE_LEADS", "12"))
        people(officers, leads)
    elif phase == "domains":
        domains()
    elif phase == "salesforce":
        salesforce()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
