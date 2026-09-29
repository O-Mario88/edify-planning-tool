"""Project school capacity (brief, 2026-09-29).

The Project Coordinator sets how many schools each staff member may add to a
project; staff add schools only within it; a school is withdrawn only before
its project work begins, and its place comes back. The service holds the
line, and so does the database, for anything that bypasses the service.
"""

from __future__ import annotations

import threading

from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, ConflictError, Forbidden
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.projects import capacity
from apps.projects import services as project_services
from apps.projects.models import (
    Project,
    ProjectSchoolAssignment,
    ProjectSchoolEnrollmentHistory,
    ProjectStaffCapacity,
)
from apps.schools.models import School

FY = get_operational_fy()


class _World:
    """One coordinated project and a CCEO with twelve schools of their own."""

    def build(self):
        self.region = Region.objects.create(name="Cap Region")
        self.district = District.objects.create(name="Cap District", region=self.region)
        self.coordinator_user, self.coordinator = self._user(
            "cap-pc", "ProjectCoordinator", "Cap Coordinator"
        )
        self.cceo_user, self.cceo = self._user("cap-cceo", "CCEO", "Cap Officer")
        self.other_user, self.other = self._user("cap-cceo2", "CCEO", "Cap Other")
        self.project = Project.objects.create(
            code="CAP-SEL",
            name="Cap CC-SEL",
            category="intervention_specific",
            manager_staff_id=self.coordinator.id,
        )
        self.schools = [self._school(f"CAP-{n:02d}") for n in range(12)]

    def _user(self, uid, role, name):
        user = User.objects.create_user(
            email=f"{uid}@edify.org",
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        profile = StaffProfile.objects.create(
            id=f"{uid}-sp", user=user, title=role, country="Uganda"
        )
        return user, profile

    def _school(self, code, owner=None):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=self.region,
            district=self.district,
            school_type="client",
            account_owner_id=(owner or self.cceo).id,
        )
        StaffSchoolAssignment.objects.create(
            staff=owner or self.cceo, school_id=school.id
        )
        return school

    def add(self, school, user=None):
        return project_services.assign_school(
            self.project.id,
            {"schoolId": school.school_id, "reason": "Selected for the cohort."},
            user or self.cceo_user,
        )

    def allow(self, maximum, staff=None):
        return capacity.set_capacity(
            self.project.id,
            (staff or self.cceo).id,
            maximum,
            self.coordinator_user,
            create=True,
        )


class _Fixture(_World, TestCase):
    def setUp(self):
        self.build()

    def held(self, staff=None):
        return capacity.allocation_for(self.project.id, (staff or self.cceo).id)


class SettingAnAllocationTest(_Fixture):
    def test_the_coordinator_sets_and_changes_it_and_both_are_logged(self):
        allocation = self.allow(10)
        self.assertEqual(
            (allocation.maximum, allocation.assigned, allocation.remaining),
            (10, 0, 10),
        )
        capacity.set_capacity(
            self.project.id, self.cceo.id, 12, self.coordinator_user, create=False
        )
        self.assertEqual(self.held().maximum, 12)
        actions = list(
            AuditLog.objects.filter(action__startswith="project.capacity_")
            .order_by("created_at")
            .values_list("action", flat=True)
        )
        self.assertEqual(
            actions, ["project.capacity_created", "project.capacity_changed"]
        )

    def test_it_must_be_a_positive_whole_number(self):
        for value in ("0", "-3", "abc", "", "2.5"):
            with self.subTest(value=value), self.assertRaises(BadRequest):
                self.allow(value)

    def test_a_second_allocation_for_the_same_pair_is_refused(self):
        self.allow(10)
        with self.assertRaisesMessage(BadRequest, "Edit that allocation"):
            self.allow(20)
        self.assertEqual(ProjectStaffCapacity.objects.count(), 1)

    def test_only_eligible_staff_can_hold_one(self):
        with self.assertRaises(BadRequest):
            self.allow(10, staff=self.coordinator)

    def test_a_staff_member_cannot_set_their_own(self):
        with self.assertRaises(Forbidden):
            capacity.set_capacity(
                self.project.id, self.cceo.id, 99, self.cceo_user, create=True
            )

    def test_another_coordinator_cannot_set_one(self):
        stranger_user, _ = self._user("cap-pc2", "ProjectCoordinator", "Stranger")
        with self.assertRaises(Forbidden):
            capacity.set_capacity(
                self.project.id, self.cceo.id, 5, stranger_user, create=True
            )

    def test_case_10_it_cannot_drop_below_what_is_assigned(self):
        self.allow(5)
        for school in self.schools[:4]:
            self.add(school)
        with self.assertRaisesMessage(
            BadRequest,
            "Capacity cannot be reduced below the current number of assigned "
            "schools. Current assignment: 4.",
        ):
            capacity.set_capacity(
                self.project.id, self.cceo.id, 3, self.coordinator_user, create=False
            )
        self.assertEqual(self.held().maximum, 5)
        self.assertEqual(ProjectSchoolAssignment.objects.count(), 4)


