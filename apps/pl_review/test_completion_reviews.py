"""Completion Reviews — the Programme Lead confirms the team's completed work.

Programme Lead alignment, 2026-09-13. Four things are pinned here:

  1. One review rule. The page's permission check and the review service used
     to answer "may this lead review this completion?" differently — the page
     read one id space and no monitor — so a completion filed under a CCEO's
     User id was listed in the queue and refused by its own Approve button.
  2. A cluster session run by a supervised officer is readable by the lead,
     and by nobody the rule did not already reach.
  3. The queue is a register read in bulk: its cost does not grow with the
     number of completions waiting.
  4. A return carries a reason, refused visibly when it does not.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.messages import get_messages
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityCompletionVerification
from apps.activities.services import _serialize
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest
from apps.core.permissions import RolePermissionService
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.pl_review import services
from apps.schools.models import School

QUEUE_URL = "/pl/review-queue"
LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "completion-reviews",
    }
}


def _staff(email, name, role):
    user = User.objects.create(
        email=email,
        name=name,
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
    )
    return user, StaffProfile.objects.create(user=user, title=name, country="Uganda")


class ReviewFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Review Region")
        cls.district = District.objects.create(
            name="Review District", region=cls.region
        )

        cls.pl_user, cls.pl = _staff(
            "rev-pl@t.test", "Lead Lydia", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.james_user, cls.james = _staff("rev-james@t.test", "James", EdifyRole.CCEO)
        cls.mary_user, cls.mary = _staff("rev-mary@t.test", "Mary", EdifyRole.CCEO)
        cls.rival_pl_user, cls.rival_pl = _staff(
            "rev-rival-pl@t.test", "Rival Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.rival_user, cls.rival = _staff(
            "rev-rival@t.test", "Rival CCEO", EdifyRole.CCEO
        )
        cls.cd_user, cls.cd = _staff(
            "rev-cd@t.test", "Director", EdifyRole.COUNTRY_DIRECTOR
        )
        cls.admin_user, _ = _staff("rev-admin@t.test", "Admin", EdifyRole.ADMIN)
        for officer in (cls.james, cls.mary):
            StaffSupervisorAssignment.objects.create(
                supervisee=officer, supervisor=cls.pl
            )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.rival, supervisor=cls.rival_pl
        )

        cls.school = cls._school("REV-1", "Alpha Primary")
        cls.mary_school = cls._school("REV-2", "Beta Primary")
        cls.rival_school = cls._school("REV-3", "Rival Primary")
        StaffSchoolAssignment.objects.create(staff=cls.james, school_id=cls.school.id)
        StaffSchoolAssignment.objects.create(
            staff=cls.mary, school_id=cls.mary_school.id
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.rival, school_id=cls.rival_school.id
        )
        cls.cluster = Cluster.objects.create(
            name="Mukono North",
            region=cls.region,
            district=cls.district,
            responsible_staff_id=cls.james.id,
        )

    @classmethod
    def _school(cls, ref, name):
        return School.objects.create(
            school_id=ref, name=name, region=cls.region, district=cls.district
        )

    def _completion(self, owner_id, *, school=None, cluster=None, **extra):
        values = {
            "activity_type": "school_visit",
            "status": "submitted_to_pl",
            "fy": "2026",
            "quarter": "Q4",
            "planned_date": date.today() - timedelta(days=3),
            "responsible_staff_id": owner_id,
            "school": school if school is not None or cluster else self.school,
            "cluster": cluster,
        }
        values.update(extra)
        return Activity.objects.create(**values)

    def as_user(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client


class OneReviewRuleTest(ReviewFixture):
    def test_the_supervising_lead_may_review_in_either_id_space(self):
        by_profile = self._completion(self.james.id)
        by_user = self._completion(self.james_user.id)

        self.assertTrue(services.may_review(self.pl_user, by_profile))
        self.assertTrue(services.may_review(self.pl_user, by_user))

    def test_partner_work_is_reviewed_through_its_monitor(self):
        partner_work = self._completion(
            None, delivery_type="partner", monitored_by_staff_id=self.james.id
        )
        self.assertTrue(services.may_review(self.pl_user, partner_work))

    def test_own_work_and_another_team_are_refused(self):
        own = self._completion(self.pl.id)
        rival = self._completion(self.rival.id, school=self.rival_school)

        self.assertFalse(services.may_review(self.pl_user, own))
        self.assertFalse(services.may_review(self.pl_user, rival))
        self.assertFalse(services.may_review(self.james_user, own))

    def test_the_page_permission_asks_the_same_rule(self):
        """The case that used to disagree: filed under the CCEO's User id."""
        by_user = self._completion(self.james_user.id)
        rival = self._completion(self.rival.id, school=self.rival_school)

        self.assertTrue(
            RolePermissionService.can_review_activity(self.pl_user, by_user)
        )
        self.assertFalse(RolePermissionService.can_review_activity(self.pl_user, rival))
        self.assertIn(by_user.id, {row["id"] for row in services.queue(self.pl_user)})

    def test_a_user_id_filed_completion_is_approvable_from_the_page(self):
        by_user = self._completion(self.james_user.id)

        response = self.as_user(self.pl_user).post(f"{QUEUE_URL}/{by_user.id}/confirm")

        self.assertEqual(response.status_code, 302)
        by_user.refresh_from_db()
        self.assertEqual(by_user.status, "awaiting_ia_verification")


