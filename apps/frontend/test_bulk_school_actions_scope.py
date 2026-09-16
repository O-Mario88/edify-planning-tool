"""The three /schools bulk write endpoints must respect object scope.

`require_page_permission("school_directory")` answers one question: may this
role open the School Directory. Six of the eleven roles may, including CCEO.
It says nothing about *which* schools, and two of the three bulk endpoints
went straight to `School.objects.filter(id__in=school_ids)` — so the set of
schools a caller could act on was the set of ids they were willing to type,
not the set they own.

Only bulk-match-staff was actually exploitable, and it is the worst one to
lose: account ownership is the root of the scoping chain, writing
StaffSchoolAssignment, which is what resolve_user_scope reads to decide
planning, targets and budget scope. A CCEO posting ids they had no
relationship to could move any school in the country onto any staff profile.
bulk-assign-project read the same unscoped queryset. It used to be unreachable
— the projects service refused any project the caller did not run, before
school scope was ever consulted — so it was hardened for consistency rather
than because it leaked. Since 2026-09-16 the school's own owner may enrol it
in any open project, which makes this view's own scope constraint the only
guard, and the test below exercises it.

The single-school paths in school_views were never affected — school_edit,
change-type and add-to-cluster all go through get_scoped_object_or_404 or
school_queryset. Only the bulk paths skipped it, and none of the three had a
single test, which is why it survived.

Each test posts one in-scope id and one out-of-scope id in the same request:
the in-scope half must still work, or a "fix" that simply refuses everything
would pass.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

User = get_user_model()


class BulkSchoolActionsRespectScopeTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Bulk Region")
        self.district = District.objects.create(
            name="Bulk District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Bulk Sub", district=self.district
        )

        # The actor: a CCEO, the least-privileged role that can reach these
        # endpoints at all.
        self.cceo = User.objects.create(
            id="bulk-cceo",
            email="bulk-cceo@edify.org",
            name="Bulk CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.cceo_sp = StaffProfile.objects.create(
            id="bulk-cceo-sp", user=self.cceo, title="CCEO"
        )

        # An unrelated colleague, in no supervisory relationship with the actor.
        self.other = User.objects.create(
            id="bulk-other",
            email="bulk-other@edify.org",
            name="Bulk Other",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.other_sp = StaffProfile.objects.create(
            id="bulk-other-sp", user=self.other, title="CCEO"
        )

        self.mine = self._school("BULK-MINE", "Bulk Mine", self.cceo_sp)
        self.theirs = self._school("BULK-THEIRS", "Bulk Theirs", self.other_sp)

        self.client.force_login(self.cceo)

    def _school(self, school_id, name, owner):
        school = School.objects.create(
            school_id=school_id,
            name=name,
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            account_owner_id=owner.id,
            account_owner_name_raw=owner.user.name,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.get_or_create(staff=owner, school_id=school.id)
        return school

    def test_bulk_match_staff_cannot_reassign_a_school_outside_scope(self):
        response = self.client.post(
            "/schools/bulk-match-staff",
            {
                "school_ids": f"{self.mine.id},{self.theirs.id}",
                "staff_id": self.cceo_sp.id,
            },
        )
        self.assertEqual(response.status_code, 302)

        self.theirs.refresh_from_db()
        self.assertEqual(
            self.theirs.account_owner_id,
            self.other_sp.id,
            "a school outside the actor's scope must keep its owner",
        )
        self.assertFalse(
            StaffSchoolAssignment.objects.filter(
                staff=self.cceo_sp, school_id=self.theirs.id
            ).exists(),
            "no assignment may be written for an out-of-scope school",
        )

    def test_bulk_match_staff_still_works_for_a_school_in_scope(self):
        # Guards against a fix that just refuses everything.
        self.client.post(
            "/schools/bulk-match-staff",
            {
                "school_ids": f"{self.mine.id},{self.theirs.id}",
                "staff_id": self.other_sp.id,
            },
        )
        self.mine.refresh_from_db()
        self.assertEqual(
            self.mine.account_owner_id,
            self.other_sp.id,
            "the in-scope half of the request must still be applied",
        )

    def test_bulk_assign_project_cannot_reach_a_school_outside_scope(self):
        """This test used to be impossible to write honestly.

        `assign_school` refused any project the caller did not run before
        school scope was consulted, so a view-level test passed on the
        service's refusal whether or not this view scoped anything. Now that
        the school's own owner enrols it (owner, 2026-09-16), the view's
        `school_queryset(..., direct_only=True)` is the only thing standing
        between a typed id and another CCEO's school.
        """
        from apps.projects.models import Project, ProjectSchoolAssignment

        project = Project.objects.create(
            name="Bulk Project",
            code="SP-BULK-1",
            category="intervention_specific",
            status="active",
        )
        self.client.post(
            "/schools/bulk-assign-project",
            {
                "school_ids": f"{self.mine.id},{self.theirs.id}",
                "project_id": project.id,
                "override_reason": "Cohort pilot",
            },
        )
        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(
                project=project, school=self.theirs
            ).exists(),
            "an out-of-scope school must not be enrolled by another actor",
        )
        # The in-scope half still lands, or a "fix" that refuses everything
        # would pass.
        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(
                project=project, school=self.mine
            ).exists(),
            "the actor's own school must still be enrolled",
        )

    def test_bulk_assign_cluster_cannot_reach_a_school_outside_scope(self):
        from apps.clusters.models import Cluster

        cluster = Cluster.objects.create(
            name="Bulk Cluster",
            region=self.region,
            district=self.district,
            cluster_type="mixed",
            status="active",
        )
        self.client.post(
            "/schools/bulk-assign-cluster",
            {
                "school_ids": f"{self.mine.id},{self.theirs.id}",
                "cluster_id": cluster.id,
            },
        )
        self.theirs.refresh_from_db()
        self.assertNotEqual(
            self.theirs.cluster_id,
            cluster.id,
            "an out-of-scope school must not be clustered by another actor",
        )
