"""Browser-journey fixture for Partner-supported schools (e2e only).

Runs against the LOCAL demo-seeded database the browser suite uses, and only
through the canonical services — the same doors the pages use — so a journey
never starts from a state the application itself could not produce:

    python scripts/e2e_partner_support_fixture.py setup
    python scripts/e2e_partner_support_fixture.py partner-progress <assignment>
    python scripts/e2e_partner_support_fixture.py ia-verify <activity>
    python scripts/e2e_partner_support_fixture.py partner-return <assignment>
    python scripts/e2e_partner_support_fixture.py inspect <school code>
    python scripts/e2e_partner_support_fixture.py dates [count]
    python scripts/e2e_partner_support_fixture.py reset

Each prints one JSON object. ``setup`` is idempotent: it reuses the live
handovers it made on an earlier run instead of stacking new ones.

It refuses to run in production, like every other local-data command.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

if getattr(settings, "IS_PRODUCTION", False) or os.environ.get("NODE_ENV") == (
    "production"
):
    raise SystemExit("The e2e fixture never runs in production.")

from apps.accounts.models import User  # noqa: E402
from apps.activities.models import Activity  # noqa: E402
from apps.partners.models import Partner, PartnerAssignment  # noqa: E402

# Literacy Uganda is the organisation partner@edify.org signs in for.
PARTNERS = ("Literacy Uganda", "Build Africa", "World Reader")
MARKER = "e2e-partner-support"


def _user(email):
    return User.objects.get(email=email)


def _cceo_schools(user):
    """Clustered client schools with no Partner history of their own.

    The demo seed hands some schools to Partners already; a journey that starts
    from one of those would be asserting the seed, not the rule.
    """
    from apps.core.scoping import direct_portfolio_schools, resolve_user_scope

    seeded = PartnerAssignment.objects.exclude(notes=MARKER).values("school_id")
    worked = Activity.objects.filter(
        deleted_at__isnull=True, delivery_type="partner"
    ).values("school_id")
    return list(
        direct_portfolio_schools(resolve_user_scope(user))
        .filter(
            school_type="client",
            cluster_status="clustered",
            deleted_at__isnull=True,
        )
        .exclude(cluster_id__isnull=True)
        .exclude(cluster_id="")
        .exclude(id__in=seeded)
        .exclude(id__in=worked)
        .order_by("cluster_id", "school_id")[:12]
    )


def _handover(school, partner, cceo):
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.partners.services import create_assignment

    live = (
        PartnerAssignment.objects.filter(school=school, partner=partner, notes=MARKER)
        .exclude(status=PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        .first()
    )
    if live:
        return live
    # SSA Support: one of the three purposes a Partner may be handed, and the
    # one whose completion needs no earlier session to exist at the school.
    item = ActivityCatalogueItem.objects.get(
        stable_code="STANDARD_SCHOOL_VISIT_SSA_COLLECTION"
    )
    return create_assignment(
        school=school,
        partner=partner,
        assigning_staff_id=cceo.staff_profile.id,
        monitoring_staff_id=cceo.staff_profile.id,
        catalogue_item=item,
        expected_activity_type=item.workflow_kind,
        purpose_of_visit="ssa_support",
        notes=MARKER,
    )


def setup():
    cceo = _user("cceo@edify.org")
    schools = _cceo_schools(cceo)
    if len(schools) < 5:
        raise SystemExit("cceo@edify.org holds too few clustered schools.")
    partners = [Partner.objects.get(name=name) for name in PARTNERS]
    rows = []
    # Three schools, three Partners (Journeys 1, 5, 7), and a fourth school
    # with a second Literacy Uganda handover for the return journey (8).
    for school, partner in [*zip(schools[:3], partners), (schools[3], partners[0])]:
        assignment = _handover(school, partner, cceo)
        rows.append(
            {
                "school_pk": school.id,
                "school_id": school.school_id,
                "name": school.name,
                "cluster_id": school.cluster_id,
                "partner": partner.name,
                "partner_id": partner.id,
                "assignment_id": assignment.id,
                "status": assignment.status,
            }
        )
    staff_managed = schools[4]
    from apps.accounts.models import StaffSupervisorAssignment

    lead = (
        StaffSupervisorAssignment.objects.filter(supervisee=cceo.staff_profile)
        .select_related("supervisor__user")
        .first()
    )
    print(
        json.dumps(
            {
                "cceo_name": cceo.name,
                "handovers": rows,
                "staff_managed": {
                    "school_id": staff_managed.school_id,
                    "name": staff_managed.name,
                },
                "pl_email": lead.supervisor.user.email if lead else "pl1@edify.org",
            }
        )
    )


def partner_progress(assignment_id):
    """The Partner starts the scheduled work and submits evidence to IA."""
    from apps.activities.services import complete, start_completion
    from apps.evidence.models import EvidenceRecord

    officer = _user("partner@edify.org")
    assignment = PartnerAssignment.objects.get(id=assignment_id)
    activity = assignment.scheduled_activity
    if activity is None:
        raise SystemExit("Schedule the assignment in the browser first.")
    if activity.status in ("scheduled", "partner_scheduled"):
        # A fixture date in the past is what lets the Partner start today.
        Activity.objects.filter(id=activity.id).update(
            planned_date=date.today() - timedelta(days=1)
        )
        start_completion(activity.id, {}, officer)
    if not EvidenceRecord.objects.filter(activity_id=activity.id).exists():
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="visit_form",
            uri=f"{MARKER}-{activity.id}.pdf",
            original_name="visit-form.pdf",
            mime_type="application/pdf",
            uploaded_by=officer.id,
            uploader_role=officer.active_role,
        )
    activity.refresh_from_db()
    if activity.status not in ("awaiting_ia_verification", "ia_verified"):
        complete(
            activity.id,
            {
                "actualDeliveryDate": (date.today() - timedelta(days=1)).isoformat(),
                "actualOutcome": "Follow-up delivered with the head teacher.",
                "feedbackFinding": "Lesson plans are in use in every class visited.",
                "schoolImprovements": ["Weekly staff meeting now reviews lesson plans"],
                "teachersAttended": 4,
                "leadersAttended": 1,
            },
            officer,
        )
    activity.refresh_from_db()
    print(json.dumps({"activity_id": activity.id, "status": activity.status}))


def ia_verify(activity_id):
    """Impact Assessment records the SSA results, which completes the work."""
    from apps.activities.services import complete_partner_ssa_support
    from apps.core.enums import SsaIntervention

    ia = _user("ia@edify.org")
    activity = Activity.objects.get(id=activity_id)
    if activity.status == "awaiting_ia_verification":
        complete_partner_ssa_support(
            activity.id,
            {
                "enrollment": 320,
                "scores": [
                    {"intervention": code, "score": 6.0}
                    for code, _label in SsaIntervention.choices
                ],
                "salesforceId": f"SVE-E2E{activity.id[-8:].upper()}",
            },
            ia,
        )
    activity.refresh_from_db()
    print(
        json.dumps(
            {
                "activity_id": activity.id,
                "status": activity.status,
                "ia": activity.ia_verification_status,
            }
        )
    )


def partner_return(assignment_id):
    from apps.partners.services import return_assignment

    officer = _user("partner@edify.org")
    result = return_assignment(
        assignment_id,
        {
            "reason_category": "school_unavailable",
            "reason": "The school is closed for national examinations.",
        },
        officer,
    )
    print(json.dumps(result))


def inspect(school_code):
    """What the database says about one school, for the journey to assert."""
    from apps.activities.models import ActivityScheduleCostLine
    from apps.fund_requests.fundable import fundable_lines
    from apps.schools.models import School
    from apps.targets.models import TargetAchievementLedger

    school = School.objects.get(school_id=school_code)
    activities = list(
        Activity.objects.filter(school=school, deleted_at__isnull=True).order_by(
            "created_at"
        )
    )
    lines = ActivityScheduleCostLine.objects.filter(
        activity__in=[a.id for a in activities]
    )
    fundable = set(fundable_lines(lines).values_list("activity_id", flat=True))
    partner_ids = [a.id for a in activities if a.delivery_type == "partner"]
    print(
        json.dumps(
            {
                "owner": school.account_owner_id,
                "district": school.district_id,
                "cluster": school.cluster_id,
                "assignments": PartnerAssignment.objects.filter(school=school).count(),
                "activities": [
                    {
                        "id": a.id,
                        "type": a.activity_type,
                        "delivery": a.delivery_type,
                        "status": a.status,
                        "fy": a.fy,
                        "responsible": a.responsible_staff_id,
                        "cost_lines": lines.filter(activity_id=a.id).count(),
                        "cost_missing": a.cost_missing,
                        "staff_fundable": a.id in fundable,
                    }
                    for a in activities
                ],
                "partner_credits": TargetAchievementLedger.objects.filter(
                    source_id__in=partner_ids
                ).count(),
            }
        )
    )


def reset():
    """Undo what earlier journey runs left behind, so a rerun starts clean.

    Soft-deletes the activities the journeys created — the ones whose goal
    they wrote as "E2E …", and the Partner's scheduled work on the marker
    handovers — then removes the marker handovers themselves. Nothing the
    demo seed created is touched.
    """
    from django.utils import timezone

    marker = PartnerAssignment.objects.filter(notes=MARKER)
    partner_work = [
        a for a in marker.values_list("scheduled_activity_id", flat=True) if a
    ]
    now = timezone.now()
    removed = (
        Activity.objects.filter(deleted_at__isnull=True)
        .filter(activity_purpose_text__startswith="E2E ")
        .update(deleted_at=now)
    )
    removed += Activity.objects.filter(
        id__in=partner_work, deleted_at__isnull=True
    ).update(deleted_at=now)
    # The SSA results ``ia-verify`` recorded on that work: a rerun on the same
    # day would otherwise meet its own record as a duplicate.
    from apps.ssa.models import SsaRecord

    SsaRecord.objects.filter(
        source_activity_id__in=partner_work, deleted_at__isnull=True
    ).update(deleted_at=now)
    replacements = PartnerAssignment.objects.filter(replaces_assignment__in=marker)
    count = replacements.count() + marker.count()
    replacements.delete()
    marker.delete()
    print(json.dumps({"activities": removed, "assignments": count}))


def dates(count="4"):
    """The next weekdays the calendar policy accepts for cceo@edify.org."""
    from apps.core.calendar_policy import SchedulingPolicyService

    cceo = _user("cceo@edify.org")
    day, found = date.today() + timedelta(days=2), []
    while len(found) < int(count):
        day += timedelta(days=1)
        if day.weekday() >= 5:
            continue
        if SchedulingPolicyService.check(cceo, day)["status"] != "blocked":
            found.append(
                {
                    "date": day.isoformat(),
                    "fy": str(day.year + 1 if day.month >= 10 else day.year),
                }
            )
    print(json.dumps({"dates": found}))


if __name__ == "__main__":
    command, *args = sys.argv[1:] or ["setup"]
    {
        "setup": setup,
        "partner-progress": partner_progress,
        "ia-verify": ia_verify,
        "partner-return": partner_return,
        "inspect": inspect,
        "reset": reset,
        "dates": dates,
    }[command](*args)
