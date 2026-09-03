"""Visits into somebody else's portfolio wait for that owner's yes.

The country roles with no portfolio — the Country Director, Impact Assessment
and the Accountant — do not plan into a CCEO's or Programme Lead's schools.
They ask: the visit is scheduled the ordinary way, carries the reason for it,
and sits in ``awaiting_owner_approval`` until the school's owner approves it
onto the requester's plan or declines it with a reason. Cluster meetings and
trainings of an owned cluster have no request path at all.

Where nobody owns the target the older rule stands: the CD and IA plan
directly, the Accountant is refused. See apps.planning.visit_requests.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.budget.models import CostCatalogue, CostSetting
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.planning import visit_requests
from apps.schools.models import School


def _confirmed_ssa(school):
    from apps.core.enums import SsaIntervention
    from apps.ssa.models import SsaRecord, SsaScore

    record = SsaRecord.objects.create(
        school=school,
        fy=get_operational_fy(),
        date_of_ssa=timezone.now() - datetime.timedelta(days=120),
        average_score=6.0,
        verification_status="confirmed",
    )
    for intervention, _ in SsaIntervention.choices:
        SsaScore.objects.create(ssa_record=record, intervention=intervention, score=6.0)


def _schedulable_date() -> datetime.date:
    from apps.core.calendar_policy import SchedulingPolicyService

    day = timezone.localdate() + datetime.timedelta(days=7)
    for _ in range(21):
        if SchedulingPolicyService.check(None, day)["status"] != "blocked":
            return day
        day += datetime.timedelta(days=1)
    raise AssertionError("no schedulable date within three weeks")


def _at(day: datetime.date):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(9, 0)))


class VisitRequestFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="VR Region")
        cls.district = District.objects.create(
            name="VR District", region=cls.region, district_type="primary"
        )

        def _person(email, name, role):
            user = User.objects.create_user(
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            profile = StaffProfile.objects.create(
                user=user, staff_number=f"VR-{name[:8]}", country="Uganda", title=role
            )
            return user, profile

        cls.cceo, cls.cceo_sp = _person("vr-cceo@edify.org", "Vera Owner", "CCEO")
        cls.other_cceo, cls.other_sp = _person(
            "vr-cceo2@edify.org", "Otto Other", "CCEO"
        )
        cls.pl, cls.pl_sp = _person("vr-pl@edify.org", "Pia Lead", "Program Lead")
        cls.cd, cls.cd_sp = _person(
            "vr-cd@edify.org", "Dan Director", "CountryDirector"
        )
        cls.ia, cls.ia_sp = _person("vr-ia@edify.org", "Ida Assess", "ImpactAssessment")
        cls.accountant, cls.acct_sp = _person(
            "vr-acct@edify.org", "Ann Counts", "Accountant"
        )

        cls.owned = School.objects.create(
            school_id="VR-OWNED",
            name="Owned Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
            account_owner_id=cls.cceo_sp.id,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.owned.id)
        cls.unowned = School.objects.create(
            school_id="VR-UNOWNED",
            name="Unowned Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        for school in (cls.owned, cls.unowned):
            _confirmed_ssa(school)

        cls.owned_cluster = Cluster.objects.create(
            name="Owned Cluster",
            region=cls.region,
            district=cls.district,
            cluster_type="mixed",
            status="active",
            responsible_staff_id=cls.cceo_sp.id,
        )
        cls.unowned_cluster = Cluster.objects.create(
            name="Unowned Cluster",
            region=cls.region,
            district=cls.district,
            cluster_type="mixed",
            status="active",
        )
        # Planning lists clustered schools only, and asks for both halves.
        cls.owned.cluster_id = cls.owned_cluster.id
        cls.owned.cluster_status = "clustered"
        cls.owned.save(update_fields=["cluster_id", "cluster_status"])

        cls.day = _schedulable_date()
        cls.fy = get_operational_fy(cls.day)
        catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda", fy=cls.fy, is_active=True, defaults={"version": 1}
        )
        for key, cost in (
            ("primary_transport_per_day", 50_000),
            ("primary_lunch_per_day", 12_000),
        ):
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key.replace("_", " ").title(),
                    "unit_cost": cost,
                    "fy": cls.fy,
                    "catalogue": catalogue,
                },
            )

    def _payload(self, school, *, justification="Spot check on last quarter's advance"):
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind

        data = {
            "schoolId": school.school_id,
            "catalogueItemId": resolve_item_for_workflow_kind("school_visit").id,
            "scheduledDate": _at(self.day).isoformat(),
            "activityPurposeText": "See the school for myself",
        }
        if justification is not None:
            data["visitJustification"] = justification
        return data

    def _request(self, who, school=None, **kw) -> Activity:
        from apps.planning.services import schedule_school_visit

        created = schedule_school_visit(self._payload(school or self.owned, **kw), who)
        return Activity.objects.get(id=created["id"])


class RequestingAVisitTest(VisitRequestFixture):
    def test_a_director_at_an_owned_school_asks_rather_than_plans(self):
        a = self._request(self.cd)

        self.assertEqual(a.status, visit_requests.AWAITING)
        self.assertEqual(a.approval_owner_id, self.cceo_sp.id)
        # The requester is the one going, not the owner being asked.
        self.assertEqual(a.responsible_staff_id, self.cd_sp.id)
        self.assertEqual(a.visit_justification, "Spot check on last quarter's advance")
        # Not a plan yet, so not priced yet: it draws no money and must not
        # dilute the day pool of the owner's own visits.
        self.assertEqual(a.est_cost_cents, 0)

    def test_impact_assessment_and_the_accountant_ask_the_same_way(self):
        for who in (self.ia, self.accountant):
            with self.subTest(role=who.active_role):
                a = self._request(who)
                self.assertEqual(a.status, visit_requests.AWAITING)
                self.assertEqual(a.approval_owner_id, self.cceo_sp.id)

    def test_the_owner_is_told_and_the_request_is_audited(self):
        from apps.audit.models import AuditLog

        a = self._request(self.cd)

        notice = Notification.objects.filter(
            recipient_id=self.cceo.id,
            source_event_type=visit_requests.EVENT_REQUESTED,
            context_id=a.id,
        ).first()
        self.assertIsNotNone(notice, "the owner was never told a request arrived")
        self.assertIn("Dan Director", notice.body)
        self.assertIn("Spot check", notice.body)
        self.assertTrue(
            AuditLog.objects.filter(
                action="visit_request_submitted", subject_id=a.id
            ).exists()
        )

    def test_a_request_without_a_reason_is_refused(self):
        with self.assertRaises(BadRequest):
            self._request(self.cd, justification="")
        with self.assertRaises(BadRequest):
            self._request(self.cd, justification=None)
        self.assertFalse(Activity.objects.filter(school=self.owned).exists())

    def test_a_request_is_not_funded_until_approved(self):
        from apps.fund_requests.models import WeeklyFundRequest

        self._request(self.cd)

        self.assertFalse(
            WeeklyFundRequest.objects.filter(responsible_user=self.cd.id)
            .exclude(total_amount=0)
            .exists(),
            "a visit nobody has approved yet must not enter a fund request",
        )

    def test_the_owner_plans_their_own_school_untouched(self):
        a = self._request(self.cceo, justification=None)

        self.assertEqual(a.status, "scheduled")
        self.assertEqual(a.approval_owner_id, "")

    def test_where_nobody_owns_the_school_the_visit_is_simply_scheduled(self):
        """Any school: with nobody to ask, all three roles schedule outright."""
        for who in (self.cd, self.ia, self.accountant):
            with self.subTest(role=who.active_role):
                a = self._request(who, self.unowned, justification=None)
                self.assertEqual(a.status, "scheduled")
                self.assertEqual(a.approval_owner_id, "")
                self.assertEqual(a.responsible_staff_id, who.staff_profile_id)

    def test_never_a_cluster_meeting_or_training(self):
        """Owned or not: cluster work is the cluster owner's programme."""
        from apps.activities.services import _assert_target_in_scope

        for who in (self.cd, self.ia, self.accountant):
            for cluster in (self.owned_cluster, self.unowned_cluster):
                with (
                    self.subTest(role=who.active_role, cluster=cluster.name),
                    self.assertRaises(Forbidden),
                ):
                    _assert_target_in_scope(
                        school=None, cluster_id=cluster.id, principal=who
                    )
        # The owner is unaffected.
        _assert_target_in_scope(
            school=None, cluster_id=self.owned_cluster.id, principal=self.cceo
        )

    def test_a_requester_may_move_their_own_visit(self):
        from apps.activities.services import _assert_may_schedule

        a = self._request(self.accountant, self.unowned, justification=None)
        _assert_may_schedule(a, self.accountant)  # does not raise
        # Another country role with no scheduling authority still may not.
        other = User.objects.create_user(
            email="vr-acct2@edify.org",
            name="Other Counts",
            roles=["Accountant"],
            active_role="Accountant",
            password="x",
            is_active=True,
        )
        with self.assertRaises(Forbidden):
            _assert_may_schedule(a, other)


