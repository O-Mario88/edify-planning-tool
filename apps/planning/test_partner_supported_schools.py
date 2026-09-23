"""Partner support changes delivery responsibility, never school ownership.

Owner rule, 2026-09-23. These tests hold the rule end to end:

* the school stays on Planning and in the Cluster School List, with its staff
  owner, and a Responsible column naming Staff or Partner from live records;
* at a Partner-supported school staff may plan Data Gathering, Content
  Gathering and Donor Visits directly, and Cluster Meetings and Group Training
  through Cluster Planning — the server refuses everything else, whatever the
  browser sends;
* Partner-delivered work is the Partner's: never on a staff My Plan, never in
  a staff fund request, never a staff target credit;
* the shared Visit and Training Status badges count Partner work where the
  school is, honest about planned / submitted / verified, and never block
  planning; the Planning filters and Next Activity read the same buckets.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffSchoolAssignment, User
from apps.activities.models import (
    Activity,
    ActivityScheduleCostLine,
    ClusterActivityAttendance,
)
from apps.core.exceptions import BadRequest, ConflictError, Forbidden
from apps.core.fy import get_operational_fy
from apps.partners.models import Partner, PartnerAssignment
from apps.partners.services import create_assignment
from apps.partners.support_responsibility import (
    MULTIPLE_PARTNER_ISSUE_TYPE,
    SchoolSupportResponsibilityService,
)
from apps.planning.partner_school_policy import (
    PartnerSupportedSchoolPlanningPolicy,
    PlanningDecision,
    assert_cluster_invitations_allowed,
    partner_supported_members,
)
from apps.planning.planning_support import (
    PLANNING_SUPPORT_FILTERS,
    filter_queryset,
    next_activities,
)
from apps.planning.school_planning_badges import SchoolPlanningBadgeService
from apps.planning.test_standard_support_scheduling import (
    StandardSupportBase,
    _at,
    _schedulable_date,
)
from apps.schools.models import DataQualityIssue, School

ROOT = Path(settings.BASE_DIR)


def _later_date(days: int) -> datetime.date:
    """A schedulable date ``days`` after the first one, skipping Sundays."""
    day = _schedulable_date() + datetime.timedelta(days=days)
    while day.weekday() == 6:
        day += datetime.timedelta(days=1)
    return day


class PartnerSchoolFixture(StandardSupportBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        School.objects.filter(id=cls.school.id).update(
            account_owner_id=cls.staff.id, sub_county=cls.sub_county
        )
        cls.school.refresh_from_db()
        cls.partner_user = User.objects.create_user(
            email="ozeki-officer@edify.org",
            name="Ozeki Officer",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            password="x",
            is_active=True,
        )
        cls.partner = Partner.objects.create(
            name="Ozeki Foundation", active_status=True, user=cls.partner_user
        )
        cls.other_partner = Partner.objects.create(
            name="Bright Future", active_status=True
        )
        cls.third_partner = Partner.objects.create(
            name="Learning Bridge", active_status=True
        )
        cls.fy = get_operational_fy()
        cls.members = list(
            School.objects.filter(school_id__startswith="STD-MEM-").order_by(
                "school_id"
            )
        )

    def hand_to_partner(self, school=None, partner=None):
        """The canonical creation door, exactly as Planning's Assign uses it."""
        return create_assignment(
            school=school or self.school,
            partner=partner or self.partner,
            assigning_staff_id=self.staff.id,
            monitoring_staff_id=self.staff.id,
            catalogue_item=self.item("STANDARD_IN_SCHOOL_TRAINING"),
            expected_activity_type="in_school_training",
            purpose_of_visit="in_school_training",
        )

    def partner_activity(self, school=None, *, status="partner_scheduled", **kw):
        when = kw.pop("planned_date", _schedulable_date())
        return Activity.objects.create(
            activity_type=kw.pop("activity_type", "school_visit"),
            school=school or self.school,
            fy=kw.pop("fy", self.fy),
            quarter="Q1",
            planned_date=when,
            scheduled_date=_at(when),
            status=status,
            delivery_type="partner",
            executor_type="partner",
            assigned_partner_id=kw.pop("partner_id", self.partner.id),
            monitored_by_staff_id=self.staff.id,
            responsible_staff_id=kw.pop("responsible_staff_id", None),
            **kw,
        )

    def staff_activity(self, code, **payload):
        return self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item(code).id,
            activityPurposeText="Planned from the Planning page",
            **payload,
        )

    def planning_rows(self, principal=None, **filters):
        from apps.planning.planning_service import PlanningDashboardService

        data = PlanningDashboardService.get_dashboard_data(
            principal or self.user,
            {"fy": self.fy, "tab": "client", "page": 1, "per_page": 50, **filters},
        )
        return {row["schoolId"]: row for row in data["schools"]}

    def my_plan_queryset_ids(self, principal=None):
        from apps.my_plan import services as my_plan

        feed = my_plan.get(principal or self.user, {"fy": self.fy, "period": "fy"})
        return {row["id"] for row in feed["items"]}


