"""Undo a planning change made by mistake (owner, 2026-09-28).

"can you create a function for users to undo plans done by mistake. for
example if a user assign schools to partner they are not supposed to assign
can you make sure the actions can be reversed." And: "Same with assigning to
project, adding a school to clusters".

These hold the three undos — a partner handover, a project school, a cluster
move — the limits that keep an undo an undo (the person who made it, within a
week, before anything was built on it), and the two doors: the Undo on a
save's confirmation and the Recent changes drawer on the Planning page.
"""

from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
from apps.audit.models import AuditLog
from apps.clusters.models import Cluster, SchoolClusterMembership
from apps.clusters.services import set_school_cluster_membership
from apps.core.exceptions import ConflictError, NotFoundError
from apps.geography.models import District, Region, SubCounty
from apps.notifications.models import Notification
from apps.partners.models import Partner, PartnerAssignment
from apps.partners.services import create_assignment
from apps.planning import undo as undo_service
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School


class UndoFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(
            email="undo-cceo@edify.org",
            password="password123",
            name="Undo Planner",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.profile = StaffProfile.objects.create(
            id="undo-staff", user=cls.user, title="CCEO"
        )
        cls.other = User.objects.create_user(
            email="undo-other@edify.org",
            password="password123",
            name="Another Planner",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.other_profile = StaffProfile.objects.create(
            id="undo-other", user=cls.other, title="CCEO"
        )
        region = Region.objects.create(name="Undo Region")
        cls.district = District.objects.create(name="Undo District", region=region)
        sub_county = SubCounty.objects.create(name="Undo Sub", district=cls.district)
        cls.school = School.objects.create(
            school_id="UNDO-1",
            name="Undo Primary",
            region=region,
            district=cls.district,
            sub_county=sub_county,
            school_type="client",
            cluster_status="unclustered",
            account_owner_id=cls.profile.id,
        )
        cls.second = School.objects.create(
            school_id="UNDO-2",
            name="Redo Primary",
            region=region,
            district=cls.district,
            sub_county=sub_county,
            school_type="client",
            cluster_status="unclustered",
            account_owner_id=cls.profile.id,
        )
        for school in (cls.school, cls.second):
            StaffSchoolAssignment.objects.create(staff=cls.profile, school_id=school.id)
        cls.cluster_a = Cluster.objects.create(
            name="First Cluster",
            region=region,
            district=cls.district,
            status="active",
            responsible_staff_id=cls.profile.id,
        )
        cls.cluster_b = Cluster.objects.create(
            name="Second Cluster",
            region=region,
            district=cls.district,
            status="active",
            responsible_staff_id=cls.profile.id,
        )
        cls.partner_user = User.objects.create_user(
            email="undo-partner@edify.org",
            password="password123",
            name="Partner User",
            roles=["Partner"],
            active_role="Partner",
            is_active=True,
        )
        cls.partner = Partner.objects.create(
            name="Wrong Partner", user=cls.partner_user
        )
        cls.project = Project.objects.create(name="Reading Project", status="active")

    def handover(self, *, by=None, school=None, **over):
        by = by or self.profile
        fields = {
            "school": school or self.school,
            "partner": self.partner,
            "assigning_staff_id": by.id,
            "monitoring_staff_id": by.id,
            "expected_activity_type": "school_visit",
        }
        fields.update(over)
        return create_assignment(**fields)

    def enrol(self, *, by=None, school=None):
        by = by or self.user
        return ProjectSchoolAssignment.objects.create(
            project=self.project, school=school or self.school, assigned_by=by.id
        )

    def join(self, cluster, *, by=None, school=None):
        by = by or self.user
        school = School.objects.get(pk=(school or self.school).pk)
        set_school_cluster_membership(school, cluster, by.id)
        return SchoolClusterMembership.objects.get(
            school_id=school.id, ended_at__isnull=True
        )

    def age(self, model, pk, days, field="created_at"):
        model.objects.filter(pk=pk).update(
            **{field: timezone.now() - datetime.timedelta(days=days)}
        )


class PartnerHandoverUndoTest(UndoFixture):
    def test_the_assigner_takes_back_a_handover_the_partner_has_not_touched(self):
        handover = self.handover()
        self.assertTrue(
            Notification.objects.filter(
                context_id=handover.id, resolved_at__isnull=True
            ).exists()
        )

        result = undo_service.undo(self.user, "partner", handover.id)

        self.assertIn("Undo Primary assigned to Wrong Partner", result.message)
        self.assertFalse(PartnerAssignment.objects.filter(id=handover.id).exists())
        # The Partner's "New assignment" notice no longer opens onto nothing.
        self.assertFalse(
            Notification.objects.filter(
                context_id=handover.id, resolved_at__isnull=True
            ).exists()
        )
        entry = AuditLog.objects.get(action="partner.assignment_undone")
        self.assertEqual(entry.subject_id, handover.id)
        self.assertEqual(entry.payload["previous"]["partnerId"], self.partner.id)

    def test_the_school_can_be_handed_to_the_right_partner_afterwards(self):
        handover = self.handover()
        undo_service.undo(self.user, "partner", handover.id)
        self.handover()  # the once-per-partner rule no longer sees the mistake

    def test_someone_elses_handover_is_not_yours_to_undo(self):
        handover = self.handover(by=self.other_profile)
        with self.assertRaises(NotFoundError):
            undo_service.undo(self.user, "partner", handover.id)
        self.assertTrue(PartnerAssignment.objects.filter(id=handover.id).exists())

    def test_once_the_partner_has_scheduled_it_it_is_withdrawn_not_undone(self):
        handover = self.handover()
        PartnerAssignment.objects.filter(id=handover.id).update(
            status=PartnerAssignment.STATUS_SCHEDULED
        )
        with self.assertRaises(ConflictError) as caught:
            undo_service.undo(self.user, "partner", handover.id)
        self.assertIn("already scheduled", str(caught.exception))
        self.assertTrue(PartnerAssignment.objects.filter(id=handover.id).exists())

    def test_a_week_later_it_is_a_withdrawal(self):
        handover = self.handover()
        self.age(PartnerAssignment, handover.id, days=8)
        with self.assertRaises(ConflictError) as caught:
            undo_service.undo(self.user, "partner", handover.id)
        self.assertIn("7 days", str(caught.exception))

    def test_a_batch_undoes_what_it_can_and_says_what_it_could_not(self):
        first = self.handover()
        second = self.handover(school=self.second)
        PartnerAssignment.objects.filter(id=second.id).update(
            status=PartnerAssignment.STATUS_SCHEDULED
        )
        done, refused = undo_service.undo_many(
            self.user, "partner", [first.id, second.id]
        )
        self.assertEqual(len(done), 1)
        self.assertEqual(len(refused), 1)
        self.assertFalse(PartnerAssignment.objects.filter(id=first.id).exists())
        self.assertTrue(PartnerAssignment.objects.filter(id=second.id).exists())


class ProjectEnrolmentUndoTest(UndoFixture):
    def test_the_person_who_added_the_school_takes_it_out(self):
        enrolment = self.enrol()
        result = undo_service.undo(self.user, "project", enrolment.id)
        self.assertEqual(result.project_ids, (self.project.id,))
        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(id=enrolment.id).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="project.school_enrolment_undone", subject_id=self.school.id
            ).exists()
        )

    def test_not_once_work_is_planned_under_the_project(self):
        enrolment = self.enrol()
        Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            project_id=self.project.id,
            fy="2026",
            quarter="Q4",
            planned_date=datetime.date(2026, 7, 15),
            status="planned",
            responsible_staff_id=self.profile.id,
            delivery_type="staff",
        )
        with self.assertRaises(ConflictError) as caught:
            undo_service.undo(self.user, "project", enrolment.id)
        self.assertIn("Work is already planned", str(caught.exception))
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(id=enrolment.id).exists()
        )

    def test_nor_while_a_partner_holds_project_work_there(self):
        enrolment = self.enrol()
        self.handover(project=self.project)
        with self.assertRaises(ConflictError) as caught:
            undo_service.undo(self.user, "project", enrolment.id)
        self.assertIn("assigned to a partner", str(caught.exception))

    def test_someone_elses_enrolment_is_not_yours_to_undo(self):
        enrolment = self.enrol(by=self.other)
        with self.assertRaises(NotFoundError):
            undo_service.undo(self.user, "project", enrolment.id)