class DecidingAVisitRequestTest(VisitRequestFixture):
    def setUp(self):
        self.request = self._request(self.cd)

    def test_only_the_owner_holds_the_request(self):
        self.assertEqual(
            [a.id for a in visit_requests.pending_for_owner(self.cceo)],
            [self.request.id],
        )
        for who in (self.pl, self.other_cceo, self.cd):
            with self.subTest(role=who.active_role):
                self.assertEqual(list(visit_requests.pending_for_owner(who)), [])
                with self.assertRaises(Forbidden):
                    visit_requests.approve(self.request.id, who)

    def test_approval_puts_the_visit_on_the_requesters_plan(self):
        from apps.audit.models import AuditLog
        from apps.fund_requests.models import WeeklyFundRequest

        visit_requests.approve(self.request.id, self.cceo, "Go ahead, Tuesday is fine")
        self.request.refresh_from_db()

        self.assertEqual(self.request.status, "scheduled")
        self.assertEqual(self.request.owner_decided_by, self.cceo.id)
        self.assertEqual(self.request.owner_decision_note, "Go ahead, Tuesday is fine")
        self.assertEqual(self.request.responsible_staff_id, self.cd_sp.id)
        # Priced at approval, against the requester, and it now draws money on
        # the requester's own request.
        self.assertGreater(self.request.est_cost_cents, 0)
        self.assertTrue(
            WeeklyFundRequest.objects.filter(responsible_user=self.cd.id)
            .exclude(total_amount=0)
            .exists(),
            "an approved visit must enter the requester's weekly fund request",
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="visit_request_approve", subject_id=self.request.id
            ).exists()
        )
        # The requester is told, and the owner's own notice is closed.
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.cd.id,
                source_event_type=visit_requests.EVENT_APPROVED,
                context_id=self.request.id,
            ).exists()
        )
        owner_notice = Notification.objects.get(
            recipient_id=self.cceo.id,
            source_event_type=visit_requests.EVENT_REQUESTED,
            context_id=self.request.id,
        )
        self.assertIsNotNone(owner_notice.resolved_at)

    def test_it_shows_on_the_requesters_plan_as_waiting_then_as_scheduled(self):
        from apps.my_plan.services import (
            compute_next_action,
            get_activity_status_label_and_class,
        )

        today = timezone.localdate()
        label, _cls = get_activity_status_label_and_class(self.request, today)
        self.assertEqual(label, "Awaiting owner approval")
        action = compute_next_action(self.request, today)
        self.assertEqual(action["action"], "await_owner")
        self.assertEqual(action["url"], visit_requests.QUEUE_URL)

        visit_requests.approve(self.request.id, self.cceo)
        self.request.refresh_from_db()
        label, _cls = get_activity_status_label_and_class(self.request, today)
        self.assertNotEqual(label, "Awaiting owner approval")

    def test_declining_needs_a_reason_and_tells_the_requester(self):
        with self.assertRaises(BadRequest):
            visit_requests.decline(self.request.id, self.cceo, "   ")

        visit_requests.decline(self.request.id, self.cceo, "Exams that week")
        self.request.refresh_from_db()

        self.assertEqual(self.request.status, "rejected")
        self.assertEqual(self.request.owner_decision_note, "Exams that week")
        notice = Notification.objects.get(
            recipient_id=self.cd.id,
            source_event_type=visit_requests.EVENT_DECLINED,
            context_id=self.request.id,
        )
        self.assertIn("Exams that week", notice.body)
        self.assertEqual(notice.priority, "high")

    def test_a_pending_request_cannot_be_edited_into_a_plan(self):
        """Reschedule and reassign both write a live status. Around an owner
        who has not said yes, that is a bypass."""
        from apps.activities.services import reassign, reschedule

        new_day = _at(self.day + datetime.timedelta(days=1)).isoformat()
        with self.assertRaises(BadRequest):
            reschedule(
                self.request.id, {"scheduledDate": new_day, "reason": "x"}, self.cd
            )
        with self.assertRaises(BadRequest):
            reassign(self.request.id, {"deliveryType": "staff"}, self.cd)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, visit_requests.AWAITING)

    def test_a_decided_request_is_not_decided_twice(self):
        visit_requests.approve(self.request.id, self.cceo)
        with self.assertRaises(BadRequest):
            visit_requests.decline(self.request.id, self.cceo, "changed my mind")
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, "scheduled")

    def test_the_owner_gets_a_todo_nobody_else_does(self):
        from apps.command_center.todo_service import get_todos

        ids = {t["id"] for t in get_todos(self.cceo)["todos"]}
        self.assertIn(f"visitreq-{self.request.id}", ids)
        for who in (self.pl, self.other_cceo):
            with self.subTest(role=who.active_role):
                ids = {t["id"] for t in get_todos(who)["todos"]}
                self.assertNotIn(f"visitreq-{self.request.id}", ids)