class QueueRowsNameTheWorkTest(ReviewFixture):
    def test_queue_rows_carry_the_label_the_cluster_and_the_officer(self):
        session = self._completion(
            self.james.id, cluster=self.cluster, activity_type="cluster_training"
        )

        row = next(r for r in services.queue(self.pl_user) if r["id"] == session.id)

        self.assertEqual(row["activityTypeLabel"], session.get_activity_type_display())
        self.assertEqual(row["clusterName"], "Mukono North")
        self.assertEqual(row["ownerName"], "James")

    def test_the_serializer_never_fetches_a_cluster_it_was_not_given(self):
        session = self._completion(
            self.james.id, cluster=self.cluster, activity_type="cluster_training"
        )
        bare = Activity.objects.get(id=session.id)
        joined = Activity.objects.select_related("cluster").get(id=session.id)

        with self.assertNumQueries(0):
            self.assertIsNone(_serialize(bare)["clusterName"])
        with self.assertNumQueries(0):
            self.assertEqual(_serialize(joined)["clusterName"], "Mukono North")


class ReturnNeedsAReasonTest(ReviewFixture):
    def test_the_service_refuses_a_blank_reason(self):
        work = self._completion(self.james.id)

        with self.assertRaises(BadRequest):
            services.return_activity(work.id, {"reason": "   "}, self.pl_user)

        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")

    def test_the_page_says_why_rather_than_returning_silently(self):
        work = self._completion(self.james.id)

        response = self.as_user(self.pl_user).post(
            f"{QUEUE_URL}/{work.id}/return", {"reason": ""}
        )

        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")
        self.assertIn(
            "Say what needs correcting",
            " ".join(str(m) for m in get_messages(response.wsgi_request)),
        )

    def test_a_return_with_a_reason_reaches_the_officer(self):
        work = self._completion(self.james.id)

        self.as_user(self.pl_user).post(
            f"{QUEUE_URL}/{work.id}/return", {"reason": "Attendance sheet is blank"}
        )

        work.refresh_from_db()
        self.assertEqual(work.status, "returned_by_pl")
        self.assertEqual(work.pl_review_note, "Attendance sheet is blank")


