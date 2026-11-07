"""Add to Project saves while the allocation has room (owner, 2026-11-06:
"project assignment ... is rejecting even when the ceiling is not yet met";
"schools or school is not saved to the project").

Two refusals came with places still left:

* A CCEO the coordinator had given an allocation, with no school in the
  project yet, could not use the project's own Add schools drawer: the
  project was not "theirs" until a school of theirs was in it, so the drawer
  answered "You do not manage this project". An allocation now makes the
  project the holder's to fill.
* A Programme Lead adding a supervised CCEO's school was charged to the PL's
  own allocation — which a PL usually does not have — although the CCEO's had
  room. A school added for a team member now takes a place from that school's
  officer's allocation when they hold one on the project, and from the
  adder's otherwise, as before.
"""

from __future__ import annotations

from apps.accounts.models import StaffSupervisorAssignment
from apps.projects import capacity
from apps.projects.models import ProjectSchoolAssignment
from apps.projects.scoping import scoped_projects
from apps.projects.test_project_capacity import _Fixture


class _Allocated(_Fixture):
    def setUp(self):
        super().setUp()
        self.allow(10)
        self.pl_user, self.pl = self._user("cap-pl", "Program Lead", "Cap Lead")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl, supervisee=self.cceo
        )

    def enrolled(self):
        return ProjectSchoolAssignment.objects.filter(project=self.project)

    def drawer_post(self, schools):
        return self.client.post(
            f"/projects/{self.project.id}/schools/bulk-assign-drawer",
            {"school_ids": [s.id for s in schools], "reason": "Cohort."},
            HTTP_HX_REQUEST="true",
        )


class AnAllocationOpensTheProjectTest(_Allocated):
    def test_the_holder_reads_the_project_before_adding_any_school(self):
        self.assertIn(self.project, list(scoped_projects(self.cceo_user)))

    def test_the_project_drawer_takes_the_first_schools(self):
        self.client.force_login(self.cceo_user)
        drawer = self.client.get(
            f"/projects/{self.project.id}/schools/bulk-assign-drawer"
        )
        self.assertContains(drawer, "capLeft: 10,")
        self.drawer_post(self.schools[:2])
        self.assertEqual(self.enrolled().count(), 2)
        self.assertEqual(self.held().remaining, 8)


class ALeadAddsForTheirTeamTest(_Allocated):
    def test_the_single_school_drawer_uses_the_officers_place(self):
        self.client.force_login(self.pl_user)
        self.client.post(
            f"/schools/{self.schools[0].id}/assign-to-project",
            {"project_id": self.project.id, "notes": "Cohort."},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(
            list(self.enrolled().values_list("assigned_staff_id", flat=True)),
            [self.cceo.id],
        )
        self.assertEqual(self.held().remaining, 9)

    def test_the_directory_bulk_add_uses_the_officers_places(self):
        self.client.force_login(self.pl_user)
        self.client.post(
            "/schools/bulk-assign-project",
            {
                "project_id": self.project.id,
                "school_ids": ",".join(s.id for s in self.schools[:3]),
                "override_reason": "Cohort.",
            },
        )
        self.assertEqual(self.enrolled().count(), 3)
        self.assertEqual(self.held().remaining, 7)

    def test_the_project_drawer_is_open_to_the_lead_and_saves(self):
        self.client.force_login(self.pl_user)
        drawer = self.client.get(
            f"/projects/{self.project.id}/schools/bulk-assign-drawer"
        )
        self.assertNotContains(drawer, "You have no school allocation")
        self.drawer_post(self.schools[:2])
        self.assertEqual(self.enrolled().count(), 2)
        self.assertEqual(self.held().remaining, 8)

    def test_a_selection_past_the_officers_remaining_places_is_refused_whole(self):
        capacity.set_capacity(
            self.project.id, self.cceo.id, 2, self.coordinator_user, create=False
        )
        self.client.force_login(self.pl_user)
        self.client.post(
            "/schools/bulk-assign-project",
            {
                "project_id": self.project.id,
                "school_ids": ",".join(s.id for s in self.schools[:3]),
                "override_reason": "Cohort.",
            },
        )
        self.assertEqual(self.enrolled().count(), 0)

    def test_an_officer_without_an_allocation_still_needs_one(self):
        # The other CCEO holds no allocation on this managed project, and
        # neither does the lead: the school is refused, as before.
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl, supervisee=self.other
        )
        theirs = self._school("CAP-OTHER", owner=self.other)
        self.client.force_login(self.pl_user)
        self.client.post(
            f"/schools/{theirs.id}/assign-to-project",
            {"project_id": self.project.id, "notes": "Cohort."},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(self.enrolled().count(), 0)

    def test_both_the_officer_and_the_lead_who_added_it_may_withdraw_it(self):
        self.add(self.schools[0], user=self.pl_user)
        enrolment = self.enrolled().get()
        self.assertEqual(enrolment.assigned_staff_id, self.cceo.id)
        self.assertTrue(capacity.may_withdraw(self.cceo_user, enrolment))
        self.assertTrue(capacity.may_withdraw(self.pl_user, enrolment))
        self.assertFalse(capacity.may_withdraw(self.other_user, enrolment))
