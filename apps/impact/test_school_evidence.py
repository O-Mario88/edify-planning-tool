"""School progress and the new measures (IA review, owner, 2026-09-13).

Pinned here:
- student learning, discipleship and EdTech evidence lands pending and is
  confirmed by someone other than the recorder: a second IA officer in the
  country, the Country Director only where the recorder is its one officer;
- every read and decision stops at the reader's country;
- a delivered OneTest visit records its class results from the visit;
- class results compare the same class and subject year on year, withholding
  small classes, and a CSV records every row or none;
- Most Significant Change stories are reviewed by someone other than the
  author and, once approved, count as discipleship evidence;
- the Outcomes view leads with portfolio school change through the one
  change rule, and reads "Not measured" — never 0 — when nothing is measured;
- the school profile heads with the confirmed SSA and counts pairs, not
  activities; Declining Schools survives a bad FY and names interventions;
- the pages and To-Do builders cost a fixed number of queries.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.impact import evidence_services as ev
from apps.impact.models import (
    DefinitionStatus,
    DiscipleshipIndicatorRecord,
    EdTechCheck,
    EdTechDeployment,
    LearningAssessmentResult,
    OutcomeArea,
    OutcomeAreaDomain,
)
from apps.notifications.models import Notification
from apps.notifications.services import NotificationLinkResolver
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.targets import mscs_review
from apps.targets.models import MostSignificantChangeStory

IA = EdifyRole.IMPACT_ASSESSMENT.value
CD = EdifyRole.COUNTRY_DIRECTOR.value
CCEO = EdifyRole.CCEO.value

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ia-school-evidence-tests",
    }
}


def _user(email, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].replace("-", " ").title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country=country)
    return User.objects.select_related("staff_profile").get(pk=user.pk)


def _learning(**overrides):
    data = {
        "assessment_type": "onetest",
        "assessed_on": "2026-02-10",
        "grade_level": "P6",
        "subject": "Literacy",
        "learners_tested": "30",
        "mean_score": "55",
        "max_score": "100",
        "learners_proficient": "12",
        "evidence_reference": "OneTest report 14",
    }
    data.update(overrides)
    return data


@override_settings(CACHES=LOCMEM)
class EvidenceFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ug = Region.objects.create(name="Evidence Central", country="Uganda")
        cls.ke = Region.objects.create(name="Evidence Coast", country="Kenya")
        cls.tz = Region.objects.create(name="Evidence Lake", country="Tanzania")
        cls.ug_district = District.objects.create(name="Evidence Wakiso", region=cls.ug)
        cls.ke_district = District.objects.create(
            name="Evidence Mombasa", region=cls.ke
        )
        cls.tz_district = District.objects.create(name="Evidence Mwanza", region=cls.tz)
        cls.school = cls._school("EV-UG-1", cls.ug, cls.ug_district)
        cls.school2 = cls._school("EV-UG-2", cls.ug, cls.ug_district)
        cls.ke_school = cls._school("EV-KE-1", cls.ke, cls.ke_district)
        cls.tz_school = cls._school("EV-TZ-1", cls.tz, cls.tz_district)

        cls.ia = _user("ev-ia1@t.org", IA)
        cls.ia2 = _user("ev-ia2@t.org", IA)
        cls.cd = _user("ev-cd@t.org", CD)
        cls.cceo = _user("ev-cceo@t.org", CCEO)
        cls.ke_ia = _user("ev-ke-ia@t.org", IA, country="Kenya")
        cls.tz_ia = _user("ev-tz-ia@t.org", IA, country="Tanzania")
        cls.tz_cd = _user("ev-tz-cd@t.org", CD, country="Tanzania")

    @classmethod
    def _school(cls, code, region, district):
        return School.objects.create(
            name=f"School {code}", school_id=code, region=region, district=district
        )

    def _onetest(self, *, status="evidence_uploaded", school=None, owner=None):
        owner = owner or self.cceo
        return Activity.objects.create(
            activity_type="school_visit",
            costing_profile_snapshot="ONETEST",
            status=status,
            school=school or self.school,
            fy="2026",
            planned_date=date(2026, 2, 9),
            actual_delivery_date=date(2026, 2, 10),
            responsible_staff_id=owner.staff_profile.id,
            delivery_type="staff",
        )


# ── Recording and independent verification ──────────────────────────────────


class VerificationTests(EvidenceFixture):
    def test_a_record_lands_pending_and_is_audited(self):
        row = ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"})
        self.assertEqual(row.verification_status, ev.PENDING)
        self.assertEqual(row.country, "Uganda")
        self.assertEqual(row.fy, "2026")
        self.assertEqual(row.recorded_by_user_id, str(self.ia.id))
        self.assertTrue(
            AuditLog.objects.filter(
                action="ia.school_evidence.learning_recorded", subject_id=row.id
            ).exists()
        )

    def test_the_recorder_never_confirms_their_own_record(self):
        row = ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"})
        with self.assertRaises(Forbidden):
            ev.decide(self.ia, ev.LEARNING, row.id, decision="confirm")
        row.refresh_from_db()
        self.assertEqual(row.verification_status, ev.PENDING)

    def test_a_second_ia_officer_confirms_and_the_cd_does_not_while_one_exists(self):
        row = ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"})
        with self.assertRaises(Forbidden):
            ev.decide(self.cd, ev.LEARNING, row.id, decision="confirm")
        ev.decide(self.ia2, ev.LEARNING, row.id, decision="confirm")
        row.refresh_from_db()
        self.assertEqual(row.verification_status, ev.CONFIRMED)
        self.assertEqual(row.verified_by_user_id, str(self.ia2.id))
        audit = AuditLog.objects.get(
            action="ia.school_evidence.learning_confirmed", subject_id=row.id
        )
        self.assertEqual(audit.payload["review_basis"], "peer_ia")

    def test_the_country_director_confirms_where_the_recorder_is_the_only_officer(self):
        row = ev.record(
            self.tz_ia,
            ev.DISCIPLESHIP,
            {
                "school_id": "EV-TZ-1",
                "observed_on": "2026-03-01",
                "discipleship_groups_active": "3",
            },
        )
        ev.decide(self.tz_cd, ev.DISCIPLESHIP, row.id, decision="confirm")
        row.refresh_from_db()
        self.assertEqual(row.verification_status, ev.CONFIRMED)
        self.assertEqual(
            AuditLog.objects.get(
                action="ia.school_evidence.discipleship_confirmed", subject_id=row.id
            ).payload["review_basis"],
            "cd_fallback",
        )

    def test_another_country_can_neither_see_nor_decide_the_record(self):
        row = ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"})
        self.assertFalse(ev.visible(self.ke_ia, ev.LEARNING).filter(id=row.id).exists())
        with self.assertRaises(NotFoundError):
            ev.decide(self.ke_ia, ev.LEARNING, row.id, decision="confirm")
        with self.assertRaises(BadRequest):
            ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-KE-1"})

    def test_only_impact_assessment_records_on_the_page(self):
        for principal in (self.cd, self.cceo):
            with self.subTest(role=principal.active_role), self.assertRaises(Forbidden):
                ev.record(
                    principal, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"}
                )

    def test_a_return_needs_a_reason_tells_the_recorder_and_correction_resubmits(self):
        row = ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"})
        with self.assertRaises(BadRequest):
            ev.decide(self.ia2, ev.LEARNING, row.id, decision="return")
        ev.decide(
            self.ia2, ev.LEARNING, row.id, decision="return", reason="Max score is 50"
        )
        row.refresh_from_db()
        self.assertEqual(row.verification_status, ev.RETURNED)
        notice = Notification.objects.get(
            recipient_id=self.ia.id, source_event_type=ev.EVENT_RETURNED
        )
        self.assertIn(f"open=learning-{row.id}", notice.target_route)
        with self.assertRaises(NotFoundError):
            ev.correct(self.ia2, ev.LEARNING, row.id, _learning(max_score="60"))
        ev.correct(self.ia, ev.LEARNING, row.id, _learning(max_score="60"))
        row.refresh_from_db()
        self.assertEqual(row.verification_status, ev.PENDING)
        self.assertEqual(row.return_reason, "")
        self.assertEqual(float(row.max_score), 60.0)
        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)

    def test_a_confirmed_record_cannot_be_corrected_or_withdrawn(self):
        row = ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"})
        ev.decide(self.ia2, ev.LEARNING, row.id, decision="confirm")
        with self.assertRaises(BadRequest):
            ev.correct(self.ia, ev.LEARNING, row.id, _learning())
        with self.assertRaises(BadRequest):
            ev.withdraw(self.ia, ev.LEARNING, row.id)

    def test_validation_refuses_impossible_results(self):
        cases = (
            ({"learners_proficient": "40"}, "exceed"),
            ({"mean_score": "120"}, "above the maximum"),
            ({"mean_score": "", "learners_proficient": ""}, "at least one"),
            ({"assessed_on": (date.today() + timedelta(days=3)).isoformat()}, "future"),
        )
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaisesMessage(BadRequest, message):
                    ev.record(
                        self.ia,
                        ev.LEARNING,
                        {**_learning(**overrides), "school_id": "EV-UG-1"},
                    )
        ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"})
        with self.assertRaisesMessage(BadRequest, "already has a result"):
            ev.record(
                self.ia,
                ev.LEARNING,
                {**_learning(subject="literacy"), "school_id": "EV-UG-1"},
            )

    def test_an_edtech_check_needs_a_confirmed_deployment_and_fits_its_quantity(self):
        deployment = ev.record(
            self.ia,
            ev.EDTECH,
            {
                "school_id": "EV-UG-1",
                "asset_type": "tablet",
                "quantity": "20",
                "deployed_on": "2026-01-05",
                "funding": "grant",
                "learners_with_access": "120",
            },
        )
        check = {
            "checked_on": "2026-04-01",
            "units_functional": "18",
            "learners_using": "90",
        }
        with self.assertRaisesMessage(BadRequest, "once it is confirmed"):
            ev.record_check(self.ia, deployment.id, check)
        ev.decide(self.ia2, ev.EDTECH, deployment.id, decision="confirm")
        with self.assertRaisesMessage(BadRequest, "cannot exceed"):
            ev.record_check(self.ia, deployment.id, {**check, "units_functional": "25"})
        row = ev.record_check(self.ia, deployment.id, check)
        self.assertEqual(row.country, "Uganda")
        self.assertEqual(row.verification_status, ev.PENDING)


# ── OneTest results from the visit ──────────────────────────────────────────


class OneTestTests(EvidenceFixture):
    def test_the_person_who_delivered_a_onetest_visit_records_its_results(self):
        activity = self._onetest()
        row = ev.record(self.cceo, ev.LEARNING, _learning(), source_activity=activity)
        self.assertEqual(row.school_id, self.school.id)
        self.assertEqual(row.source_activity_id, activity.id)
        self.assertEqual(row.verification_status, ev.PENDING)
        # Impact Assessment confirms field staff's results.
        ev.decide(self.ia, ev.LEARNING, row.id, decision="confirm")

    def test_not_before_delivery_not_for_another_visit_type_not_another_country(self):
        scheduled = self._onetest(status="scheduled")
        visit = self._onetest()
        visit.costing_profile_snapshot = "CORE_SCHOOL_VISIT"
        visit.save(update_fields=["costing_profile_snapshot"])
        ke_visit = self._onetest(school=self.ke_school)
        for principal, activity in (
            (self.cceo, scheduled),
            (self.cceo, visit),
            (self.ia, ke_visit),
        ):
            with self.subTest(activity=activity.status), self.assertRaises(Forbidden):
                ev.record(principal, ev.LEARNING, _learning(), source_activity=activity)

    def test_the_visit_page_offers_the_drawer_and_the_drawer_records(self):
        activity = self._onetest()
        self.client.force_login(self.cceo)
        page = self.client.get(f"/my-plan/{activity.id}?learning_results=1")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'hx-get="/my-plan/{activity.id}/learning-results"')
        self.assertContains(page, "data-onetest-autoload")
        drawer = self.client.get(f"/my-plan/{activity.id}/learning-results?completed=1")
        self.assertContains(drawer, "Record learning results")
        self.assertContains(drawer, "data-onetest-autoloaded")
        self.assertContains(drawer, 'value="2026-02-10"')
        response = self.client.post(
            f"/my-plan/{activity.id}/learning-results/save", _learning()
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            LearningAssessmentResult.objects.filter(source_activity=activity).exists()
        )

    def test_the_returned_result_notice_and_to_do_open_the_visit(self):
        activity = self._onetest()
        row = ev.record(self.cceo, ev.LEARNING, _learning(), source_activity=activity)
        ev.decide(self.ia, ev.LEARNING, row.id, decision="return", reason="Wrong class")
        notice = Notification.objects.get(
            recipient_id=self.cceo.id, source_event_type=ev.EVENT_RETURNED
        )
        self.assertEqual(
            notice.target_route, f"/my-plan/{activity.id}?learning_results=1"
        )
        from apps.impact.evidence_todos import evidence_todos

        rows = evidence_todos(self.cceo, CCEO, timezone.localdate())
        returned = [
            r for r in rows if r["id"].startswith("ia-school-evidence-returned")
        ]
        self.assertEqual(
            returned[0]["action_url"], f"/my-plan/{activity.id}?learning_results=1"
        )
        self.client.force_login(self.cceo)
        drawer = self.client.get(f"/my-plan/{activity.id}/learning-results")
        self.assertContains(drawer, "Correct a returned learning result")
        self.assertContains(drawer, "Wrong class")

    def test_a_delivered_onetest_without_results_is_a_to_do_until_recorded(self):
        from apps.impact.evidence_todos import evidence_todos

        activity = self._onetest()
        today = timezone.localdate()
        ids = [r["id"] for r in evidence_todos(self.cceo, CCEO, today)]
        self.assertIn(f"onetest-results-{activity.id}", ids)
        ev.record(self.cceo, ev.LEARNING, _learning(), source_activity=activity)
        ids = [r["id"] for r in evidence_todos(self.cceo, CCEO, today)]
        self.assertNotIn(f"onetest-results-{activity.id}", ids)


# ── Learning comparisons and CSV ────────────────────────────────────────────


class LearningComparisonTests(EvidenceFixture):
    def _confirmed(self, school, fy_day, **overrides):
        row = ev.record(
            self.ia,
            ev.LEARNING,
            {
                **_learning(assessed_on=fy_day, **overrides),
                "school_id": school.school_id,
            },
        )
        ev.decide(self.ia2, ev.LEARNING, row.id, decision="confirm")
        return row

    def test_the_same_class_and_subject_compare_year_on_year_and_small_classes_withhold(
        self,
    ):
        self._confirmed(self.school, "2025-03-01", mean_score="40")
        self._confirmed(self.school, "2026-03-01", mean_score="55")
        self._confirmed(
            self.school2, "2025-03-01", learners_tested="6", learners_proficient=""
        )
        self._confirmed(self.school2, "2026-03-01", learners_tested="30")
        # Pending evidence never counts.
        ev.record(
            self.ia,
            ev.LEARNING,
            {
                **_learning(assessed_on="2025-03-02", grade_level="P7"),
                "school_id": "EV-UG-1",
            },
        )
        rows = {c["school_id"]: c for c in ev.learning_summary(self.ia, "2026")}
        self.assertEqual(rows[self.school.id]["state"], "compared")
        self.assertEqual(rows[self.school.id]["change"], 15.0)
        self.assertEqual(rows[self.school.id]["classification"], "improved")
        self.assertEqual(rows[self.school2.id]["state"], "withheld")
        summary = ev.outcome_evidence(self.ia, "2026")["learning"]
        self.assertEqual(summary["comparisons"], 1)
        self.assertEqual(summary["improved"], 1)
        self.assertEqual(summary["withheld"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(
            ev.outcome_evidence(self.ke_ia, "2026")["learning"]["comparisons"], 0
        )

    def test_a_csv_records_every_row_or_none(self):
        header = ",".join(ev.LEARNING_CSV_COLUMNS)
        good = "EV-UG-1,OneTest,2026-02-10,P5,Numeracy,31,48,100,10,,"
        bad = "EV-KE-1,onetest,2026-02-10,P5,Numeracy,31,48,100,10,,"

        def upload(*lines):
            content = "\n".join((header, *lines)).encode()
            return ev.upload_learning_csv(
                self.ia, SimpleUploadedFile("results.csv", content, "text/csv")
            )

        result = upload(good, bad)
        self.assertEqual(result["created"], 0)
        self.assertIn("Row 3", result["errors"][0])
        self.assertFalse(LearningAssessmentResult.objects.exists())
        result = upload(good, good.replace("P5", "P6"))
        self.assertEqual(result["created"], 2)
        self.assertEqual(
            LearningAssessmentResult.objects.filter(
                verification_status="pending"
            ).count(),
            2,
        )
        self.assertIn("already has", upload(good)["errors"][0])
        with self.assertRaises(Forbidden):
            ev.upload_learning_csv(
                self.cceo, SimpleUploadedFile("r.csv", io.BytesIO(b"x").read())
            )


# ── Most Significant Change review ──────────────────────────────────────────


class StoryReviewTests(EvidenceFixture):
    def _story(self, author, school=None, **kw):
        return MostSignificantChangeStory.objects.create(
            user_id=author.id,
            school=school or self.school,
            title=kw.pop("title", "Devotions restarted"),
            narrative="The staff restarted morning devotions.",
            story_date=kw.pop("story_date", date(2026, 3, 1)),
            status=kw.pop("status", "submitted"),
            **kw,
        )

    def test_the_author_never_reviews_and_approval_needs_a_tag(self):
        story = self._story(self.ia)
        with self.assertRaises(Forbidden):
            mscs_review.decide(
                self.ia,
                story.id,
                decision="approve",
                intervention="christlike_behaviour",
            )
        with self.assertRaisesMessage(BadRequest, "Tag the outcome"):
            mscs_review.decide(self.ia2, story.id, decision="approve")
        with self.assertRaisesMessage(BadRequest, "needs a reason"):
            mscs_review.decide(self.ia2, story.id, decision="return")
        mscs_review.decide(
            self.ia2, story.id, decision="approve", intervention="christlike_behaviour"
        )
        story.refresh_from_db()
        self.assertEqual(story.status, "approved")
        self.assertEqual(story.reviewed_by, str(self.ia2.id))
        self.assertEqual(story.country, "Uganda")
        self.assertTrue(
            AuditLog.objects.filter(
                action="mscs.story_approved", subject_id=story.id
            ).exists()
        )

    def test_another_country_cannot_see_or_review_the_story(self):
        story = self._story(self.cceo)
        self.assertFalse(
            mscs_review.visible_stories(self.ke_ia).filter(id=story.id).exists()
        )
        with self.assertRaises(NotFoundError):
            mscs_review.decide(
                self.ke_ia, story.id, decision="reject", note="Not a change"
            )

    def test_an_approved_spiritual_story_counts_as_discipleship_evidence(self):
        area = OutcomeArea.objects.create(
            code="spiritual-formation",
            name="Spiritual formation",
            definition="Growth in Christ-like character.",
            status=DefinitionStatus.APPROVED,
            author_id=self.ia.id,
        )
        OutcomeAreaDomain.objects.create(
            area=area, intervention="exposure_to_word_of_god"
        )
        story = self._story(self.cceo)
        other = self._story(self.cceo, title="Fees collected")
        mscs_review.decide(
            self.ia, story.id, decision="approve", outcome_area="spiritual-formation"
        )
        mscs_review.decide(
            self.ia, other.id, decision="approve", intervention="financial_health"
        )
        evidence = ev.outcome_evidence(self.ia, "2026")["discipleship"]
        self.assertEqual(evidence["stories_approved"], 1)
        self.assertEqual(evidence["stories_waiting"], 0)

    def test_the_stories_page_reviews_and_the_cd_reads_but_cannot_decide_staff_stories(
        self,
    ):
        story = self._story(self.cceo)
        self.client.force_login(self.ia)
        page = self.client.get("/ia/stories/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Devotions restarted")
        drawer = self.client.get(f"/ia/stories/{story.id}/")
        self.assertContains(drawer, "Review a change story")
        response = self.client.post(
            f"/ia/stories/{story.id}/decide",
            {"decision": "return", "note": "Add what changed for learners"},
        )
        self.assertEqual(response.status_code, 302)
        story.refresh_from_db()
        self.assertEqual(story.status, "returned")
        # The Country Director opens the page (fallback reviewer for a lone IA
        # officer's stories) but a CCEO's story is Impact Assessment's to decide.
        self.client.force_login(self.cd)
        self.assertEqual(self.client.get("/ia/stories/").status_code, 200)
        other = self._story(self.cceo, title="Reading club started")
        self.client.post(
            f"/ia/stories/{other.id}/decide",
            {"decision": "reject", "note": "Not a change"},
        )
        other.refresh_from_db()
        self.assertEqual(other.status, "submitted")
        self.assertEqual(
            NotificationLinkResolver.resolve(
                "mscs.story_reviewed", "MostSignificantChangeStory", story.id, "CCEO"
            )[0],
            "/my-targets",
        )


# ── The School Evidence page ────────────────────────────────────────────────


class SchoolEvidencePageTests(EvidenceFixture):
    def test_each_tab_renders_its_register_and_filters(self):
        ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"})
        self.client.force_login(self.ia2)
        for tab, text in (
            ("learning", "Learning results"),
            ("discipleship", "Discipleship records"),
            ("edtech", "Deployments"),
        ):
            with self.subTest(tab=tab):
                response = self.client.get("/ia/school-evidence/", {"tab": tab})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, text)
                self.assertContains(response, 'name="status"')
        response = self.client.get("/ia/school-evidence/", {"tab": "learning"})
        self.assertContains(response, "School EV-UG-1")
        self.assertContains(response, ">Verify<")
        self.assertContains(response, 'name="subject"')

    def test_the_drawer_offers_verification_only_to_someone_else(self):
        row = ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"})
        self.client.force_login(self.ia)
        own = self.client.get(f"/ia/school-evidence/learning/{row.id}/")
        self.assertNotContains(own, "Verify learning result")
        self.assertContains(own, "Correct learning result")
        refused = self.client.post(
            f"/ia/school-evidence/learning/{row.id}/decide", {"decision": "confirm"}
        )
        self.assertEqual(refused.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.verification_status, ev.PENDING)
        self.client.force_login(self.ia2)
        drawer = self.client.get(f"/ia/school-evidence/learning/{row.id}/")
        self.assertContains(drawer, "Verify learning result")
        self.client.post(
            f"/ia/school-evidence/learning/{row.id}/decide", {"decision": "confirm"}
        )
        row.refresh_from_db()
        self.assertEqual(row.verification_status, ev.CONFIRMED)
        self.client.force_login(self.ke_ia)
        self.assertContains(
            self.client.get(f"/ia/school-evidence/learning/{row.id}/"),
            "not in your country",
        )

    def test_field_staff_cannot_open_the_page(self):
        self.client.force_login(self.cceo)
        self.assertEqual(self.client.get("/ia/school-evidence/").status_code, 302)
        self.assertIn(
            self.client.post(
                "/ia/school-evidence/learning/save", _learning()
            ).status_code,
            (302, 403),
        )
        self.assertFalse(LearningAssessmentResult.objects.exists())

    def test_the_country_director_reads_and_cannot_record(self):
        self.client.force_login(self.cd)
        self.assertEqual(self.client.get("/ia/school-evidence/").status_code, 200)
        self.client.post(
            "/ia/school-evidence/learning/save", {**_learning(), "school_id": "EV-UG-1"}
        )
        self.assertFalse(LearningAssessmentResult.objects.exists())

    def test_the_template_csv_downloads(self):
        self.client.force_login(self.ia)
        response = self.client.get("/ia/school-evidence/learning/template.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn(",".join(ev.LEARNING_CSV_COLUMNS), response.content.decode())


# ── Outcomes view, school profile, Declining Schools, SSA Performance ───────


class OutcomesAndProgressTests(EvidenceFixture):
    def _ssa(self, school, on, scores, *, status="confirmed", fy):
        record = SsaRecord.objects.create(
            school=school,
            fy=fy,
            quarter="Q2",
            average_score=sum(scores.values()) / len(scores),
            verification_status=status,
            date_of_ssa=timezone.make_aware(
                timezone.datetime(on.year, on.month, on.day)
            ),
            uploaded_by="t",
        )
        for code, score in scores.items():
            SsaScore.objects.create(ssa_record=record, intervention=code, score=score)
        return record

    def test_nothing_measured_reads_not_measured_never_zero(self):
        from apps.analytics.ia_workflow import portfolio_change, portfolio_tiles

        tiles = {
            t["label"]: t for t in portfolio_tiles(portfolio_change(self.ia, fy="2026"))
        }
        improved = tiles["Schools Improved (Share of Measured)"]
        self.assertEqual(improved["display_value"], "Not measured")
        self.assertFalse(improved["is_measured"])
        self.client.force_login(self.ia)
        response = self.client.get("/ia/dashboard/", {"view": "outcomes"})
        self.assertContains(response, "School change across the portfolio")
        self.assertContains(response, "Not measured")

    def test_portfolio_change_pairs_confirmed_ssas_in_scope_through_the_rule(self):
        from apps.analytics.ia_workflow import portfolio_change

        cb, wog = "christlike_behaviour", "exposure_to_word_of_god"
        self._ssa(self.school, date(2025, 2, 1), {cb: 4, wog: 5}, fy="2025")
        self._ssa(self.school, date(2026, 2, 1), {cb: 6, wog: 7}, fy="2026")
        self._ssa(self.school2, date(2025, 2, 1), {cb: 6, wog: 6}, fy="2025")
        self._ssa(self.school2, date(2026, 2, 1), {cb: 5, wog: 5}, fy="2026")
        # A newer unconfirmed record changes nothing; another country is out.
        self._ssa(
            self.school2, date(2026, 3, 1), {cb: 9, wog: 9}, status="pending", fy="2026"
        )
        self._ssa(self.ke_school, date(2025, 2, 1), {cb: 2, wog: 2}, fy="2025")
        self._ssa(self.ke_school, date(2026, 2, 1), {cb: 9, wog: 9}, fy="2026")
        result = portfolio_change(self.ia, fy="2026")
        self.assertEqual(result["measured"], 2)
        self.assertEqual(result["improved"], 1)
        self.assertEqual(result["declined"], 1)
        self.assertEqual(result["improved_pct"], 50)
        self.assertEqual(result["median_interval_days"], 365)
        domain_rows = {r["name"]: r for r in result["rows"] if not r["is_area"]}
        self.assertEqual(domain_rows["Christlike Behaviour"]["n"], 2)
        # Below the evidence floor the median change is withheld, not shown.
        self.assertTrue(domain_rows["Christlike Behaviour"]["withheld"])
        self.assertIsNone(domain_rows["Christlike Behaviour"]["median_change"])

    def test_the_collection_view_renders_the_worklist_with_its_actions(self):
        self.client.force_login(self.ia)
        response = self.client.get("/ia/dashboard/", {"view": "collection"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-ia-collection-worklist")
        self.assertContains(response, "School EV-UG-1")
        self.assertContains(response, "Add SSA")
        self.assertContains(response, "Assessment collection")
        self.assertNotContains(response, "School EV-KE-1")

    def test_the_school_profile_heads_with_the_confirmed_ssa_and_counts_pairs(self):
        cb = "christlike_behaviour"
        self._ssa(self.school, date(2025, 2, 1), {cb: 4}, fy="2025")
        confirmed = self._ssa(self.school, date(2026, 2, 1), {cb: 6}, fy="2026")
        self._ssa(self.school, date(2026, 4, 1), {cb: 9}, status="pending", fy="2026")
        from apps.analytics.ia_workflow import school_progress

        progress = school_progress(self.school)
        self.assertEqual(progress["latest"].id, confirmed.id)
        self.assertEqual(len(progress["newer_unconfirmed"]), 1)
        self.assertEqual(len(progress["pairs"]), 1)
        self.assertEqual(progress["pairs"][0]["classification"], "improved")
        self.assertEqual(progress["improved_pairs"], 1)
        self.client.force_login(self.ia)
        response = self.client.get(f"/schools/{self.school.school_id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="ssa-timeline"')
        self.assertContains(response, "Current confirmed SSA")
        self.assertContains(response, "not confirmed yet and is not counted")
        self.assertContains(response, "SSA change between confirmed assessments")

    def test_declining_schools_survives_a_bad_fy_and_names_interventions(self):
        cb = "christlike_behaviour"
        self._ssa(self.school, date(2025, 2, 1), {cb: 8}, fy="2025")
        self._ssa(self.school, date(2026, 2, 1), {cb: 4}, fy="2026")
        self.client.force_login(self.cd)
        bad = self.client.get("/declining-schools", {"fy": "abc"}, follow=True)
        self.assertEqual(bad.status_code, 200)
        self.assertIn("fy=", bad.redirect_chain[0][0])
        response = self.client.get("/declining-schools", {"fy": "2026"})
        self.assertContains(response, "Christlike Behaviour")
        self.assertNotContains(response, "Christlike_Behaviour")
        self.assertContains(response, f'href="/schools/{self.school.id}"')

    def test_ssa_performance_draws_no_bar_and_no_success_for_missing_data(self):
        from apps.analytics.ssa_performance_service import build_dashboard

        data = build_dashboard(self.ia, {"fy": "2026"})
        self.assertTrue(all(i["width"] is None for i in data["interventions"]))
        momentum = next(
            i for i in data["insights"] if i["title"] == "Performance momentum"
        )
        self.assertEqual(momentum["tone"], "info")


# ── Notifications and To-Dos ────────────────────────────────────────────────


class NoticeAndToDoTests(EvidenceFixture):
    def test_the_resolver_opens_the_record_or_the_visit(self):
        resolve = NotificationLinkResolver.resolve
        self.assertEqual(
            resolve(ev.EVENT_RETURNED, "EdTechCheck", "c1", "ImpactAssessment")[0],
            "/ia/school-evidence/?tab=edtech&status=returned&open=check-c1",
        )
        self.assertEqual(
            resolve(ev.EVENT_RETURNED, "OneTestActivity", "a1", "CCEO")[0],
            "/my-plan/a1?learning_results=1",
        )

    def test_the_verifier_sees_a_row_and_the_recorder_does_not(self):
        from apps.impact.evidence_todos import evidence_todos

        ev.record(self.ia, ev.LEARNING, {**_learning(), "school_id": "EV-UG-1"})
        today = timezone.localdate()
        mine = [r["id"] for r in evidence_todos(self.ia, IA, today)]
        self.assertNotIn("ia-school-evidence-verify-learning", mine)
        theirs = [r for r in evidence_todos(self.ia2, IA, today)]
        self.assertIn("ia-school-evidence-verify-learning", [r["id"] for r in theirs])
        self.assertEqual(evidence_todos(self.cd, CD, today), [])
        self.assertEqual(evidence_todos(self.ke_ia, IA, today), [])


@override_settings(CACHES=LOCMEM)
class QueryBudgetTests(EvidenceFixture):
    """Ceilings, never targets; none grows with the data."""

    def _grow(self, n):
        for i in range(n):
            school = self._school(f"EV-G-{self._grown + i}", self.ug, self.ug_district)
            row = ev.record(
                self.ia,
                ev.LEARNING,
                {**_learning(), "school_id": school.school_id},
            )
            ev.decide(self.ia2, ev.LEARNING, row.id, decision="confirm")
            DiscipleshipIndicatorRecord.objects.create(
                school=school,
                country="Uganda",
                fy="2026",
                observed_on=date(2026, 2, 1),
                recorded_by_user_id=self.ia.id,
                verification_status="confirmed",
                discipleship_groups_active=2,
            )
            deployment = EdTechDeployment.objects.create(
                school=school,
                country="Uganda",
                fy="2026",
                asset_type="tablet",
                quantity=10,
                deployed_on=date(2026, 1, 1),
                funding="grant",
                recorded_by_user_id=self.ia.id,
                verification_status="confirmed",
            )
            EdTechCheck.objects.create(
                deployment=deployment,
                school=school,
                country="Uganda",
                fy="2026",
                checked_on=date(2026, 3, 1),
                units_functional=8,
                recorded_by_user_id=self.ia.id,
                verification_status="pending",
            )
            MostSignificantChangeStory.objects.create(
                user_id=self.cceo.id,
                school=school,
                title=f"Story {i}",
                narrative="n",
                story_date=date(2026, 2, 1),
                status="submitted",
            )
        self._grown += n

    def _count(self, fn):
        with CaptureQueriesContext(connection) as ctx:
            fn()
        return len(ctx.captured_queries)

    def test_pages_and_builders_stay_flat_as_records_grow(self):
        from apps.analytics.ia_workflow import outcome_progress
        from apps.impact.evidence_todos import evidence_todos

        self._grown = 0
        self.client.force_login(self.ia2)
        today = timezone.localdate()
        probes = {
            "evidence_learning": lambda: self.client.get(
                "/ia/school-evidence/", {"tab": "learning"}
            ),
            "evidence_discipleship": lambda: self.client.get(
                "/ia/school-evidence/", {"tab": "discipleship"}
            ),
            "evidence_edtech": lambda: self.client.get(
                "/ia/school-evidence/", {"tab": "edtech"}
            ),
            "stories": lambda: self.client.get("/ia/stories/"),
            "outcome_progress": lambda: outcome_progress(self.ia2, fy="2026"),
            "todos": lambda: evidence_todos(self.ia2, IA, today),
        }
        self._grow(2)
        for probe in probes.values():
            probe()  # warm per-process caches
        small = {key: self._count(probe) for key, probe in probes.items()}
        self._grow(12)
        large = {key: self._count(probe) for key, probe in probes.items()}
        budgets = {
            "evidence_learning": 40,
            "evidence_discipleship": 40,
            "evidence_edtech": 40,
            "stories": 30,
            # Called outside a request, so the reader's scope is resolved per
            # call rather than once per request: measured at 14.
            "outcome_progress": 16,
            "todos": 10,
        }
        for key, budget in budgets.items():
            with self.subTest(probe=key):
                self.assertLessEqual(large[key], small[key] + 1, (small, large))
                self.assertLessEqual(large[key], budget, large)