class ClusterMembershipUndoTest(UndoFixture):
    def test_a_school_added_by_mistake_is_unclustered_again(self):
        membership = self.join(self.cluster_a)
        result = undo_service.undo(self.user, "cluster", membership.id)

        self.assertIn("unclustered again", result.message)
        school = School.objects.get(pk=self.school.pk)
        self.assertIsNone(school.cluster_id)
        self.assertEqual(school.cluster_status, "unclustered")
        membership.refresh_from_db()
        self.assertIsNotNone(membership.ended_at)
        self.assertTrue(membership.end_reason.startswith("Undo:"))

    def test_a_school_moved_by_mistake_goes_back_where_it_was(self):
        self.join(self.cluster_a)
        moved = self.join(self.cluster_b)
        result = undo_service.undo(self.user, "cluster", moved.id)

        self.assertIn("back in First Cluster", result.message)
        self.assertEqual(
            set(result.cluster_ids), {self.cluster_a.id, self.cluster_b.id}
        )
        self.assertEqual(
            School.objects.get(pk=self.school.pk).cluster_id, self.cluster_a.id
        )
        # The restoring membership is not offered back as a change to undo,
        # and the first join closed when the school moved.
        kinds = [c.kind for c in undo_service.recent_changes(self.user)]
        self.assertNotIn("cluster", kinds)

    def test_not_after_the_school_has_moved_again(self):
        first = self.join(self.cluster_a)
        self.join(self.cluster_b, by=self.other)
        with self.assertRaises(NotFoundError):
            undo_service.undo(self.user, "cluster", first.id)
        self.assertEqual(
            School.objects.get(pk=self.school.pk).cluster_id, self.cluster_b.id
        )

    def test_a_previous_cluster_that_has_closed_leaves_the_school_unclustered(self):
        self.join(self.cluster_a)
        moved = self.join(self.cluster_b)
        Cluster.objects.filter(pk=self.cluster_a.pk).update(status="inactive")
        result = undo_service.undo(self.user, "cluster", moved.id)
        self.assertIn("unclustered again", result.message)
        self.assertIsNone(School.objects.get(pk=self.school.pk).cluster_id)