class CompletionReviewsPageTest(ReviewFixture):
    def test_the_lead_sees_a_register_of_their_teams_completions_only(self):
        session = self._completion(
            self.james.id,
            cluster=self.cluster,
            activity_type="cluster_training",
            teachers_attended=12,
            leaders_attended=3,
            salesforce_activity_id="TS-1001",
            focus_intervention="leadership",
        )
        mine = self._completion(self.pl.id)
        rival = self._completion(self.rival.id, school=self.rival_school)

        response = self.as_user(self.pl_user).get(QUEUE_URL)

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for heading in (
            "Officer",
            "Activity",
            "School or cluster",
            "Date",
            "Intervention",
            "Attendance",
            "Evidence",
            "Salesforce ID",
            "Days waiting",
        ):
            with self.subTest(heading=heading):
                self.assertIn(f">{heading}</th>", body)
        self.assertIn(f'data-review-row="{session.id}"', body)
        self.assertNotIn(f'data-review-row="{mine.id}"', body)
        self.assertNotIn(f'data-review-row="{rival.id}"', body)
        self.assertIn("Mukono North", body)
        self.assertIn("12 teachers · 3 leaders", body)
        self.assertIn("TS-1001", body)
        self.assertIn(">LSHIP<", body)
        # The row decides the review and nothing else about the officer's work.
        self.assertNotIn("/reschedule", body)
        self.assertNotIn("complete-drawer", body)

    def test_the_longest_waiting_completion_comes_first(self):
        recent = self._completion(self.james.id)
        old = self._completion(self.mary.id, school=self.mary_school)
        for activity, days in ((recent, 1), (old, 9)):
            ActivityCompletionVerification.objects.create(
                activity=activity, salesforce_id="", entered_by=self.james_user.id
            )
            ActivityCompletionVerification.objects.filter(activity=activity).update(
                updated_at=timezone.now() - timedelta(days=days)
            )

        rows = services.review_register(self.pl_user)["rows"]

        self.assertEqual([r["id"] for r in rows], [old.id, recent.id])
        self.assertEqual(rows[0]["days_waiting"], 9)
        self.assertEqual(rows[0]["wait_tone"], "danger")
        self.assertEqual(rows[1]["wait_tone"], "")

    def test_the_officer_filter_appears_only_when_it_narrows(self):
        self._completion(self.james.id)
        client = self.as_user(self.pl_user)
        self.assertNotContains(client.get(QUEUE_URL), 'name="cceo"')

        marys = self._completion(self.mary.id, school=self.mary_school)
        page = client.get(QUEUE_URL)
        self.assertContains(page, 'name="cceo"')

        narrowed = client.get(QUEUE_URL, {"cceo": self.mary.id})
        self.assertEqual([r["id"] for r in narrowed.context["rows"]], [marys.id])
        # The User id reaches the same officer.
        by_user = client.get(QUEUE_URL, {"cceo": self.mary_user.id})
        self.assertEqual([r["id"] for r in by_user.context["rows"]], [marys.id])

    def test_roles_without_the_queue_are_refused(self):
        for user in (self.james_user, self.cd_user, self.rival_user):
            with self.subTest(role=user.active_role):
                response = self.as_user(user).get(QUEUE_URL)
                self.assertNotEqual(response.status_code, 200)

    def test_admin_may_open_the_queue(self):
        self.assertEqual(self.as_user(self.admin_user).get(QUEUE_URL).status_code, 200)

    def test_the_open_drawer_reads_the_completion_and_offers_approve(self):
        work = self._completion(self.james.id, salesforce_activity_id="SV-77")
        EvidenceRecord.objects.create(
            activity=work,
            kind="photo",
            uri="x.jpg",
            original_name="visit-photo.jpg",
            uploaded_by=self.james_user.id,
        )

        response = self.as_user(self.pl_user).get(
            f"{QUEUE_URL}/{work.id}/drawer", headers={"HX-Request": "true"}
        )

        self.assertContains(response, "Approve completion")
        self.assertContains(response, f'action="{QUEUE_URL}/{work.id}/confirm"')
        self.assertContains(response, "SV-77")
        self.assertContains(response, "visit-photo.jpg")

    def test_a_drawer_for_another_team_refuses_and_offers_nothing(self):
        rival = self._completion(self.rival.id, school=self.rival_school)
        client = self.as_user(self.pl_user)

        for suffix in ("drawer", "return-drawer"):
            with self.subTest(drawer=suffix):
                response = client.get(
                    f"{QUEUE_URL}/{rival.id}/{suffix}", headers={"HX-Request": "true"}
                )
                self.assertContains(response, "another Program Lead")
                self.assertNotContains(response, "<form")

    def test_the_return_drawer_requires_a_reason(self):
        work = self._completion(self.james.id)

        response = self.as_user(self.pl_user).get(
            f"{QUEUE_URL}/{work.id}/return-drawer", headers={"HX-Request": "true"}
        )

        self.assertContains(response, f'action="{QUEUE_URL}/{work.id}/return"')
        self.assertRegex(
            response.content.decode(), r'<textarea[^>]*name="reason"[^>]*required'
        )

    def test_another_teams_completion_cannot_be_decided_by_id(self):
        rival = self._completion(self.rival.id, school=self.rival_school)
        client = self.as_user(self.pl_user)

        for action in ("confirm", "return"):
            with self.subTest(action=action):
                response = client.post(
                    f"{QUEUE_URL}/{rival.id}/{action}", {"reason": "Not mine"}
                )
                self.assertEqual(response.status_code, 403)
        rival.refresh_from_db()
        self.assertEqual(rival.status, "submitted_to_pl")

    def test_open_lands_on_the_named_completion_and_only_ones_own(self):
        work = self._completion(self.james.id)
        rival = self._completion(self.rival.id, school=self.rival_school)
        client = self.as_user(self.pl_user)

        self.assertContains(
            client.get(QUEUE_URL, {"open": work.id}),
            f'hx-get="{QUEUE_URL}/{work.id}/drawer" hx-trigger="load"',
        )
        self.assertNotContains(
            client.get(QUEUE_URL, {"open": rival.id}), "data-review-autoload"
        )