class AddingWithinTheAllocationTest(_Fixture):
    def test_case_1_an_empty_allocation_takes_all_its_places(self):
        self.allow(10)
        for school in self.schools[:10]:
            self.add(school)
        self.assertEqual(self.held().assigned, 10)
        self.assertEqual(self.held().status, "full")

    def test_case_2_and_3_the_last_place_then_none(self):
        self.allow(10)
        for school in self.schools[:9]:
            self.add(school)
        self.assertEqual(self.held().remaining, 1)
        self.assertEqual(self.held().status, "near")
        self.add(self.schools[9])
        with self.assertRaisesMessage(BadRequest, "Project capacity reached"):
            self.add(self.schools[10])
        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(school=self.schools[10]).exists()
        )

    def test_a_managed_project_refuses_staff_without_an_allocation(self):
        self.allow(10, staff=self.other)
        with self.assertRaisesMessage(Forbidden, "no school allocation"):
            self.add(self.schools[0])

    def test_an_unmanaged_project_works_as_before(self):
        self.add(self.schools[0])
        row = ProjectSchoolAssignment.objects.get(school=self.schools[0])
        self.assertEqual(row.assigned_staff_id, self.cceo.id)

    def test_a_country_role_adds_without_using_anybodys_places(self):
        ia_user, _ = self._user("cap-ia", "ImpactAssessment", "Cap IA")
        self.allow(1)
        self.add(self.schools[0], user=ia_user)
        self.assertIsNone(
            ProjectSchoolAssignment.objects.get(school=self.schools[0]).assigned_staff
        )
        self.assertEqual(self.held().assigned, 0)

    def test_adding_the_same_school_twice_uses_one_place(self):
        self.allow(3)
        self.add(self.schools[0])
        self.add(self.schools[0])
        self.assertEqual(self.held().assigned, 1)
        self.assertEqual(
            AuditLog.objects.filter(action="project.school_added").count(), 1
        )

    def test_case_9_the_api_refuses_past_the_allocation(self):
        self.allow(1)
        self.add(self.schools[0])
        self.client.force_login(self.cceo_user)
        response = self.client.post(
            f"/api/special-projects/{self.project.id}/schools",
            {"schoolId": self.schools[1].school_id, "reason": "Forced."},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.held().assigned, 1)

    def test_a_batch_larger_than_what_remains_is_refused_whole(self):
        self.allow(3)
        self.add(self.schools[0])
        with self.assertRaisesMessage(
            BadRequest, "You can add a maximum of 2 more schools"
        ):
            capacity.assert_batch_fits(self.project, self.cceo.id, 3)
        capacity.assert_batch_fits(self.project, self.cceo.id, 2)


class TheDatabaseHoldsTheLineTest(_Fixture):
    """Case 9, the way round the service: a raw write still cannot overfill
    an allocation or shrink it below what it holds."""

    def test_a_direct_insert_past_the_allocation_is_refused(self):
        self.allow(1)
        self.add(self.schools[0])
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProjectSchoolAssignment.objects.create(
                project=self.project, school=self.schools[1], assigned_staff=self.cceo
            )

    def test_a_direct_update_below_what_is_held_is_refused(self):
        self.allow(2)
        self.add(self.schools[0])
        self.add(self.schools[1])
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE project_staff_capacity SET max_schools = 1 "
                    "WHERE project_id = %s",
                    [self.project.id],
                )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProjectStaffCapacity.objects.filter(project=self.project).update(
                max_schools=0
            )