class VisitRequestSurfacesTest(VisitRequestFixture):
    """The drawer, the page and the sidebar — as the roles actually reach them."""

    def _post_visit(self, who, school, **extra):
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind

        self.client.force_login(who)
        data = {
            "school_id": school.school_id,
            "catalogue_item_id": resolve_item_for_workflow_kind("school_visit").id,
            "scheduled_date": _at(self.day).isoformat(),
            "activity_purpose_text": "See the school for myself",
            "purpose_of_visit": "ssa_support",
            "delivery_type": "staff",
            "executor_type": "staff",
        }
        data.update(extra)
        return self.client.post("/planning/schedule-action", data)

    def test_the_drawer_asks_a_requester_why(self):
        for who in (self.cd, self.ia, self.accountant):
            with self.subTest(role=who.active_role):
                self.client.force_login(who)
                response = self.client.get(
                    f"/planning/schedule-modal?school_id={self.owned.school_id}"
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="visit_justification"')
                self.assertContains(response, "Vera Owner")

    def test_the_drawer_is_the_ordinary_one_where_nobody_owns_the_school(self):
        self.client.force_login(self.cd)
        response = self.client.get(
            f"/planning/schedule-modal?school_id={self.unowned.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="visit_justification"')

    def test_the_owner_still_sees_their_own_drawer(self):
        self.client.force_login(self.cceo)
        response = self.client.get(
            f"/planning/schedule-modal?school_id={self.owned.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="visit_justification"')

    def test_submitting_without_a_reason_is_refused_with_one_sentence(self):
        response = self._post_visit(self.cd, self.owned, visit_justification="")
        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response, "Explain why you need to visit this school", status_code=400
        )
        self.assertFalse(Activity.objects.filter(school=self.owned).exists())

    def test_submitting_files_a_request_and_says_where_it_went(self):
        response = self._post_visit(
            self.cd, self.owned, visit_justification="Monitoring visit before the board"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(visit_requests.QUEUE_URL, response.content.decode())
        a = Activity.objects.get(school=self.owned)
        self.assertEqual(a.status, visit_requests.AWAITING)
        self.assertEqual(a.responsible_staff_id, self.cd_sp.id)
        self.assertEqual(a.visit_justification, "Monitoring visit before the board")

    def test_the_owner_decides_on_the_page(self):
        a = self._request(self.cd)

        self.client.force_login(self.cceo)
        response = self.client.get(visit_requests.QUEUE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-visit-request-pending="{a.id}"')
        self.assertContains(response, "Dan Director asks to visit Owned Primary")

        response = self.client.post(
            f"{visit_requests.QUEUE_URL}/{a.id}/approve", {"note": "Fine by me"}
        )
        self.assertEqual(response.status_code, 302)
        a.refresh_from_db()
        self.assertEqual(a.status, "scheduled")

    def test_someone_else_is_refused_on_the_page(self):
        a = self._request(self.cd)
        self.client.force_login(self.other_cceo)
        response = self.client.post(
            f"{visit_requests.QUEUE_URL}/{a.id}/decline", {"reason": "no"}
        )
        self.assertEqual(response.status_code, 403)
        a.refresh_from_db()
        self.assertEqual(a.status, visit_requests.AWAITING)

    def test_a_requester_follows_their_requests_on_the_page(self):
        a = self._request(self.accountant)
        self.client.force_login(self.accountant)

        page = self.client.get(visit_requests.QUEUE_URL)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'data-visit-request-row="{a.id}"')
        self.assertContains(page, "Awaiting approval")

    def test_requesters_schedule_from_planning_and_the_queue_is_not_a_menu_item(
        self,
    ):
        """Owners reach the queue from the To-Do and the notification; the
        three request-only roles reach the drawer from Planning, where the
        button stays "Schedule" (owner, 2026-09-02)."""
        from types import SimpleNamespace

        from apps.core.navigation import build_sidebar_for_user

        for role in ("CCEO", "PL", "CD", "IA", "ACCOUNTANT"):
            with self.subTest(role=role):
                urls = {
                    i["url"]
                    for g in build_sidebar_for_user(
                        SimpleNamespace(is_authenticated=True, active_role=role), "/"
                    )
                    for i in g["items"]
                }
                self.assertIn("/planning", urls)
                self.assertNotIn(visit_requests.QUEUE_URL, urls)
        for who in (self.cd, self.ia, self.accountant):
            with self.subTest(role=who.active_role):
                self.client.force_login(who)
                response = self.client.get("/planning")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Schedule activity for Owned Primary")
                clusters = self.client.get("/planning?tab=clusters")
                self.assertEqual(clusters.status_code, 200)
                self.assertNotContains(clusters, "Group Training")
                self.assertNotContains(clusters, "Cluster Meeting")
                drawer = self.client.get(
                    f"/planning/schedule-modal?cluster_id={self.unowned_cluster.id}"
                )
                self.assertEqual(drawer.status_code, 403)
        self.client.force_login(self.cceo)
        clusters = self.client.get("/planning?tab=clusters")
        self.assertContains(clusters, "Group Training")

    def test_the_cluster_profile_offers_cluster_planning_to_planners_only(self):
        for who in (self.cd, self.ia):
            with self.subTest(role=who.active_role):
                self.client.force_login(who)
                page = self.client.get(f"/clusters/{self.owned_cluster.id}")
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, "Schedule Group Training")
                self.assertNotContains(page, "Schedule Cluster Meeting")
        self.client.force_login(self.cceo)
        page = self.client.get(f"/clusters/{self.owned_cluster.id}")
        self.assertContains(page, "Schedule Group Training")


class CoreVisitRequestTest(VisitRequestFixture):
    """The same rule on the Core lane, whatever stage the school is at.

    Core, Champion, Core Trained and Core Graduate schools are scheduled
    through the core package drawers, which take their own path to `create`.
    A request-only role's core visit waits for the owner; a declined request
    hands the package slot back; core trainings are refused to those roles
    outright (owner, 2026-09-02).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.activity_catalogue.models import ActivityCatalogueItem
        from apps.core_schools.models import (
            CorePlan,
            CoreSchoolProfile,
            cplan_id,
            cprof_id,
        )
        from apps.core_schools.services import create_package_slots

        cls.core_item = ActivityCatalogueItem.objects.get(
            stable_code="CORE_SCHOOL_FOLLOWUP_VISIT"
        )
        cls.core_schools = {}
        for stage in ("core", "champion", "core_trained", "core_graduate"):
            school = School.objects.create(
                school_id=f"VR-{stage.upper()}",
                name=f"{stage.replace('_', ' ').title()} Primary",
                region=cls.region,
                district=cls.district,
                school_type=stage,
                current_fy_ssa_status="done",
                account_owner_id=cls.cceo_sp.id,
                account_owner_status="matched",
                cluster_id=cls.owned_cluster.id,
                cluster_status="clustered",
            )
            StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=school.id)
            _confirmed_ssa(school)
            plan = CorePlan.objects.create(
                id=cplan_id(school.school_id, cls.fy),
                school_id=school.school_id,
                fy=cls.fy,
                status="Active",
            )
            CoreSchoolProfile.objects.create(
                id=cprof_id(school.school_id),
                school_id=school.school_id,
                core_plan=plan,
                core_start_fy=cls.fy,
            )
            create_package_slots(plan, school.school_id, ["leadership"])
            cls.core_schools[stage] = school

    def _post_core_visit(self, who, school, **extra):
        self.client.force_login(who)
        data = {
            "school_id": school.school_id,
            "visit_number": "1",
            "scheduled_date": self.day.isoformat(),
            "focus_intervention": "leadership",
            "visit_purpose": "Core package check",
            "expected_outcome": "Slot fulfilled",
            "responsible_staff_id": self.cceo_sp.user_id,
            "catalogue_item_id": self.core_item.id,
        }
        data.update(extra)
        return self.client.post("/core-schools/schedule-visit/action", data)

    def _slot(self, school):
        from apps.core_schools.models import CoreActivitySlot

        return CoreActivitySlot.objects.get(
            school_id=school.school_id, activity_type="visit", sequence_number=1
        )

    def test_a_core_visit_by_a_country_role_waits_for_the_owner_at_every_stage(self):
        for stage, school in self.core_schools.items():
            with self.subTest(stage=stage):
                response = self._post_core_visit(
                    self.cd, school, visit_justification="Board asked me to see it"
                )
                self.assertEqual(response.status_code, 200, response.content[:300])
                self.assertIn(visit_requests.QUEUE_URL, response.content.decode())
                a = Activity.objects.get(school=school, activity_type="core_visit")
                self.assertEqual(a.status, visit_requests.AWAITING)
                self.assertEqual(a.approval_owner_id, self.cceo_sp.id)
                # Filed against the requester, not the posted owner.
                self.assertEqual(a.responsible_staff_id, self.cd_sp.id)
                slot = self._slot(school)
                self.assertEqual(slot.status, "Scheduled")
                self.assertEqual(slot.activity_id, a.id)

    def test_the_core_drawer_asks_the_requester_why(self):
        school = self.core_schools["core"]
        for who in (self.cd, self.ia, self.accountant):
            with self.subTest(role=who.active_role):
                self.client.force_login(who)
                response = self.client.get(
                    f"/core-schools/schedule-visit?school_id={school.school_id}"
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="visit_justification"')
                self.assertContains(response, "Vera Owner")

    def test_without_a_reason_the_core_request_is_refused(self):
        school = self.core_schools["champion"]
        response = self._post_core_visit(self.accountant, school)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Activity.objects.filter(school=school).exists())
        self.assertEqual(self._slot(school).status, "Planned")

    def test_declining_hands_the_package_slot_back(self):
        school = self.core_schools["core_trained"]
        self._post_core_visit(self.ia, school, visit_justification="Verification")
        a = Activity.objects.get(school=school)
        visit_requests.decline(a.id, self.cceo, "Not this term")
        slot = self._slot(school)
        self.assertEqual(slot.status, "Planned")
        self.assertIsNone(slot.activity_id)
        self.assertIsNone(slot.assigned_staff_id)
        self.assertEqual(slot.owner, "unassigned")

    def test_approving_keeps_the_slot_and_schedules_the_visit(self):
        school = self.core_schools["core_graduate"]
        self._post_core_visit(self.cd, school, visit_justification="Graduation review")
        a = Activity.objects.get(school=school)
        visit_requests.approve(a.id, self.cceo)
        a.refresh_from_db()
        self.assertEqual(a.status, "scheduled")
        self.assertGreater(a.est_cost_cents, 0)
        # Activity.save mirrors its own (lowercase) status onto the slot, and
        # every slot reader normalises case — so compare the way they read.
        self.assertEqual(self._slot(school).status.lower(), "scheduled")

    def test_core_trainings_are_refused_to_country_roles(self):
        school = self.core_schools["core"]
        for who in (self.cd, self.ia, self.accountant):
            with self.subTest(role=who.active_role):
                self.client.force_login(who)
                drawer = self.client.get(
                    f"/core-schools/schedule-training?school_id={school.school_id}"
                )
                self.assertEqual(drawer.status_code, 403)
                action = self.client.post(
                    "/core-schools/schedule-training/action",
                    {"school_id": school.school_id, "training_number": "1"},
                )
                self.assertEqual(action.status_code, 403)
                chooser = self.client.get(
                    f"/core-schools/schedule-activity?school_id={school.school_id}"
                )
                self.assertEqual(chooser.status_code, 200)
                self.assertNotContains(chooser, "schedule-training")
        self.client.force_login(self.cceo)
        chooser = self.client.get(
            f"/core-schools/schedule-activity?school_id={school.school_id}"
        )
        self.assertContains(chooser, "schedule-training")

    def test_the_owner_still_schedules_core_work_directly(self):
        school = self.core_schools["core"]
        response = self._post_core_visit(self.cceo, school)
        self.assertEqual(response.status_code, 200, response.content[:300])
        a = Activity.objects.get(school=school)
        self.assertEqual(a.status, "scheduled")
        self.assertEqual(a.approval_owner_id, "")