# ── Ownership and visibility ────────────────────────────────────────────────
class OwnershipAndVisibilityTest(PartnerSchoolFixture):
    def test_a_partner_supported_school_stays_on_planning(self):
        self.hand_to_partner()

        rows = self.planning_rows()

        self.assertIn(self.school.school_id, rows)
        row = rows[self.school.school_id]
        self.assertEqual(row["responsible"]["responsibility_type"], "partner")
        self.assertEqual(row["responsible"]["responsible_name"], "Ozeki Foundation")
        self.assertEqual(row["responsible"]["display"], "Partner · Ozeki Foundation")
        # The owner stays on the row beside the Partner.
        self.assertEqual(row["responsible"]["staff_owner_name"], "Standard CCEO")
        self.assertEqual(row["ownerName"], "Standard CCEO")

    def test_partner_work_scheduled_into_the_next_year_still_counts(self):
        """A Partner that schedules into the next financial year is still
        supporting the school now; reading this year alone would flip the
        school back to Staff the moment the date crossed 1 October."""
        assignment = self.hand_to_partner()
        activity = self.partner_activity(fy=str(int(self.fy) + 1))
        PartnerAssignment.objects.filter(id=assignment.id).update(
            status=PartnerAssignment.STATUS_SCHEDULED,
            scheduled_activity=activity,
        )

        support = SchoolSupportResponsibilityService.for_school(self.school, fy=self.fy)

        self.assertTrue(support.is_partner)
        self.assertEqual(support.display, "Partner · Ozeki Foundation")

    def test_partner_work_from_an_earlier_year_does_not_count(self):
        assignment = self.hand_to_partner()
        activity = self.partner_activity(fy=str(int(self.fy) - 1))
        PartnerAssignment.objects.filter(id=assignment.id).update(
            status=PartnerAssignment.STATUS_SCHEDULED,
            scheduled_activity=activity,
        )

        support = SchoolSupportResponsibilityService.for_school(self.school, fy=self.fy)

        self.assertFalse(support.is_partner)

    def test_the_planning_page_renders_the_partner_and_keeps_the_plan_action(self):
        self.hand_to_partner()
        client = Client()
        client.force_login(self.user)

        html = client.get("/planning?tab=client").content.decode()

        self.assertIn(self.school.name, html)
        self.assertIn('data-responsible="partner"', html)
        self.assertIn("Ozeki Foundation", html)
        self.assertIn("<dt>Responsible</dt>", html)
        self.assertIn("data-planning-support", html)
        # Selectable and plannable: the Schedule action is a live button.
        self.assertIn(
            f"/planning/schedule-modal?school_id={self.school.school_id}", html
        )

    def test_a_partner_supported_school_stays_in_the_cluster_school_list(self):
        from apps.clusters.services import cluster_schools

        self.hand_to_partner()

        rows = {r["schoolId"]: r for r in cluster_schools(self.cluster.id, self.user)}

        self.assertIn(self.school.school_id, rows)
        self.assertEqual(
            rows[self.school.school_id]["responsible"]["display"],
            "Partner · Ozeki Foundation",
        )

    def test_planning_and_the_cluster_list_give_the_same_answer(self):
        from apps.clusters.services import cluster_schools

        self.hand_to_partner()
        self.partner_activity()
        self.staff_activity("STANDARD_DONOR_VISIT")

        from django.test import RequestFactory

        from apps.frontend.views.cluster_views import _attach_planning_badges

        planning = self.planning_rows()[self.school.school_id]
        roster = cluster_schools(self.cluster.id, self.user)
        _attach_planning_badges(RequestFactory().get("/", {"fy": self.fy}), roster)
        cluster = {r["schoolId"]: r for r in roster}[self.school.school_id]

        self.assertEqual(planning["responsible"], cluster["responsible"])
        self.assertEqual(
            planning["planningBadges"].as_dict(), cluster["planningBadges"].as_dict()
        )
        self.assertEqual(planning["nextActivity"], cluster["nextActivity"])
        self.assertEqual(planning["planningBadges"].visits.planned_count, 2)

    def test_ownership_is_unchanged_by_the_assignment(self):
        before = (
            self.school.account_owner_id,
            self.school.district_id,
            self.school.cluster_id,
            list(
                StaffSchoolAssignment.objects.filter(
                    school_id=self.school.id
                ).values_list("staff_id", flat=True)
            ),
        )

        self.hand_to_partner()
        self.school.refresh_from_db()

        after = (
            self.school.account_owner_id,
            self.school.district_id,
            self.school.cluster_id,
            list(
                StaffSchoolAssignment.objects.filter(
                    school_id=self.school.id
                ).values_list("staff_id", flat=True)
            ),
        )
        self.assertEqual(before, after)
        self.assertEqual(School.objects.filter(school_id="STD-001").count(), 1)

    def test_staff_name_shows_when_no_partner_supports_the_school(self):
        row = self.planning_rows()[self.school.school_id]

        self.assertEqual(row["responsible"]["responsibility_type"], "staff")
        self.assertEqual(row["responsible"]["display"], "Staff · Standard CCEO")

    def test_a_returned_assignment_leaves_no_stale_partner_label(self):
        assignment = self.hand_to_partner()
        PartnerAssignment.objects.filter(id=assignment.id).update(
            status=PartnerAssignment.STATUS_RETURNED_TO_STAFF
        )

        result = SchoolSupportResponsibilityService.for_school(self.school)

        self.assertEqual(result.responsibility_type, "staff")
        self.assertEqual(result.display, "Staff · Standard CCEO")
        self.assertTrue(result.staff_action_required)
        self.assertEqual(
            result.workflow_label, "Partner Returned — Staff Action Required"
        )

    def test_a_cancelled_partner_activity_releases_the_school(self):
        assignment = self.hand_to_partner()
        activity = self.partner_activity(status="cancelled")
        PartnerAssignment.objects.filter(id=assignment.id).update(
            status="partner_scheduled", scheduled_activity=activity
        )

        result = SchoolSupportResponsibilityService.for_school(self.school)

        self.assertEqual(result.responsibility_type, "staff")
        self.assertFalse(result.staff_action_required)

    def test_two_partners_are_never_silently_resolved_to_one(self):
        self.hand_to_partner()
        with self.captureOnCommitCallbacks(execute=True):
            self.hand_to_partner(partner=self.other_partner)

        result = SchoolSupportResponsibilityService.for_school(self.school)

        self.assertEqual(result.responsibility_type, "multiple_partners")
        self.assertEqual(result.display, "Multiple Partners — Review Required")
        self.assertIn("Ozeki Foundation", result.partner_names)
        self.assertIn("Bright Future", result.partner_names)
        issue = DataQualityIssue.objects.get(
            school=self.school, issue_type=MULTIPLE_PARTNER_ISSUE_TYPE
        )
        self.assertEqual(issue.status, "open")
        # Existing records are preserved; a third Partner waits for review.
        self.assertEqual(
            PartnerAssignment.objects.filter(school=self.school).count(), 2
        )
        with self.assertRaises(ConflictError):
            self.hand_to_partner(partner=self.third_partner)

    def test_the_exception_closes_when_one_partner_lets_go(self):
        self.hand_to_partner()
        with self.captureOnCommitCallbacks(execute=True):
            second = self.hand_to_partner(partner=self.other_partner)
        with self.captureOnCommitCallbacks(execute=True):
            second.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
            second.save(update_fields=["status", "updated_at"])

        issue = DataQualityIssue.objects.get(
            school=self.school, issue_type=MULTIPLE_PARTNER_ISSUE_TYPE
        )
        self.assertEqual(issue.status, "resolved")

    def test_a_school_save_does_not_close_the_partner_exception(self):
        self.hand_to_partner()
        with self.captureOnCommitCallbacks(execute=True):
            self.hand_to_partner(partner=self.other_partner)

        self.school.refresh_from_db()
        self.school.save()

        self.assertTrue(
            DataQualityIssue.objects.filter(
                school=self.school,
                issue_type=MULTIPLE_PARTNER_ISSUE_TYPE,
                status="open",
            ).exists()
        )

    @override_settings(PARTNER_SUPPORTED_SCHOOL_PLANNING_VISIBILITY_ENABLED=False)
    def test_switching_the_rule_off_restores_the_previous_display(self):
        self.hand_to_partner()

        rows = self.planning_rows()

        self.assertNotIn(self.school.school_id, rows)
        self.assertTrue(PartnerAssignment.objects.filter(school=self.school).exists())

    @override_settings(
        PARTNER_SUPPORTED_SCHOOL_PLANNING_VISIBILITY_ENABLED=False,
        PARTNER_SUPPORTED_SCHOOL_PLANNING_PILOT_ROLES=["CCEO"],
    )
    def test_a_pilot_role_sees_the_rule_while_it_is_off_for_everyone_else(self):
        self.hand_to_partner()

        self.assertIn(self.school.school_id, self.planning_rows())


