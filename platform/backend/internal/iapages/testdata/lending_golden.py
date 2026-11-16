"""Write lending_golden.json: Impact Assessment's Lending Evidence
(/ia/lending-evidence/) as the existing feed reads it, over loans and
evidence the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/lending_golden.json \\
    python manage.py shell < platform/backend/internal/iapages/testdata/lending_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gle": a transformation case and four loans (three with the demo
lending partner, one of them at a school in a CCEO's portfolio; one with the
other partner), each disbursed (one twice, one reversed) in two years;
reported loan use, enrolment snapshots (reported and verified, baseline and
follow-up), purpose outputs and teacher completions; and impact conclusions
due and not, prepared and not, awaiting, returned with a note and verified
with each classification. It asks every tab of the readers the page opens
for, the conclusions' states, a page past the end and values the page does
not offer, writes the rows and the answers to GOLDEN_OUT and deletes the rows.
internal/integration/ia_lending_test.go files the same rows and compares.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.business_transformation import models as bt
from apps.core.scoping import resolve_user_scope
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("lending_golden.py runs only against a _test database")

User = get_user_model()
PATH = "/ia/lending-evidence/"
#: Children first.
TABLES = (
    "bt_loan_disbursement_reversal",
    "bt_loan_impact_assessment",
    "bt_teacher_degree_beneficiary",
    "bt_purpose_asset_output",
    "bt_enrolment_snapshot",
    "bt_loan_purpose_allocation",
    "bt_loan_disbursement",
    "bt_funding_facility_allocation",
    "bt_mfi_loan",
    "bt_case",
)
TODAY = dj_timezone.localdate()
NOW = dj_timezone.now()
DEMO, OTHER = "cmw9p8ddb00vtgeekhekc", "cmwbkq8eh00chvekeleuz"
FACILITY = "cmwbnbmdp0051bmlddg42"


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM \"{table}\" WHERE id LIKE 'gle%%'")  # noqa: S608  # nosec B608


def file_rows():
    admin = User.objects.get(email="admin@edify.org")
    cceo = User.objects.get(email="cceo@edify.org")
    own = sorted(resolve_user_scope(cceo).school_ids)[0]
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM school WHERE deleted_at IS NULL AND id <> %s ORDER BY id LIMIT 3",
            [own],
        )
        others = [r[0] for r in cursor.fetchall()]
    purposes = list(bt.LoanPurpose.objects.order_by("code")[:3])
    case = bt.TransformationCase.objects.create(
        id="glecase", school_id=others[0], opened_fy="2026"
    )
    loans = []
    for n, (mfi, school, purpose) in enumerate(
        (
            (DEMO, others[0], purposes[0]),
            (DEMO, own, purposes[0]),
            (DEMO, others[1], purposes[1]),
            (OTHER, others[2], purposes[2]),
        )
    ):
        loans.append(
            bt.MfiLoan.objects.create(
                id=f"gleloan{n}",
                mfi_id=mfi,
                school_id=school,
                case=case,
                purpose=purpose,
                external_loan_reference=f"GLE-{n}",
                registered_by=admin.id,
            )
        )
    # Disbursements: two years; the first loan twice, one reversed.
    for n, (loan, day, amount) in enumerate(
        (
            (0, -400, 5000),
            (0, -350, 2000),
            (1, -400, 7000),
            (2, -40, 9000),
            (3, -30, 3000),
        )
    ):
        # One facility allocation a loan, whatever its disbursements.
        alloc, _ = bt.FundingFacilityAllocation.objects.get_or_create(
            loan=loans[loan],
            defaults={
                "id": f"gleffa{loan}",
                "facility_id": FACILITY,
                "amount": 7000 if loan == 0 else amount,
                "idempotency_key": f"gle-ffa-{loan}",
                "reserved_by": admin.id,
                "reserved_at": NOW,
            },
        )
        bt.LoanDisbursement.objects.create(
            id=f"gledis{n}",
            loan=loans[loan],
            allocation=alloc,
            sequence=1 if n != 1 else 2,
            external_reference=f"GLE-D{n}",
            idempotency_key=f"gle-dis-{n}",
            amount=amount,
            disbursed_on=TODAY + timedelta(days=day),
            value_date=TODAY + timedelta(days=day),
            bank_reference=f"GLE-B{n}",
            confirmed_by=admin.id,
            confirmed_at=NOW,
        )
    alloc_use = bt.LoanPurposeAllocation.objects.create(
        id="glepa0",
        loan=loans[0],
        purpose=purposes[0],
        planned_amount=5000,
        intended_output="Two classrooms for P5 and P6, roofed and floored before the rains",
        recorded_by=admin.id,
        status=bt.PurposeAllocationStatus.REPORTED,
        reported_amount=4800,
    )
    bt.LoanPurposeAllocation.objects.create(
        id="glepa1",
        loan=loans[1],
        purpose=purposes[0],
        planned_amount=7000,
        intended_output="One classroom",
        recorded_by=admin.id,
        status=bt.PurposeAllocationStatus.REPORTED,
        reported_amount=7000,
    )
    for n, (loan, kind, day, count, status) in enumerate(
        (
            (0, "baseline", -410, 300, "verified"),
            (0, "follow_up", -20, 345, "verified"),
            (1, "baseline", -405, 200, "reported"),
            (2, "baseline", -45, 150, "verified"),
        )
    ):
        bt.EnrolmentSnapshot.objects.create(
            id=f"gleen{n}",
            loan=loans[loan],
            kind=kind,
            as_of_date=TODAY + timedelta(days=day),
            learner_count=count,
            cohort_definition="All learners",
            evidence_reference=f"REG-{n}",
            reported_by=admin.id,
            status=status,
            verified_by=admin.id if status == "verified" else None,
            verified_at=NOW if status == "verified" else None,
        )
    bt.PurposeSpecificAssetOutput.objects.create(
        id="gleout0",
        allocation=alloc_use,
        asset_type="classroom_block",
        planned_quantity=2,
        reported_quantity=2,
        reported_operational_quantity=1,
        reported_by=admin.id,
        status=bt.ImpactEvidenceStatus.REPORTED,
        evidence_reference="PHOTO-1",
    )
    bt.TeacherDegreeUpgradeBeneficiary.objects.create(
        id="gletch0",
        loan=loans[0],
        anonymized_reference="T-001",
        institution="Kyambogo",
        programme="B.Ed",
        started_on=TODAY - timedelta(days=700),
        completed_on=TODAY - timedelta(days=10),
        evidence_reference="CERT-1",
        reported_by=admin.id,
        status=bt.ImpactEvidenceStatus.REPORTED,
    )
    status = bt.IAValidationStatus
    for n, (loan, due, ia, prepared, classification, note) in enumerate(
        (
            (0, -10, status.PENDING, False, "", ""),
            (0, -5, status.PENDING, True, "positive", ""),
            (1, -3, status.RETURNED, True, "mixed", "Baseline register missing"),
            (1, 30, status.PENDING, False, "", ""),
            (2, -60, status.VERIFIED, True, "negative", ""),
            (3, -1, status.VERIFIED, True, "insufficient_evidence", ""),
        )
    ):
        bt.LoanImpactAssessment.objects.create(
            id=f"gleia{n}",
            loan=loans[loan],
            due_date=TODAY + timedelta(days=due),
            ia_status=ia,
            prepared_at=NOW if prepared else None,
            prepared_by=admin.id if prepared else None,
            classification=classification or bt.LoanImpactStatus.INSUFFICIENT_EVIDENCE,
            ia_note=note,
        )
    # The first loan's second disbursement is reversed.
    bt.LoanDisbursementReversal.objects.create(
        id="glerev1",
        disbursement_id="gledis1",
        idempotency_key="gle-rev-1",
        reason="Paid to the wrong account",
        reversed_by=admin.id,
        reversed_at=NOW,
    )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gle%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


TABS = ("use", "enrolment", "outputs", "teachers", "conclusions", "cohorts")
QUESTIONS = (
    [{}]
    + [{"tab": t} for t in TABS]
    + [
        {"tab": "conclusions", "state": s}
        for s in ("to_prepare", "awaiting", "returned", "verified", "bogus")
    ]
    + [{"tab": "bogus"}, {"tab": "use", "page": "2"}, {"tab": "cohorts", "page": "x"}]
)
READERS = {
    "ia@edify.org": QUESTIONS,
    "cd@edify.org": QUESTIONS,
    "admin@edify.org": [{}, {"tab": "conclusions"}, {"tab": "cohorts"}],
    "cceo@edify.org": [{}, {"tab": "conclusions"}, {"tab": "cohorts"}],
    "cceo1@edify.org": [{}],
    "pl1@edify.org": [{}],
    "mfi-admin@edify.org": [{}, {"tab": "cohorts"}],
    "business-transformation@edify.org": [{}, {"tab": "conclusions"}],
    "accountant@edify.org": [{}],
}

clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    for email, asked in READERS.items():
        user = User.objects.get(email=email)
        for query in asked:
            with transaction.atomic():
                status, body = read_page(user, PATH, query)
                transaction.set_rollback(True)
            answers.append(
                {
                    "email": email,
                    "path": PATH,
                    "query": query,
                    "status": status,
                    "body": body,
                }
            )
finally:
    clear()
with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {"today": TODAY.isoformat(), "rows": rows, "answers": answers},
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
