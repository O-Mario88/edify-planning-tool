"""A request that read an activity before a competing write must not win.

Each service below read the activity without a lock, checked its status on
that read, and saved the copy it held. A second request that read the row
before the first one wrote (a double-click, a second tab, a second person
acting on the same activity) was applied on top of the first, and the last
writer won:

  1. IA decisions. `ia_confirm` and `ia_return` both applied. A returned
     activity could end verified, with its clearance payable and its credit
     recorded, and a verified one could end returned with payment_status still
     "ia_confirmed". `complete_partner_ssa_support` locked the school, not the
     activity, so a second completion re-keyed the scores and the enrolment of
     work that was already verified.
  2. `record_attendance` wrote `status` back from its read. A cancel, a lead's
     approval or an IA verification made in between was reverted.
  3. `complete` and `submit_for_review` submitted twice and undid a cancel. On
     a cluster session the second write of the attendance register could
     collide with the first on its unique constraint and return a 500.

Each test hands the service a read taken before the competing write, as the
losing request had. The service must re-read the row under a lock and either
refuse or apply its change to the row as it now stands.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta
from unittest.mock import patch

from django.db import connections
from django.test import TestCase, TransactionTestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities import services
from apps.activities.models import (
    Activity,
    ActivitySalesforceReference,
    ClusterActivityAttendance,
)
from apps.clusters.models import Cluster
from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.partners.models import Partner
from apps.pl_review import services as pl_review
from apps.schools.models import School
from apps.ssa.models import SsaRecord


def _user(email, name, role):
    return User.objects.create(
        email=email,
        name=name,
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
    )


def _staff(email, name, role):
    user = _user(email, name, role)
    return user, StaffProfile.objects.create(user=user, title=name, country="Uganda")


def _evidence(activity, uploaded_by):
    EvidenceRecord.objects.create(
        activity=activity,
        kind="attendance_form",
        uri=f"evidence/{activity.id}.pdf",
        original_name="register.pdf",
        mime_type="application/pdf",
        uploaded_by=uploaded_by,
    )


class OneIaDecisionPerActivityTest(TestCase):
    """Confirm, return and the partner SSA completion decide work once."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Stale Read Region")
        district = District.objects.create(
            name="Stale Read District", region=region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="STALE-IA-1",
            name="Stale Read Primary",
            region=region,
            district=district,
            enrollment=120,
        )
        partner_user = _user(
            "stale-partner@t.test", "Partner Officer", EdifyRole.PARTNER_FIELD_OFFICER
        )
        cls.partner = Partner.objects.create(
            name="Stale Read Partner", user=partner_user, active_status=True
        )
        cls.ia = _user("stale-ia@t.test", "IA One", EdifyRole.IMPACT_ASSESSMENT)
        cls.other_ia = _user("stale-ia2@t.test", "IA Two", EdifyRole.IMPACT_ASSESSMENT)
        cls.monitor, cls.monitor_profile = _staff(
            "stale-monitor@t.test", "Monitor", EdifyRole.CCEO
        )

    def _awaiting(self, **extra):
        today = date.today()
        values = {
            "school": self.school,
            "activity_type": "in_school_training",
            "delivery_type": "partner",
            "assigned_partner_id": self.partner.id,
            "monitored_by_staff_id": self.monitor_profile.id,
            "status": "awaiting_ia_verification",
            "fy": get_operational_fy(today),
            "quarter": get_quarter_for_date(today),
            "planned_date": today,
            "actual_delivery_date": today,
        }
        values.update(extra)
        work = Activity.objects.create(**values)
        _evidence(work, self.partner.user_id)
        return work

    def _ssa_support(self):
        return self._awaiting(
            activity_type="school_visit_ssa_collection", purpose_type="ssa_support"
        )

    def _ssa(self, enrollment):
        return {
            "scores": [
                {"intervention": code, "score": "6"}
                for code, _label in SsaIntervention.choices
            ],
            "enrollment": str(enrollment),
            "salesforceId": "SVE-STALE-0004",
        }

    def _read_before_the_other_decision(self, work):
        return services._get_in_scope(work.id, self.ia)

    def test_a_return_that_lost_to_a_confirmation_leaves_the_work_verified(self):
        work = self._awaiting()
        stale = self._read_before_the_other_decision(work)
        services.ia_confirm(work.id, {"salesforceId": "TS-STALE-0001"}, self.ia)

        with patch.object(services, "_get_in_scope", return_value=stale):
            with self.assertRaises(BadRequest):
                services.ia_return(work.id, {"reason": "Photo unclear"}, self.other_ia)

        work.refresh_from_db()
        self.assertEqual(work.status, "ia_verified")
        self.assertEqual(work.ia_verification_status, "confirmed")
        self.assertEqual(work.payment_status, "ia_confirmed")

    def test_a_confirmation_that_lost_to_a_return_writes_nothing(self):
        work = self._awaiting()
        stale = self._read_before_the_other_decision(work)
        services.ia_return(work.id, {"reason": "Photo unclear"}, self.other_ia)

        with patch.object(services, "_get_in_scope", return_value=stale):
            with self.assertRaises(BadRequest):
                services.ia_confirm(
                    work.id,
                    {"salesforceId": "TS-STALE-0002", "verificationNote": "Fine."},
                    self.ia,
                )

        work.refresh_from_db()
        self.assertEqual(work.status, "returned_by_ia")
        self.assertEqual(work.payment_status, "none")
        # The partner reads the return reason from this note.
        self.assertEqual(work.pl_review_note, "Photo unclear")
        self.assertFalse(
            ActivitySalesforceReference.objects.filter(activity=work).exists()
        )

    def test_a_second_confirmation_is_refused_and_keeps_the_first_verifier(self):
        work = self._awaiting()
        stale = self._read_before_the_other_decision(work)
        services.ia_confirm(work.id, {"salesforceId": "TS-STALE-0003"}, self.ia)

        with patch.object(services, "_get_in_scope", return_value=stale):
            with self.assertRaises(BadRequest):
                services.ia_confirm(
                    work.id, {"salesforceId": "TS-STALE-0003"}, self.other_ia
                )

        work.refresh_from_db()
        self.assertEqual(work.ia_confirmed_by, self.ia.id)

    def test_a_second_ssa_completion_is_refused_and_keeps_the_first(self):
        work = self._ssa_support()
        stale = self._read_before_the_other_decision(work)
        services.complete_partner_ssa_support(work.id, self._ssa(420), self.monitor)

        with patch.object(services, "_get_in_scope", return_value=stale):
            with self.assertRaises(BadRequest):
                services.complete_partner_ssa_support(
                    work.id, self._ssa(999), self.monitor
                )

        self.school.refresh_from_db()
        self.assertEqual(self.school.enrollment, 420)
        self.assertEqual(
            SsaRecord.objects.filter(source_activity_id=work.id).count(), 1
        )