# ── Direct planning policy ──────────────────────────────────────────────────
class DirectPlanningPolicyTest(PartnerSchoolFixture):
    def setUp(self):
        super().setUp()
        self.hand_to_partner()

    def test_data_gathering_is_allowed(self):
        result = self.staff_activity(
            "STANDARD_SCHOOL_VISIT_SSA_COLLECTION",
            purposeType="ssa_support",
            ssaCollectionExpected=True,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.delivery_type, "staff")
        self.assertEqual(activity.responsible_staff_id, self.staff.id)

    def test_content_gathering_is_allowed(self):
        result = self.staff_activity("STANDARD_STORY_GATHERING_VISIT")
        self.assertEqual(Activity.objects.get(id=result["id"]).delivery_type, "staff")

    def test_donor_visit_is_allowed(self):
        result = self.staff_activity("STANDARD_DONOR_VISIT")
        self.assertEqual(Activity.objects.get(id=result["id"]).delivery_type, "staff")

    def test_the_assignment_stays_active_after_staff_plan_there(self):
        self.staff_activity("STANDARD_DONOR_VISIT")

        self.assertEqual(
            SchoolSupportResponsibilityService.for_school(
                self.school
            ).responsibility_type,
            "partner",
        )

    def test_other_direct_school_support_is_refused_with_the_reason(self):
        for code in (
            "STANDARD_SCHOOL_VISIT",
            "STANDARD_IN_SCHOOL_SUPPORT",
            "STANDARD_SOCIAL_VISIT",
            "STANDARD_IN_SCHOOL_COACHING_VISIT",
        ):
            with self.subTest(code=code):
                with self.assertRaisesMessage(
                    BadRequest, "This school is currently supported by Ozeki"
                ):
                    self.staff_activity(code, focusIntervention="leadership")
        self.assertFalse(Activity.objects.filter(school=self.school).exists())
        self.assertFalse(
            ActivityScheduleCostLine.objects.filter(
                activity__school=self.school
            ).exists()
        )

    def test_in_school_training_is_refused_and_leaves_nothing_behind(self):
        from apps.activity_catalogue.availability import (
            in_school_training_course_options,
        )
        from apps.planning.services import schedule_in_school_training_pair

        courses = in_school_training_course_options(school=self.school)
        if not courses:
            self.skipTest("no governed in-school course in this catalogue")
        with self.assertRaises(BadRequest):
            schedule_in_school_training_pair(
                {
                    "schoolId": self.school.school_id,
                    "catalogueItemId": courses[0]["id"],
                    "scheduledDate": _at(_schedulable_date()).isoformat(),
                    "responsibleStaffId": self.staff.id,
                },
                self.user,
            )
        self.assertFalse(Activity.objects.filter(school=self.school).exists())

    def test_the_api_refuses_a_manipulated_selection(self):
        client = Client()
        client.force_login(self.user)

        response = client.post(
            "/api/activities",
            {
                "catalogueItemId": self.item("STANDARD_SCHOOL_VISIT").id,
                "schoolId": self.school.school_id,
                "scheduledDate": _at(_schedulable_date()).isoformat(),
                "activityPurposeText": "Crafted request",
                "focusIntervention": "leadership",
            },
            content_type="application/json",
        )

        self.assertNotEqual(response.status_code, 201)
        self.assertIn("supported by Ozeki", response.content.decode())
        self.assertFalse(Activity.objects.filter(school=self.school).exists())

    def test_the_drawer_post_refuses_a_manipulated_purpose(self):
        client = Client()
        client.force_login(self.user)

        response = client.post(
            "/planning/schedule-action",
            {
                "school_id": self.school.school_id,
                "scheduled_date": _schedulable_date().isoformat(),
                "purpose_of_visit": "social_visit",
                "activity_purpose_text": "Crafted purpose",
                "require_catalogue": "yes",
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("supported by Ozeki", response.content.decode())
        self.assertFalse(Activity.objects.filter(school=self.school).exists())

    def test_the_drawer_offers_only_the_whitelisted_purposes(self):
        client = Client()
        client.force_login(self.user)

        html = client.get(
            f"/planning/schedule-modal?school_id={self.school.school_id}"
        ).content.decode()

        self.assertIn("data-partner-support-notice", html)
        self.assertIn("This school is supported by Ozeki Foundation", html)
        self.assertIn(
            "Staff may directly plan Data Gathering, Content Gathering, or Donor Visits",
            html,
        )
        for locked in (
            "in_school_training",
            "training_follow_up",
            "social_visit",
            "school_invitation",
        ):
            with self.subTest(locked=locked):
                self.assertIn(
                    f'<option value="{locked}" disabled data-purpose-locked="partner"',
                    html,
                )
        for open_purpose in ("ssa_support", "donor_visit", "story_gathering"):
            with self.subTest(open=open_purpose):
                self.assertNotIn(
                    f'<option value="{open_purpose}" disabled data-purpose-locked="partner"',
                    html,
                )

    def test_a_role_without_the_grant_cannot_plan_there(self):
        director = User.objects.create_user(
            email="rvp-policy@edify.org",
            name="RVP",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
            password="x",
            is_active=True,
        )

        result = PartnerSupportedSchoolPlanningPolicy.evaluate(
            self.school,
            self.item("STANDARD_DONOR_VISIT"),
            principal=director,
        )

        self.assertEqual(result.decision, PlanningDecision.NOT_ALLOWED)

    def test_partner_delivery_is_the_partner_workflow_not_this_rule(self):
        result = PartnerSupportedSchoolPlanningPolicy.evaluate(
            self.school,
            self.item("STANDARD_SCHOOL_VISIT"),
            delivery_channel="partner",
        )

        self.assertEqual(result.decision, PlanningDecision.PARTNER_WORKFLOW_REQUIRED)


class StaffManagedSchoolsAreUnaffectedTest(PartnerSchoolFixture):
    def test_a_staff_managed_school_keeps_every_option(self):
        result = self.staff_activity(
            "STANDARD_SCHOOL_VISIT", focusIntervention="financial_health"
        )
        self.assertEqual(Activity.objects.get(id=result["id"]).delivery_type, "staff")

    def test_the_drawer_locks_nothing_at_a_staff_managed_school(self):
        client = Client()
        client.force_login(self.user)

        html = client.get(
            f"/planning/schedule-modal?school_id={self.school.school_id}"
        ).content.decode()

        self.assertNotIn('data-purpose-locked="partner"', html)
        self.assertNotIn("data-partner-support-notice", html)


# ── Cluster Planning ────────────────────────────────────────────────────────
class ClusterPlanningTest(PartnerSchoolFixture):
    def setUp(self):
        super().setUp()
        self.hand_to_partner()

    def cluster_session(self, code, invited):
        return self.schedule(
            clusterId=self.cluster.id,
            catalogueItemId=self.item(code).id,
            focusIntervention="enrolment",
            participantsPerSchool=2,
            invitedSchoolIds=[s.id for s in invited],
        )

    def test_a_partner_supported_school_joins_a_cluster_meeting(self):
        result = self.cluster_session("STANDARD_CLUSTER_MEETING", [self.school])

        self.assertTrue(
            ClusterActivityAttendance.objects.filter(
                activity_id=result["id"], school=self.school, invited=True
            ).exists()
        )

    def test_a_partner_supported_school_joins_a_group_training(self):
        result = self.cluster_session("STANDARD_CLUSTER_TRAINING", [self.school])

        self.assertTrue(
            ClusterActivityAttendance.objects.filter(
                activity_id=result["id"], school=self.school, invited=True
            ).exists()
        )

    def badges(self):
        return SchoolPlanningBadgeService.get_for_schools(
            [self.school.id], financial_year=self.fy
        )[self.school.id]

    def test_membership_alone_does_not_mark_the_school_planned(self):
        # The Partner's own In-school Training handover is all it has so far,
        # and a handover is not yet a plan.
        before = self.badges()
        self.assertEqual(before.trainings.total, 0)
        self.assertEqual(before.cluster_meetings.total, 0)

        # A meeting for the rest of the cluster, this school left unticked.
        self.cluster_session("STANDARD_CLUSTER_MEETING", self.members)

        self.assertEqual(self.badges().as_dict(), before.as_dict())

    def test_explicit_selection_updates_the_training_badges(self):
        self.cluster_session("STANDARD_CLUSTER_TRAINING", [self.school])
        self.cluster_session("STANDARD_CLUSTER_MEETING", [self.school])

        badges = self.badges()
        # The training is a training; the meeting is named as a meeting (or
        # counted as training where its catalogue item says so), never lost.
        self.assertEqual(
            badges.trainings.planned_count + badges.cluster_meetings.planned_count, 2
        )
        self.assertGreaterEqual(badges.trainings.planned_count, 1)

    def test_the_cluster_activity_is_on_the_staff_owners_my_plan(self):
        result = self.cluster_session("STANDARD_CLUSTER_TRAINING", [self.school])

        self.assertIn(result["id"], self.my_plan_queryset_ids())

    def test_the_drawer_leaves_partner_schools_unticked_until_chosen(self):
        client = Client()
        client.force_login(self.user)

        html = client.get(
            f"/planning/schedule-modal?cluster_id={self.cluster.id}&action=meeting"
        ).content.decode()
        chosen = client.get(
            f"/planning/schedule-modal?cluster_id={self.cluster.id}&action=meeting"
            f"&school_id={self.school.school_id}"
        ).content.decode()

        def ticked(body, school):
            tag = body.split(f'value="{school.id}"')[1].split(">")[0]
            return "checked" in tag

        self.assertFalse(ticked(html, self.school))
        self.assertTrue(ticked(html, self.members[0]))
        self.assertTrue(ticked(chosen, self.school))
        self.assertEqual(
            partner_supported_members([self.school.id, self.members[0].id]),
            {self.school.id: "Ozeki Foundation"},
        )

    def test_a_role_without_the_cluster_grant_cannot_invite_it(self):
        director = User.objects.create_user(
            email="cd-cluster@edify.org",
            name="CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )

        with self.assertRaises(Forbidden):
            assert_cluster_invitations_allowed([self.school.id], director)
        # Staff-managed members need no grant at all.
        assert_cluster_invitations_allowed([self.members[0].id], director)


# ── My Plan ─────────────────────────────────────────────────────────────────
class MyPlanRoutingTest(PartnerSchoolFixture):
    def setUp(self):
        super().setUp()
        self.hand_to_partner()

    def test_partner_work_is_not_on_the_staff_my_plan(self):
        activity = self.partner_activity(responsible_staff_id=self.staff.id)

        self.assertNotIn(activity.id, self.my_plan_queryset_ids())

    def test_partner_work_is_on_the_partner_my_plan(self):
        activity = self.partner_activity()

        self.assertIn(activity.id, self.my_plan_queryset_ids(self.partner_user))

    def test_another_partners_work_is_not_on_this_partners_my_plan(self):
        other = self.partner_activity(partner_id=self.other_partner.id)

        self.assertNotIn(other.id, self.my_plan_queryset_ids(self.partner_user))

    def test_staff_owned_permitted_work_is_on_the_staff_my_plan(self):
        planned = [
            self.staff_activity(
                "STANDARD_SCHOOL_VISIT_SSA_COLLECTION",
                purposeType="ssa_support",
                ssaCollectionExpected=True,
            )["id"],
            self.schedule(
                schoolId=self.school.school_id,
                catalogueItemId=self.item("STANDARD_STORY_GATHERING_VISIT").id,
                scheduledDate=_at(_later_date(1)).isoformat(),
            )["id"],
            self.schedule(
                schoolId=self.school.school_id,
                catalogueItemId=self.item("STANDARD_DONOR_VISIT").id,
                scheduledDate=_at(_later_date(2)).isoformat(),
            )["id"],
        ]
        for code in ("STANDARD_CLUSTER_MEETING", "STANDARD_CLUSTER_TRAINING"):
            planned.append(
                self.schedule(
                    clusterId=self.cluster.id,
                    catalogueItemId=self.item(code).id,
                    focusIntervention="enrolment",
                    participantsPerSchool=2,
                    invitedSchoolIds=[self.school.id],
                )["id"]
            )

        mine = self.my_plan_queryset_ids()
        for activity_id in planned:
            with self.subTest(activity=activity_id):
                self.assertIn(activity_id, mine)


# ── Planning badges on Partner-supported schools ────────────────────────────
class PlanningBadgesOnPartnerSchoolsTest(PartnerSchoolFixture):
    """The shared Visit and Training Status badges (school_planning_badges)
    counting Partner work where the school is, and the Planning filters and
    Next Activity built on the same buckets (planning_support)."""

    def badges(self):
        return SchoolPlanningBadgeService.get_for_schools(
            [self.school.id], financial_year=self.fy
        )[self.school.id]

    def labels(self, chips):
        return [chip["label"] for chip in chips]

    def next_activity(self):
        details = []
        SchoolPlanningBadgeService.get_for_schools(
            [self.school.id], financial_year=self.fy, details=details
        )
        return next_activities(details).get(self.school.id)

    def test_a_waiting_handover_is_named_by_responsible_not_counted(self):
        self.hand_to_partner()

        self.assertEqual(self.badges().trainings.total, 0)
        self.assertEqual(
            self.planning_rows()[self.school.school_id]["responsible"][
                "responsibility_type"
            ],
            "partner",
        )

    def test_a_partner_scheduled_visit_counts_once(self):
        assignment = self.hand_to_partner()
        activity = self.partner_activity()
        PartnerAssignment.objects.filter(id=assignment.id).update(
            status="partner_scheduled", scheduled_activity=activity
        )

        badges = self.badges()
        self.assertEqual(badges.visits.planned_count, 1)
        self.assertEqual(self.labels(badges.visit_chips), ["1 Planned"])
        self.assertEqual(badges.trainings.total, 0)

    def test_next_activity_names_the_partner_visit(self):
        self.partner_activity()

        upcoming = self.next_activity()

        self.assertEqual(upcoming["label"], "Partner School Visit")
        self.assertEqual(upcoming["date"], _schedulable_date())

    def test_next_activity_ignores_a_past_plan(self):
        self.partner_activity(
            planned_date=timezone.localdate() - datetime.timedelta(days=3)
        )

        self.assertEqual(self.badges().visits.planned_count, 1)
        self.assertIsNone(self.next_activity())

    def test_submitted_work_is_not_green(self):
        self.partner_activity(status="awaiting_ia_verification")

        chips = self.badges().visit_chips
        self.assertEqual(self.labels(chips), ["1 Awaiting Verification"])
        self.assertEqual(chips[0]["tone"], "awaiting")

    def test_only_ia_verified_work_is_complete(self):
        self.partner_activity(status="ia_verified", ia_verification_status="confirmed")
        self.partner_activity(status="completed")

        visits = self.badges().visits
        self.assertEqual(visits.verified_count, 1)
        self.assertEqual(visits.awaiting_verification_count, 1)

    def test_cancelled_and_returned_assignments_stop_counting(self):
        self.partner_activity(status="cancelled")
        assignment = self.hand_to_partner()
        PartnerAssignment.objects.filter(id=assignment.id).update(
            status=PartnerAssignment.STATUS_RETURNED_TO_STAFF
        )

        badges = self.badges()
        self.assertEqual(badges.visits.total, 0)
        self.assertEqual(badges.trainings.total, 0)
        self.assertEqual(self.labels(badges.visit_chips), ["Not Planned"])

    def test_returned_work_needs_replanning(self):
        self.partner_activity(status="returned")

        self.assertEqual(self.labels(self.badges().visit_chips), ["1 Needs Replanning"])

    def test_several_legitimate_activities_are_all_counted(self):
        self.staff_activity("STANDARD_DONOR_VISIT")
        self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_STORY_GATHERING_VISIT").id,
            scheduledDate=_at(_later_date(1)).isoformat(),
        )
        self.partner_activity(status="ia_verified", ia_verification_status="confirmed")

        self.assertEqual(
            self.labels(self.badges().visit_chips), ["2 Planned", "1 Complete"]
        )

    def test_the_badges_never_block_further_planning(self):
        self.hand_to_partner()
        self.staff_activity("STANDARD_DONOR_VISIT")
        self.assertEqual(self.badges().visits.planned_count, 1)

        again = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_DONOR_VISIT").id,
            scheduledDate=_at(_later_date(4)).isoformat(),
        )

        self.assertTrue(Activity.objects.filter(id=again["id"]).exists())

    def test_an_exact_duplicate_submission_is_blocked(self):
        payload = {
            "schoolId": self.school.school_id,
            "catalogueItemId": self.item("STANDARD_DONOR_VISIT").id,
            "responsibleStaffId": self.staff.id,
        }
        self.schedule(**payload)

        with self.assertRaisesMessage(BadRequest, "identical activity"):
            self.schedule(**payload)
        self.assertEqual(Activity.objects.filter(school=self.school).count(), 1)

    def test_the_filters_agree_with_the_badges(self):
        self.hand_to_partner()
        self.staff_activity("STANDARD_DONOR_VISIT")
        base = School.objects.filter(school_id__startswith="STD-")

        def codes(key):
            return set(
                filter_queryset(base, key, fy=self.fy, principal=self.user).values_list(
                    "school_id", flat=True
                )
            )

        self.assertEqual(codes("partner_support"), {"STD-001"})
        self.assertNotIn("STD-001", codes("staff_managed"))
        self.assertIn("STD-001", codes("my_scheduled_visits"))
        self.assertNotIn("STD-001", codes("visit_not_planned"))
        self.assertIn("STD-MEM-0", codes("visit_not_planned"))
        # The handover is not a plan, so the training is still to plan.
        self.assertIn("STD-001", codes("training_not_planned"))
        self.assertNotIn("STD-001", codes("both_planned"))
        self.assertEqual(codes("completed"), set())

        self.partner_activity(activity_type="in_school_training")
        self.assertIn("STD-001", codes("both_planned"))
        self.assertNotIn("STD-001", codes("training_not_planned"))
        self.assertEqual(len(PLANNING_SUPPORT_FILTERS), 10)

    def test_the_status_filters_follow_the_badge_buckets(self):
        base = School.objects.filter(school_id__startswith="STD-")

        def codes(key):
            return set(
                filter_queryset(base, key, fy=self.fy).values_list(
                    "school_id", flat=True
                )
            )

        for status, key in (
            ("awaiting_ia_verification", "awaiting_verification"),
            ("ia_verified", "completed"),
            ("returned_by_ia", "needs_replanning"),
        ):
            with self.subTest(status=status):
                activity = self.partner_activity(status=status)
                self.assertEqual(codes(key), {"STD-001"})
                activity.delete()
                self.assertEqual(codes(key), set())

    def test_a_cluster_session_counts_only_for_the_schools_invited(self):
        self.schedule(
            clusterId=self.cluster.id,
            catalogueItemId=self.item("STANDARD_CLUSTER_TRAINING").id,
            focusIntervention="enrolment",
            participantsPerSchool=2,
            invitedSchoolIds=[self.school.id],
        )
        base = School.objects.filter(school_id__startswith="STD-")
        planned = set(
            filter_queryset(base, "training_not_planned", fy=self.fy).values_list(
                "school_id", flat=True
            )
        )

        self.assertNotIn("STD-001", planned)
        self.assertTrue({m.school_id for m in self.members} <= planned)

    def test_indicators_render_only_on_planning_and_the_cluster_list(self):
        """The two pages the owner named, and no other template."""
        templates = ROOT / "templates"
        partials = (
            "partials/planning/support_fields.html",
            "partials/planning/support_cells.html",
        )
        including = sorted(
            name
            for path in templates.rglob("*.html")
            if (name := str(path.relative_to(templates))) not in partials
            and any(partial in path.read_text() for partial in partials)
        )
        self.assertEqual(
            including,
            [
                # The Cluster School List: the cluster profile's table and the
                # roster partial the cluster directory expands.
                "pages/clusters/detail.html",
                "partials/clusters/cluster_schools_table.html",
                # The Planning page's school row.
                "partials/planning/school_row.html",
            ],
        )
        # The Partner fields draw no second set of Visit or Training counts:
        # those are the shared badges' alone.
        for partial in partials:
            with self.subTest(partial=partial):
                body = (templates / partial).read_text()
                self.assertNotIn("data-visit-indicator", body)
                self.assertNotIn("data-training-indicator", body)

    def test_my_plan_and_the_directory_carry_no_partner_planning_fields(self):
        self.hand_to_partner()
        client = Client()
        client.force_login(self.user)

        for url in ("/my-plan", "/schools", f"/schools/{self.school.id}"):
            with self.subTest(url=url):
                body = client.get(url).content.decode()
                self.assertNotIn("data-planning-support", body)
                self.assertNotIn("data-next-activity", body)


# ── Finance and achievement ─────────────────────────────────────────────────
class FinanceAndAchievementTest(PartnerSchoolFixture):
    def line(self, activity, amount=50_000):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="test_line",
            label="Test line",
            unit_cost=amount,
            quantity=1,
            amount=amount,
        )

    def test_partner_work_never_enters_a_staff_fund_request(self):
        from apps.fund_requests.fundable import fundable_lines

        partner_line = self.line(self.partner_activity())
        staff = Activity.objects.get(
            id=self.staff_activity("STANDARD_DONOR_VISIT")["id"]
        )
        Activity.objects.filter(id=staff.id).update(cost_missing=False)
        staff_line = self.line(staff)

        fundable = set(
            fundable_lines(ActivityScheduleCostLine.objects.all()).values_list(
                "id", flat=True
            )
        )
        self.assertNotIn(partner_line.id, fundable)
        self.assertIn(staff_line.id, fundable)

    def test_the_partner_path_and_the_staff_path_stay_apart(self):
        partner = self.partner_activity()
        staff = Activity.objects.get(
            id=self.staff_activity("STANDARD_DONOR_VISIT")["id"]
        )

        self.assertEqual(
            (partner.delivery_type, partner.executor_type), ("partner", "partner")
        )
        self.assertEqual((staff.delivery_type, staff.executor_type), ("staff", "staff"))
        self.assertIsNone(staff.assigned_partner_id)

    def test_partner_delivery_is_never_a_staff_target_credit(self):
        from apps.targets.models import TargetAchievementLedger
        from apps.targets.my_targets import TargetAchievementService

        partner = self.partner_activity(
            status="ia_verified",
            ia_verification_status="confirmed",
            responsible_staff_id=self.staff.id,
            salesforce_activity_id="SVE-OZEKI-1",
        )

        TargetAchievementService.rebuild(self.user, self.fy)

        self.assertFalse(
            TargetAchievementLedger.objects.filter(source_id=partner.id).exists()
        )

    def test_a_refused_plan_creates_no_activity_and_no_cost(self):
        self.hand_to_partner()
        before = (Activity.objects.count(), ActivityScheduleCostLine.objects.count())

        with self.assertRaises(BadRequest):
            self.staff_activity("STANDARD_SCHOOL_VISIT", focusIntervention="leadership")

        self.assertEqual(
            before,
            (Activity.objects.count(), ActivityScheduleCostLine.objects.count()),
        )

    def test_one_handover_is_one_assignment_and_no_activity(self):
        self.hand_to_partner()

        self.assertEqual(
            PartnerAssignment.objects.filter(school=self.school).count(), 1
        )
        self.assertFalse(Activity.objects.filter(school=self.school).exists())