class WithdrawingASchoolTest(_Fixture):
    def withdraw(self, school, user=None, code="reallocation", text=""):
        return project_services.remove_school(
            self.project.id,
            school.school_id,
            user or self.cceo_user,
            reason=text,
            reason_code=code,
        )

    def plan(self, school, status="scheduled", evidence_status="none"):
        return Activity.objects.create(
            activity_type="school_visit",
            school=school,
            project_id=self.project.id,
            fy=FY,
            quarter="Q1",
            planned_date=timezone.localdate(),
            status=status,
            evidence_status=evidence_status,
            responsible_staff_id=self.cceo.id,
            delivery_type="staff",
        )

    def test_case_4_the_place_comes_back_and_the_history_stays(self):
        self.allow(10)
        for school in self.schools[:10]:
            self.add(school)
        self.assertEqual(self.held().remaining, 0)

        self.withdraw(self.schools[0])

        self.assertEqual((self.held().assigned, self.held().remaining), (9, 1))
        history = ProjectSchoolEnrollmentHistory.objects.get(school=self.schools[0])
        self.assertEqual(history.assigned_staff_id, self.cceo.id)
        self.assertEqual(history.added_by, self.cceo_user.id)
        self.assertEqual(history.removed_by, self.cceo_user.id)
        self.assertEqual(history.removal_reason, "Staff capacity reallocation")
        log = AuditLog.objects.get(action="project.school_withdrawn")
        self.assertEqual(log.reason, "Staff capacity reallocation")
        # The freed place takes another school.
        self.add(self.schools[10])
        self.assertEqual(self.held().remaining, 0)

    def test_cases_5_to_7_work_that_has_begun_blocks_it(self):
        self.allow(10)
        cases = [
            ("scheduled", "none", "planned project activity"),
            ("in_progress", "none", "already started"),
            ("evidence_uploaded", "uploaded", "Evidence has already been submitted"),
            ("completed", "accepted", "already been completed"),
        ]
        for n, (status, evidence, message) in enumerate(cases):
            school = self.schools[n]
            self.add(school)
            self.plan(school, status, evidence)
            with self.subTest(status=status):
                with self.assertRaisesMessage(ConflictError, message):
                    self.withdraw(school)
                with self.assertRaisesMessage(ConflictError, message):
                    self.withdraw(school, user=self.coordinator_user)
                self.assertTrue(
                    ProjectSchoolAssignment.objects.filter(school=school).exists()
                )

    def test_cancelled_work_does_not_block_it(self):
        self.allow(10)
        self.add(self.schools[0])
        self.plan(self.schools[0], "cancelled")
        self.withdraw(self.schools[0])
        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(school=self.schools[0]).exists()
        )

    def test_other_needs_its_own_words(self):
        self.allow(10)
        self.add(self.schools[0])
        with self.assertRaisesMessage(BadRequest, "Say why"):
            self.withdraw(self.schools[0], code="other")
        self.withdraw(self.schools[0], code="other", text="Merged with a neighbour.")
        self.assertEqual(
            ProjectSchoolEnrollmentHistory.objects.get().removal_reason,
            "Other: Merged with a neighbour.",
        )

    def test_another_officer_cannot_withdraw_it(self):
        self.allow(10)
        self.add(self.schools[0])
        with self.assertRaises(Forbidden):
            self.withdraw(self.schools[0], user=self.other_user)


class TheRaceForTheLastPlaceTest(_World, TransactionTestCase):
    """Case 8: two sessions add a school each when one place is left."""

    def setUp(self):
        self.build()

    def test_two_concurrent_additions_never_overfill(self):
        self.allow(10)
        for school in self.schools[:9]:
            self.add(school)
        barrier = threading.Barrier(2)
        outcomes = []

        def attempt(school):
            try:
                barrier.wait(timeout=5)
                self.add(school)
                outcomes.append("added")
            except (BadRequest, IntegrityError) as exc:
                outcomes.append(type(exc).__name__)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=attempt, args=(school,))
            for school in self.schools[9:11]
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(sorted(outcomes), ["BadRequest", "added"])
        self.assertEqual(
            ProjectSchoolAssignment.objects.filter(assigned_staff=self.cceo).count(),
            10,
        )