class RecentChangesTest(UndoFixture):
    def test_lists_my_changes_newest_first_with_what_undo_will_do(self):
        handover = self.handover()
        enrolment = self.enrol()
        membership = self.join(self.cluster_a)
        self.age(PartnerAssignment, handover.id, days=2)
        self.age(ProjectSchoolAssignment, enrolment.id, days=1)
        self.handover(by=self.other_profile, school=self.second)

        changes = undo_service.recent_changes(self.user)

        self.assertEqual(
            [(c.kind, c.id) for c in changes],
            [
                ("cluster", membership.id),
                ("project", enrolment.id),
                ("partner", handover.id),
            ],
        )
        self.assertTrue(all(c.can_undo for c in changes))
        self.assertIn("Takes it back from Wrong Partner", changes[2].effect)

    def test_a_change_that_can_no_longer_be_undone_says_why(self):
        handover = self.handover()
        PartnerAssignment.objects.filter(id=handover.id).update(
            status=PartnerAssignment.STATUS_SCHEDULED
        )
        (change,) = undo_service.recent_changes(self.user)
        self.assertFalse(change.can_undo)
        self.assertIn("already scheduled", change.blocked)

    def test_changes_older_than_the_window_are_not_listed(self):
        handover = self.handover()
        self.age(PartnerAssignment, handover.id, days=8)
        self.assertEqual(undo_service.recent_changes(self.user), [])


class UndoDoorsTest(UndoFixture):
    def setUp(self):
        self.client.force_login(self.user)

    def test_the_planning_page_opens_recent_changes(self):
        response = self.client.get("/planning")
        self.assertContains(response, 'hx-get="/planning/recent-changes"')

    def test_the_drawer_lists_my_changes_with_an_undo_each(self):
        handover = self.handover()
        response = self.client.get("/planning/recent-changes")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recent changes")
        self.assertContains(response, "Undo Primary assigned to Wrong Partner")
        self.assertContains(response, 'hx-post="/planning/undo"')
        self.assertContains(response, handover.id)

    def test_the_drawer_says_when_there_is_nothing_to_undo(self):
        response = self.client.get("/planning/recent-changes")
        self.assertContains(response, "Nothing to undo.")

    def test_undo_from_the_drawer_answers_with_the_refreshed_list(self):
        handover = self.handover()
        response = self.client.post(
            "/planning/undo",
            {"kind": "partner", "ids": handover.id, "source": "drawer"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('id="recent-changes-list"', body)
        self.assertIn("Nothing to undo.", body)
        self.assertIn("Undone: Undo Primary assigned to Wrong Partner", body)
        self.assertIn("planning-saved", response["HX-Trigger"])

    def test_undo_from_a_confirmation_replaces_it_and_refreshes_the_pages(self):
        membership = self.join(self.cluster_a)
        response = self.client.post(
            "/planning/undo", {"kind": "cluster", "ids": membership.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-undo-toast")
        self.assertIn(
            f"cluster-schools-updated-{self.cluster_a.id}", response["HX-Trigger"]
        )

    def test_a_refused_undo_says_why_and_refreshes_nothing(self):
        handover = self.handover(by=self.other_profile)
        response = self.client.post(
            "/planning/undo", {"kind": "partner", "ids": handover.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not one you made")
        self.assertNotIn("HX-Trigger", response)
        self.assertTrue(PartnerAssignment.objects.filter(id=handover.id).exists())

    def test_undo_is_a_post(self):
        self.assertEqual(self.client.get("/planning/undo").status_code, 405)

    def test_the_cluster_drawer_confirmation_offers_undo(self):
        response = self.client.post(
            f"/clusters/{self.cluster_a.id}/bulk-assign-drawer",
            {"school_ids": [self.school.id]},
        )
        self.assertEqual(response.status_code, 200)
        membership = SchoolClusterMembership.objects.get(
            school_id=self.school.id, ended_at__isnull=True
        )
        self.assertContains(response, 'hx-post="/planning/undo"')
        self.assertContains(response, membership.id)