# ── Performance ─────────────────────────────────────────────────────────────
class QueryCountTest(PartnerSchoolFixture):
    def _schools(self, n, prefix):
        schools = []
        for i in range(n):
            school = School.objects.create(
                school_id=f"{prefix}-{i}",
                name=f"{prefix} School {i}",
                region=self.region,
                district=self.district,
                school_type="client",
                account_owner_id=self.staff.id,
            )
            self.hand_to_partner(school=school)
            self.partner_activity(school=school)
            schools.append(school)
        return schools

    def _count(self, fn):
        with CaptureQueriesContext(connection) as ctx:
            fn()
        return len(ctx.captured_queries)

    def test_the_resolver_is_constant_in_the_number_of_schools(self):
        few = self._schools(3, "QF")
        many = self._schools(12, "QM")

        small = self._count(lambda: SchoolSupportResponsibilityService.resolve(few))
        large = self._count(lambda: SchoolSupportResponsibilityService.resolve(many))

        self.assertEqual(small, large)
        self.assertLessEqual(large, 4)

    def test_next_activity_is_constant_in_the_number_of_schools(self):
        few = [s.id for s in self._schools(3, "BF")]
        many = [s.id for s in self._schools(12, "BM")]

        def upcoming(ids):
            details = []
            SchoolPlanningBadgeService.get_for_schools(
                ids, financial_year=self.fy, details=details
            )
            return next_activities(details)

        # The badge service's three reads, and one to name Partner work.
        with self.assertNumQueries(4):
            self.assertEqual(len(upcoming(few)), 3)
        with self.assertNumQueries(4):
            self.assertEqual(len(upcoming(many)), 12)

    def test_a_planning_page_costs_the_same_with_more_partner_schools(self):
        from apps.planning.planning_service import PlanningDashboardService

        from apps.core.request_cache import scoped

        def page():
            # Inside a request scope, as the page runs: the SSA readiness each
            # row shows is primed once per page from that store.
            with scoped():
                PlanningDashboardService.get_dashboard_data(
                    self.user,
                    {"fy": self.fy, "tab": "client", "page": 1, "per_page": 50},
                )

        StaffSchoolAssignment.objects.bulk_create(
            StaffSchoolAssignment(staff=self.staff, school_id=s.id)
            for s in self._schools(2, "PF")
        )
        School.objects.filter(school_id__startswith="PF-").update(
            cluster_id=self.cluster.id, cluster_status="clustered"
        )
        small = self._count(page)
        StaffSchoolAssignment.objects.bulk_create(
            StaffSchoolAssignment(staff=self.staff, school_id=s.id)
            for s in self._schools(8, "PM")
        )
        School.objects.filter(school_id__startswith="PM-").update(
            cluster_id=self.cluster.id, cluster_status="clustered"
        )
        large = self._count(page)

        self.assertEqual(small, large)