class TheCapacityPagesTest(_Fixture):
    def test_the_coordinator_sees_one_section_per_project_with_staff_names(self):
        second = Project.objects.create(
            code="CAP-ET",
            name="Cap EdTech",
            category="intervention_specific",
            manager_staff_id=self.coordinator.id,
        )
        self.allow(3)
        capacity.set_capacity(
            second.id, self.other.id, 5, self.coordinator_user, create=True
        )
        self.add(self.schools[0])
        self.client.force_login(self.coordinator_user)

        page = self.client.get("/projects/capacity")

        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertEqual(body.count("data-capacity-project="), 2)
        self.assertIn("Cap Officer", body)
        self.assertIn("Cap Other", body)
        self.assertIn("1 / 3 allocated", body)
        self.assertIn("33.3%", body)

    def test_staff_cannot_open_it(self):
        self.client.force_login(self.cceo_user)
        page = self.client.get("/projects/capacity")
        self.assertNotEqual(page.status_code, 200)

    def test_the_set_drawer_lists_eligible_staff_and_saves(self):
        self.client.force_login(self.coordinator_user)
        drawer = self.client.get(f"/projects/capacity/set?project={self.project.id}")
        self.assertContains(drawer, "Cap Officer")
        self.assertNotContains(drawer, "Cap Coordinator</option>")

        saved = self.client.post(
            "/projects/capacity/set",
            {
                "project_id": self.project.id,
                "staff_id": self.cceo.id,
                "max_schools": "4",
                "save": "1",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(
            saved["HX-Redirect"], f"/projects/capacity?project={self.project.id}"
        )
        self.assertEqual(self.held().maximum, 4)

        again = self.client.post(
            "/projects/capacity/set",
            {
                "project_id": self.project.id,
                "staff_id": self.cceo.id,
                "max_schools": "6",
                "save": "1",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(again, "Edit that allocation")
        self.assertEqual(self.held().maximum, 4)

    def test_the_edit_drawer_refuses_going_below_what_is_held(self):
        allocation = self.allow(2)
        self.add(self.schools[0])
        self.add(self.schools[1])
        self.client.force_login(self.coordinator_user)
        url = f"/projects/capacity/{allocation.capacity_id}/edit"
        self.assertContains(self.client.get(url), "Currently assigned")

        response = self.client.post(url, {"max_schools": "1"}, HTTP_HX_REQUEST="true")

        self.assertContains(response, "Current assignment: 2.")
        self.assertEqual(self.held().maximum, 2)

    def test_the_staff_member_sees_their_allocation_and_withdraws(self):
        self.allow(2)
        self.add(self.schools[0])
        self.client.force_login(self.cceo_user)

        page = self.client.get("/projects/monitoring")
        self.assertContains(page, "My project allocations")
        self.assertContains(page, "Your allocation: 1 of 2 used")
        enrolment = ProjectSchoolAssignment.objects.get(school=self.schools[0])
        self.assertContains(
            page, f"/projects/capacity/withdraw?enrolment={enrolment.id}"
        )

        drawer = self.client.get(
            f"/projects/capacity/withdraw?enrolment={enrolment.id}"
        )
        self.assertContains(drawer, "can be withdrawn")

        done = self.client.post(
            "/projects/capacity/withdraw",
            {"enrolment": enrolment.id, "reason_code": "duplicate"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(done.status_code, 204)
        self.assertEqual(self.held().assigned, 0)

    def test_the_withdraw_drawer_says_why_it_is_blocked(self):
        self.allow(2)
        self.add(self.schools[0])
        Activity.objects.create(
            activity_type="school_visit",
            school=self.schools[0],
            project_id=self.project.id,
            fy=FY,
            quarter="Q1",
            planned_date=timezone.localdate(),
            status="in_progress",
            responsible_staff_id=self.cceo.id,
            delivery_type="staff",
        )
        enrolment = ProjectSchoolAssignment.objects.get(school=self.schools[0])
        self.client.force_login(self.cceo_user)

        drawer = self.client.get(
            f"/projects/capacity/withdraw?enrolment={enrolment.id}"
        )

        self.assertContains(drawer, 'data-leave-blocked="started"')
        self.assertNotContains(drawer, "Withdraw School</button>")

    def test_another_officer_cannot_open_the_withdraw_drawer(self):
        self.allow(2)
        self.add(self.schools[0])
        enrolment = ProjectSchoolAssignment.objects.get(school=self.schools[0])
        self.client.force_login(self.other_user)
        drawer = self.client.get(
            f"/projects/capacity/withdraw?enrolment={enrolment.id}"
        )
        self.assertEqual(drawer.status_code, 404)

    def test_the_add_to_project_drawer_shows_a_full_allocation(self):
        self.allow(1)
        self.add(self.schools[0])
        self.client.force_login(self.cceo_user)
        drawer = self.client.get(f"/schools/{self.schools[1].id}/assign-to-project")
        self.assertContains(drawer, 'data-max="1" data-used="1" data-left="0"')
        self.assertContains(drawer, "You have reached your allocation of 1 schools")

    def test_the_bulk_paths_refuse_a_selection_larger_than_what_is_left(self):
        self.allow(3)
        self.add(self.schools[0])
        self.client.force_login(self.cceo_user)
        self.client.post(
            "/schools/bulk-assign-project",
            {
                "project_id": self.project.id,
                "school_ids": ",".join(s.id for s in self.schools[1:4]),
                "override_reason": "Cohort.",
            },
        )
        self.assertEqual(ProjectSchoolAssignment.objects.count(), 1)
        drawer = self.client.get(
            f"/projects/{self.project.id}/schools/bulk-assign-drawer"
        )
        self.assertContains(drawer, "capLeft: 2,")
        self.client.post(
            f"/projects/{self.project.id}/schools/bulk-assign-drawer",
            {"school_ids": [s.id for s in self.schools[1:4]], "reason": "Cohort."},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(ProjectSchoolAssignment.objects.count(), 1)
        self.client.post(
            f"/projects/{self.project.id}/schools/bulk-assign-drawer",
            {"school_ids": [s.id for s in self.schools[1:3]], "reason": "Cohort."},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(ProjectSchoolAssignment.objects.count(), 3)
