"""The Impact Assessment build of 2026-09-03: told when work arrives, a
morning digest, verification analytics with export, sample checks, IA
targets and coverage, and intervention attribution."""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.ia_models import (
    IAVerification,
    ReturnedReason,
    VerificationDecision,
    VerificationHistory,
    VerificationSample,
)
from apps.activities.models import Activity
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.schools.models import School


def _user(email, name, role, country="Uganda"):
    u = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=u, title=role, country=country)
    return u


class IaOversightFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="OB Central", country="Uganda")
        cls.district = District.objects.create(name="OB Wakiso", region=cls.region)
        cls.school = School.objects.create(
            name="OB Kampala Primary",
            school_id="OB-UG-1",
            region=cls.region,
            district=cls.district,
        )
        cls.ia = _user("ob-ia@t.org", "Ida", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.ia2 = _user("ob-ia2@t.org", "Ivan", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.cd = _user("ob-cd@t.org", "Dan", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.cceo = _user("ob-cceo@t.org", "Cara", EdifyRole.CCEO.value)
        cls.ke_ia = _user(
            "ob-ke-ia@t.org", "Kip", EdifyRole.IMPACT_ASSESSMENT.value, "Kenya"
        )

    def _activity(
        self, responsible, status="awaiting_ia_verification", code="SF-1", **kw
    ):
        return Activity.objects.create(
            activity_type=kw.pop("activity_type", "school_visit"),
            status=status,
            school=self.school,
            fy="2026",
            planned_date=date(2026, 3, 2),
            responsible_staff_id=responsible.staff_profile.id,
            salesforce_activity_id=code,
            submitted_to_ia_at=timezone.now() - timedelta(hours=kw.pop("age_hours", 2)),
            **kw,
        )


class SubmissionNotificationTest(IaOversightFixture):
    def test_submitting_work_tells_the_countrys_verifiers_but_not_the_submitter(self):
        from apps.activities.services import _notify_ia_submitted

        a = self._activity(self.cceo)
        _notify_ia_submitted(a)
        recipients = set(
            Notification.objects.filter(
                source_event_type="activity_submitted_for_verification"
            ).values_list("recipient_id", flat=True)
        )
        self.assertEqual(recipients, {self.ia.id, self.ia2.id})
        n = Notification.objects.filter(recipient_id=self.ia.id).first()
        self.assertEqual(n.target_route, f"/ia/verification/{a.id}/")

    def test_an_ia_officers_own_work_goes_to_the_country_director(self):
        from apps.activities.services import _notify_ia_submitted

        a = self._activity(self.ia, code="SF-2")
        _notify_ia_submitted(a)
        recipients = set(
            Notification.objects.filter(
                source_event_type="activity_submitted_for_verification"
            ).values_list("recipient_id", flat=True)
        )
        self.assertEqual(recipients, {self.cd.id})


class MorningDigestTest(IaOversightFixture):
    def test_the_digest_counts_waiting_and_overdue_work_once_a_day(self):
        from apps.realtime.jobs import _do_ia_verification_digest

        self._activity(self.cceo, code="SF-3", age_hours=2)
        self._activity(self.cceo, code="SF-4", age_hours=30)
        self._activity(
            self.ia, code="SF-5", age_hours=2
        )  # Ida's own: not hers to verify
        created = _do_ia_verification_digest()
        self.assertEqual(created, 2)  # Ida and Ivan; Kip has nothing in Kenya
        ida = Notification.objects.get(
            recipient_id=self.ia.id, source_event_type="ia_verification_digest"
        )
        self.assertIn("2 waiting", ida.title)
        self.assertIn("1 past 24h", ida.title)
        ivan = Notification.objects.get(
            recipient_id=self.ia2.id, source_event_type="ia_verification_digest"
        )
        self.assertIn("3 waiting", ivan.title)
        self.assertEqual(_do_ia_verification_digest(), 0)  # same day: no repeat


class VerificationAnalyticsTest(IaOversightFixture):
    def _decide(self, activity, verifier, decision, reasons=()):
        v, _ = IAVerification.objects.get_or_create(activity=activity)
        VerificationDecision.objects.create(
            verification=v, decision=decision, decided_by=verifier.id
        )
        for r in reasons:
            ReturnedReason.objects.create(verification=v, reason=r)
        if decision == "APPROVE":
            VerificationHistory.objects.create(
                activity=activity, verified_by=verifier.id, verified_at=timezone.now()
            )

    def test_the_analytics_read_reasons_submitters_and_verifiers(self):
        from apps.activities.verification_analytics import verification_analytics

        a1 = self._activity(self.cceo, status="ia_verified", code="SF-6")
        a2 = self._activity(self.cceo, status="returned_by_ia", code="SF-7")
        self._decide(a1, self.ia, "APPROVE")
        self._decide(
            a2, self.ia, "RETURN", reasons=["Evidence missing", "Wrong school"]
        )
        data = verification_analytics(self.ia, window_days=30)
        self.assertEqual(data["decisions"], 2)
        self.assertEqual(data["returned"], 1)
        self.assertEqual(data["return_rate"], 50)
        self.assertEqual(
            {r["reason"] for r in data["reasons"]}, {"Evidence missing", "Wrong school"}
        )
        cara = next(r for r in data["submitters"] if r["name"] == "Cara")
        self.assertEqual(
            (cara["submitted"], cara["returned"], cara["return_rate"]), (2, 1, 50)
        )
        ida = next(v for v in data["verifiers"] if v["name"] == "Ida")
        self.assertEqual(ida["verified"], 1)
        self.assertEqual(ida["within_24h"], 100)

    def test_the_page_and_export_are_served_to_ia_and_cd(self):
        for who in (self.ia, self.cd):
            self.client.force_login(who)
            page = self.client.get("/ia/analytics/?window=90")
            self.assertEqual(page.status_code, 200, who.active_role)
            export = self.client.get("/ia/analytics/export?window=90")
            self.assertEqual(export.status_code, 200, who.active_role)
            self.assertEqual(export["Content-Type"], "text/csv")
        self.client.force_login(self.cceo)
        self.assertNotEqual(self.client.get("/ia/analytics/").status_code, 200)


@override_settings(IA_VERIFICATION_SAMPLE_SHARE_PCT=50)
class SampleChecksTest(IaOversightFixture):
    def _verified(self, code):
        a = self._activity(self.cceo, status="ia_verified", code=code)
        VerificationHistory.objects.create(
            activity=a, verified_by=self.ia.id, verified_at=timezone.now()
        )
        return a

    def test_a_share_is_drawn_once_and_graded_by_a_second_verifier(self):
        from apps.activities.verification_sampling import draw_samples, record_outcome

        for i in range(4):
            self._verified(f"SF-S{i}")
        self.assertEqual(draw_samples(days=7), 2)
        self.assertEqual(draw_samples(days=7), 0)  # same week, nothing new
        sample = VerificationSample.objects.first()
        self.assertEqual(sample.original_verifier, self.ia.id)
        with self.assertRaises(Forbidden):
            record_outcome(sample.id, "confirmed", "", self.ia)  # her own
        with self.assertRaises(Forbidden):
            record_outcome(sample.id, "confirmed", "", self.cceo)
        graded = record_outcome(
            sample.id, "disputed", "Attendance sheet was blank", self.ia2
        )
        self.assertEqual(graded.status, "disputed")
        self.assertEqual(graded.checked_by, self.ia2.id)

        from apps.activities.verification_analytics import verification_analytics

        ida = next(
            v
            for v in verification_analytics(self.ia2, 30)["verifiers"]
            if v["name"] == "Ida"
        )
        self.assertEqual((ida["sampled"], ida["sample_accuracy"]), (1, 0))

    def test_the_sample_page_serves_and_the_draw_action_works(self):
        self._verified("SF-S9")
        self.client.force_login(self.ia)
        self.assertEqual(self.client.get("/ia/samples/").status_code, 200)
        response = self.client.post("/ia/samples/draw")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(VerificationSample.objects.count(), 1)


class IaTargetsAndCoverageTest(IaOversightFixture):
    def test_ia_reaches_my_targets_and_coverage(self):
        self.client.force_login(self.ia)
        self.assertEqual(self.client.get("/my-targets").status_code, 200)
        self.assertEqual(self.client.get("/coverage").status_code, 200)


class AttributionTest(IaOversightFixture):
    def test_movement_is_read_from_confirmed_assessments_only(self):
        from apps.analytics.attribution_service import attribution
        from apps.ssa.models import SsaRecord, SsaScore

        def rec(fy, status, score, day):
            r = SsaRecord.objects.create(
                school=self.school,
                date_of_ssa=timezone.make_aware(
                    timezone.datetime(int(fy), 3, day, 9, 0)
                ),
                fy=fy,
                quarter="Q2",
                verification_status=status,
                average_score=score,
            )
            SsaScore.objects.create(
                ssa_record=r, intervention="christlike_behaviour", score=score
            )
            return r

        rec("2025", "confirmed", 4.0, 1)
        rec("2026", "confirmed", 6.0, 1)
        rec("2026", "pending", 9.0, 2)  # unconfirmed: never read
        self._activity(
            self.cceo,
            status="completed",
            code="SF-A1",
            activity_type="cluster_training",
            focus_intervention="christlike_behaviour",
        )
        data = attribution(self.ia, fy="2026")
        row = next(
            r for r in data["rows"] if r["intervention"] == "christlike_behaviour"
        )
        self.assertEqual(
            (
                row["schools_measured"],
                row["avg_prior"],
                row["avg_latest"],
                row["movement"],
            ),
            (1, 4.0, 6.0, 2.0),
        )
        self.assertEqual(row["trainings"], 1)
        self.assertEqual(data["confirmed_share"], 50)
        self.client.force_login(self.ia)
        self.assertEqual(self.client.get("/ia/attribution/?fy=2026").status_code, 200)


class LedgerPolishTest(IaOversightFixture):
    def test_the_history_ledger_names_people_and_pages(self):
        a = self._activity(self.cceo, status="ia_verified", code="SF-H1")
        VerificationHistory.objects.create(
            activity=a, verified_by=self.ia.id, verified_at=timezone.now()
        )
        self.client.force_login(self.ia2)
        page = self.client.get("/ia/history/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Cara")  # the CCEO, not her staff id
        self.assertContains(page, "Ida")  # the verifier, not her user id
        self.assertNotContains(page, self.cceo.staff_profile.id)
        self.assertIn("history_pager", page.context)
        for url in ("/ia/returned/", "/ia/duplicates/", "/ia/notifications/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