class FieldWorkFixture(TestCase):
    """An officer's school visit, reviewed by their Programme Lead."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Field Region")
        district = District.objects.create(name="Field District", region=region)
        cls.pl_user, pl = _staff(
            "stale-pl@t.test", "Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.cceo_user, cls.cceo = _staff("stale-cceo@t.test", "Officer", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=pl)
        cls.school = School.objects.create(
            school_id="STALE-FW-1",
            name="Field Primary",
            region=region,
            district=district,
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo, school_id=cls.school.id)

    def _work(self, status, **extra):
        values = {
            "school": self.school,
            "activity_type": "school_visit",
            "delivery_type": "staff",
            "status": status,
            "fy": "2026",
            "quarter": "Q4",
            "planned_date": date.today() - timedelta(days=3),
            "responsible_staff_id": self.cceo.id,
        }
        values.update(extra)
        work = Activity.objects.create(**values)
        _evidence(work, self.cceo_user.id)
        return work

    def _read_before_the_other_write(self, work):
        return services._get_for_execution(work.id, self.cceo_user)

    def _cancel(self, work):
        services.cancel(work.id, {"reason": "School closed for exams"}, self.cceo_user)


class AttendanceKeepsTheCurrentStatusTest(FieldWorkFixture):
    ATTENDANCE = {"teachersAttended": 12, "leadersAttended": 2}

    def test_attendance_after_a_cancel_is_refused_and_leaves_it_cancelled(self):
        work = self._work("completion_started")
        stale = self._read_before_the_other_write(work)
        self._cancel(work)

        with patch.object(services, "_get_for_execution", return_value=stale):
            with self.assertRaises(BadRequest):
                services.record_attendance(work.id, self.ATTENDANCE, self.cceo_user)

        work.refresh_from_db()
        self.assertEqual(work.status, "cancelled")
        self.assertIsNone(work.teachers_attended)

    def test_attendance_during_review_keeps_the_leads_approval(self):
        work = self._work("submitted_to_pl")
        stale = self._read_before_the_other_write(work)
        pl_review.confirm(work.id, self.pl_user)

        with patch.object(services, "_get_for_execution", return_value=stale):
            services.record_attendance(work.id, self.ATTENDANCE, self.cceo_user)

        work.refresh_from_db()
        self.assertEqual(work.status, "ia_verified")
        self.assertEqual(work.teachers_attended, 12)


class CompletionIsSubmittedOnceTest(FieldWorkFixture):
    COMPLETION = {"salesforceId": "SVE-STALE-0101"}

    def _leads_notice(self, work):
        return Notification.objects.get(
            recipient_id=self.pl_user.id,
            source_event_type="activity_submitted_for_review",
            context_id=work.id,
        )

    def test_a_second_completion_is_refused_and_the_lead_is_told_once(self):
        work = self._work("completion_started")
        stale = self._read_before_the_other_write(work)
        services.complete(work.id, self.COMPLETION, self.cceo_user)

        with patch.object(services, "_get_for_execution", return_value=stale):
            with self.assertRaises(BadRequest):
                services.complete(work.id, self.COMPLETION, self.cceo_user)

        self.assertEqual(self._leads_notice(work).reminder_count, 0)

    def test_a_completion_that_lost_to_a_cancel_leaves_it_cancelled(self):
        work = self._work("completion_started")
        stale = self._read_before_the_other_write(work)
        self._cancel(work)

        with patch.object(services, "_get_for_execution", return_value=stale):
            with self.assertRaises(BadRequest):
                services.complete(work.id, self.COMPLETION, self.cceo_user)

        work.refresh_from_db()
        self.assertEqual(work.status, "cancelled")

    def test_a_second_submission_for_review_is_refused(self):
        work = self._work("completion_started", salesforce_activity_id="SVE-STALE-0102")
        stale = self._read_before_the_other_write(work)
        services.submit_for_review(work.id, self.cceo_user)

        with patch.object(services, "_get_for_execution", return_value=stale):
            with self.assertRaises(BadRequest):
                services.submit_for_review(work.id, self.cceo_user)

        self.assertEqual(self._leads_notice(work).reminder_count, 0)


class SimultaneousClusterCompletionsTest(TransactionTestCase):
    """The double-click on a cluster session, for real: two requests on two
    connections, both through the unlocked read before either writes. The
    loser either submitted the session again or collided with the winner's
    attendance rows on their unique constraint (a 500)."""

    reset_sequences = False

    def setUp(self):
        region = Region.objects.create(name="Race Region")
        district = District.objects.create(name="Race District", region=region)
        self.cceo_user, cceo = _staff(
            "race-cluster-cceo@t.test", "Race CCEO", EdifyRole.CCEO
        )
        cluster = Cluster.objects.create(
            name="Race Cluster",
            region=region,
            district=district,
            responsible_staff_id=cceo.id,
        )
        self.schools = [
            School.objects.create(
                school_id=f"RACE-C-{n}",
                name=f"Race School {n}",
                region=region,
                district=district,
                cluster_id=cluster.id,
            )
            for n in (1, 2)
        ]
        self.session = Activity.objects.create(
            activity_type="cluster_training",
            delivery_type="staff",
            status="completion_started",
            fy="2026",
            quarter="Q4",
            cluster=cluster,
            responsible_staff_id=cceo.id,
            planned_date=date.today() - timedelta(days=1),
        )
        _evidence(self.session, self.cceo_user.id)

    def test_two_simultaneous_completions_apply_once(self):
        workers = 2
        both_have_read = threading.Barrier(workers)
        read = services._get_for_execution
        outcomes: list[str] = []

        def read_then_wait(activity_id, principal):
            activity = read(activity_id, principal)
            both_have_read.wait(timeout=10)
            return activity

        def complete():
            try:
                services.complete(
                    self.session.id,
                    {
                        "salesforceId": "TS-RACE-0001",
                        "teachersAttended": 12,
                        "leadersAttended": 2,
                        "attendedSchoolIds": [s.id for s in self.schools],
                    },
                    self.cceo_user,
                )
                outcomes.append("completed")
            except BadRequest:
                outcomes.append("refused")
            except Exception as exc:  # pragma: no cover - the assertion reports it
                outcomes.append(repr(exc))
            finally:
                for db_connection in connections.all():
                    db_connection.close()

        with patch.object(services, "_get_for_execution", side_effect=read_then_wait):
            threads = [threading.Thread(target=complete) for _ in range(workers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        self.assertEqual(sorted(outcomes), ["completed", "refused"])
        self.assertEqual(
            ClusterActivityAttendance.objects.filter(
                activity=self.session, attended=True
            ).count(),
            2,
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "submitted_to_pl")