class SupervisedClusterWorkIsReadableTest(ReviewFixture):
    def test_the_lead_reads_a_supervised_officers_cluster_session(self):
        session = self._completion(
            self.james.id, cluster=self.cluster, activity_type="cluster_training"
        )
        by_user = self._completion(
            self.james_user.id, cluster=self.cluster, activity_type="cluster_meeting"
        )

        self.assertTrue(RolePermissionService.can_view_record(self.pl_user, session))
        self.assertTrue(RolePermissionService.can_view_record(self.pl_user, by_user))

    def test_nobody_the_rule_did_not_already_reach_gains_it(self):
        session = self._completion(
            self.james.id, cluster=self.cluster, activity_type="cluster_training"
        )

        # A colleague CCEO supervises nobody; another team's lead supervises
        # someone else.
        self.assertFalse(RolePermissionService.can_view_record(self.mary_user, session))
        self.assertFalse(
            RolePermissionService.can_view_record(self.rival_pl_user, session)
        )
        # The officer's own read is unchanged.
        self.assertTrue(RolePermissionService.can_view_record(self.james_user, session))

    def test_a_supervisees_session_in_a_cluster_outside_scope_stays_closed(self):
        elsewhere = District.objects.create(name="Far District", region=self.region)
        foreign = Cluster.objects.create(
            name="Far Cluster",
            region=self.region,
            district=elsewhere,
            responsible_staff_id=self.rival.id,
        )
        session = self._completion(
            self.james.id, cluster=foreign, activity_type="cluster_training"
        )

        self.assertFalse(RolePermissionService.can_view_record(self.pl_user, session))

    def test_reading_is_not_acting(self):
        session = self._completion(
            self.james.id, cluster=self.cluster, activity_type="cluster_training"
        )
        self.assertFalse(
            RolePermissionService.can_upload_evidence(self.pl_user, session)
        )
        self.assertFalse(
            RolePermissionService.can_enter_activity_sf_id(self.pl_user, session)
        )


@override_settings(CACHES=LOCMEM)
class CompletionReviewsQueryBudgetTest(ReviewFixture):
    """The register is read in bulk: more completions, same query count.

    Measured through the page so the shell's own reads are part of the fixed
    cost, and against a cache this process owns (dev tests share Redis).
    """

    CEILING = 60

    def _add(self, count):
        for index in range(count):
            owner = (self.james, self.mary)[index % 2]
            school = self.school if owner is self.james else self.mary_school
            work = self._completion(
                owner.id, school=school, teachers_attended=index + 1
            )
            EvidenceRecord.objects.create(
                activity=work,
                kind="photo",
                uri=f"{work.id}.jpg",
                original_name=f"{index}.jpg",
                uploaded_by=owner.user_id,
            )
            ActivityCompletionVerification.objects.create(
                activity=work, salesforce_id="", entered_by=owner.user_id
            )

    def _queries(self):
        client = self.as_user(self.pl_user)
        client.get(QUEUE_URL)  # warm per-process caches
        with CaptureQueriesContext(connection) as captured:
            response = client.get(QUEUE_URL)
        self.assertEqual(response.status_code, 200)
        return len(captured.captured_queries), len(response.context["rows"])

    def test_the_register_costs_the_same_for_two_completions_or_twelve(self):
        self._add(2)
        few, few_rows = self._queries()
        self._add(10)
        many, many_rows = self._queries()

        self.assertEqual((few_rows, many_rows), (2, 12))
        self.assertEqual(
            few,
            many,
            f"the register cost {few} queries for 2 completions and {many} for "
            "12 — something is being read one row at a time",
        )
        self.assertLessEqual(many, self.CEILING)


class ReviewNotificationLandsOnTheCompletionTest(TestCase):
    def test_the_lead_is_sent_to_the_named_completion(self):
        from apps.notifications.services import NotificationLinkResolver

        route, label = NotificationLinkResolver.resolve(
            "activity_submitted_for_review", "Activity", "act-42", "Program Lead"
        )
        self.assertEqual(route, f"{QUEUE_URL}?open=act-42")
        self.assertEqual(label, "Review Completion")

        ia_route, _ = NotificationLinkResolver.resolve(
            "activity_submitted_for_review", "Activity", "act-42", "ImpactAssessment"
        )
        self.assertEqual(ia_route, "/ia/verification/act-42/")
