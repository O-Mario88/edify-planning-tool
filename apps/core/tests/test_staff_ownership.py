"""Staff Name ownership + candidate + supervisor + project assignment — tests.

Proves the ownership bridge end-to-end:
  • Upload with Staff Name matching a CCEO → school enters the CCEO's planning
    scope (StaffSchoolAssignment written) + account_owner_status=matched.
  • Upload with an unmatched Staff Name → one StaffSetupCandidate (no duplicate
    on re-upload); Account Owner fallback still works; ambiguous name → AMBIGUOUS.
  • Admin create-user from a candidate → all matching schools re-link + status
    flips to matched; candidate → active.
  • CD assigns a PL as a CCEO's supervisor → the CCEO's schools enter the PL's
    team scope (resolve_user_scope).
  • CD sets a project manager.
  • Upload response reports matched/unmatched/ambiguous counts.
"""

from __future__ import annotations

from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    StaffSetupCandidate,
    User,
)
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.projects.models import Project
from apps.schools.models import School


def _csv(body: str, name="schools.csv"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, body.encode("utf-8"), content_type="text/csv")


class StaffOwnershipTest(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Staff Region")
        self.district = District.objects.create(
            name="Staff District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Staff Sub", district=self.district
        )

        # An IA who performs the upload (has SCHOOL_UPLOAD perm).
        self.ia = self._user(
            "ia@staff.test", EdifyRole.IMPACT_ASSESSMENT.value, "IA Tester"
        )
        StaffProfile.objects.create(user=self.ia, title="IA")
        # A CCEO named "Ojok Amos" — the Staff Name will match this user.
        self.cceo = self._user("ojok@staff.test", EdifyRole.CCEO.value, "Ojok Amos")
        self.cceo_staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        # A PL (supervisor-to-be).
        self.pl = self._user(
            "pl@staff.test", EdifyRole.COUNTRY_PROGRAM_LEAD.value, "Grace PL"
        )
        self.pl_staff = StaffProfile.objects.create(user=self.pl, title="PL")
        # Admin for the staff-candidate + supervisor endpoints.
        self.admin = self._user("admin@staff.test", EdifyRole.ADMIN.value, "Admin User")

    def _user(self, email, role, name):
        return User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )

    def _as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}"
        )

    def _upload(self, csv_body, user=None, update_existing=False):
        self._as(user or self.ia)
        data = {"file": _csv(csv_body)}
        if update_existing:
            data["update_existing"] = "true"
        return self.client.post("/api/schools/upload", data, format="multipart")

    # ── Upload matching ──────────────────────────────────────────────────────
    def test_staff_name_match_creates_school_assignment_and_enters_scope(self):
        """The load-bearing test: a matched Staff Name writes a
        StaffSchoolAssignment so the school enters the CCEO's planning scope."""
        body = (
            "Staff Name,School ID,School Name,District,Current Partner Type\n"
            "Ojok Amos,SCH-MATCH-1,Match Primary,Staff District,Client\n"
        )
        res = self._upload(body)
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["matched_staff_count"], 1)
        self.assertEqual(data["unmatched_staff_count"], 0)

        school = School.objects.get(school_id="SCH-MATCH-1")
        self.assertEqual(school.account_owner_status, "matched")
        self.assertEqual(school.account_owner_id, self.cceo_staff.id)
        # The ownership bridge: StaffSchoolAssignment was written.
        self.assertTrue(
            StaffSchoolAssignment.objects.filter(
                staff=self.cceo_staff, school_id=school.id
            ).exists()
        )

    def test_unmatched_staff_name_creates_one_candidate_no_duplicate(self):
        body = (
            "Staff Name,School ID,School Name,District\n"
            "Ghost Person,SCH-UNMATCH-1,Unmatch Primary,Staff District\n"
            "Ghost Person,SCH-UNMATCH-2,Unmatch Second,Staff District\n"
        )
        res = self._upload(body)
        data = res.json()
        self.assertEqual(data["unmatched_staff_count"], 2)
        # Exactly ONE candidate for "Ghost Person" (not two).
        candidates = StaffSetupCandidate.objects.filter(normalized_name="ghost person")
        self.assertEqual(candidates.count(), 1)
        self.assertEqual(candidates.first().school_count, 2)

    def test_account_owner_fallback_still_works(self):
        """An old file using 'Account Owner' instead of 'Staff Name' still maps."""
        body = (
            "Account Owner,School ID,School Name,District\n"
            "Ojok Amos,SCH-FALLBACK-1,Fallback Primary,Staff District\n"
        )
        res = self._upload(body)
        self.assertEqual(res.status_code, 200, res.content)
        school = School.objects.get(school_id="SCH-FALLBACK-1")
        self.assertEqual(school.account_owner_status, "matched")

    def test_ambiguous_staff_name_does_not_auto_assign(self):
        """Two CCEOs with the same name → AMBIGUOUS, no auto-link, candidate created."""
        self._user(
            "cc2@staff.test", EdifyRole.CCEO.value, "Ojok Amos"
        )  # second "Ojok Amos"
        StaffProfile.objects.create(
            user=User.objects.get(email="cc2@staff.test"), title="CCEO"
        )
        body = (
            "Staff Name,School ID,School Name,District\n"
            "Ojok Amos,SCH-AMB-1,Ambig Primary,Staff District\n"
        )
        res = self._upload(body)
        data = res.json()
        self.assertEqual(data["ambiguous_staff_count"], 1)
        school = School.objects.get(school_id="SCH-AMB-1")
        self.assertEqual(school.account_owner_status, "ambiguous")
        self.assertIsNone(school.account_owner_id)  # NOT auto-linked

    def test_non_field_staff_not_auto_linked(self):
        """An IA user named the same as the Staff Name is NOT auto-linked (role-aware)."""
        self._user(
            "ia2@staff.test", EdifyRole.IMPACT_ASSESSMENT.value, "Unique IA Name"
        )
        body = (
            "Staff Name,School ID,School Name,District\n"
            "Unique IA Name,SCH-IA-1,IA Primary,Staff District\n"
        )
        res = self._upload(body)
        school = School.objects.get(school_id="SCH-IA-1")
        self.assertEqual(
            school.account_owner_status, "unmatched"
        )  # IA is not field staff

    # ── Admin staff-candidate resolution ─────────────────────────────────────
    def test_admin_create_user_from_candidate_links_all_schools(self):
        # Upload two schools under an unmatched name.
        body = (
            "Staff Name,School ID,School Name,District\n"
            "New CCEO,SCH-CAND-1,Cand Primary,Staff District\n"
            "New CCEO,SCH-CAND-2,Cand Second,Staff District\n"
        )
        self._upload(body)
        cand = StaffSetupCandidate.objects.get(normalized_name="new cceo")
        self.assertEqual(cand.school_count, 2)

        # Admin creates a user for the candidate.
        self._as(self.admin)
        res = self.client.post(
            f"/api/staff-candidates/{cand.id}/create-user",
            {"email": "newcceo@staff.test", "role": "CCEO", "phone": "+256700000"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["status"], "active")

        # Both schools are now linked + matched.
        new_user = User.objects.get(email="newcceo@staff.test")
        new_staff = new_user.staff_profile
        for sid in ("SCH-CAND-1", "SCH-CAND-2"):
            school = School.objects.get(school_id=sid)
            self.assertEqual(school.account_owner_status, "matched")
            self.assertEqual(school.account_owner_id, new_staff.id)
            self.assertTrue(
                StaffSchoolAssignment.objects.filter(
                    staff=new_staff, school_id=school.id
                ).exists()
            )

    def test_admin_match_existing_user_links_schools(self):
        # Upload under a name that does NOT match any existing user → candidate.
        body = "Staff Name,School ID,School Name,District\nGrace Akello,SCH-MERGE-1,Merge Primary,Staff District\n"
        self._upload(body)
        cand = StaffSetupCandidate.objects.get(normalized_name="grace akello")
        # Admin merges the candidate with the existing PL user.
        self._as(self.admin)
        res = self.client.post(
            f"/api/staff-candidates/{cand.id}/match-existing-user",
            {"userId": self.pl.id},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["status"], "merged")
        school = School.objects.get(school_id="SCH-MERGE-1")
        self.assertEqual(school.account_owner_status, "matched")
        self.assertEqual(school.account_owner_id, self.pl_staff.id)

    # ── CD supervisor assignment → PL team scope ─────────────────────────────
    def test_cd_assigns_supervisor_and_pl_team_scope_grows(self):
        # CCEO owns a school (write the assignment directly to set up the test).
        school = School.objects.create(
            school_id="SCH-SUP-1",
            name="Sup Primary",
            region=self.region,
            district=self.district,
        )
        StaffSchoolAssignment.objects.create(staff=self.cceo_staff, school_id=school.id)

        # Admin assigns the PL as the CCEO's supervisor.
        self._as(self.admin)
        res = self.client.post(
            f"/api/staff/{self.cceo_staff.id}/assign-supervisor",
            {"supervisorId": self.pl_staff.id, "reason": "PL manages CCEO"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(
            StaffSupervisorAssignment.objects.filter(
                supervisee=self.cceo_staff, supervisor=self.pl_staff
            ).exists()
        )

        # The PL's resolved scope now includes the CCEO's school (team lens).
        from apps.core.scoping import resolve_user_scope

        # resolve_user_scope reads active_role + staff_profile_id + user_id.
        pl_principal = type(
            "P",
            (),
            {
                "active_role": self.pl.active_role,
                "user_id": self.pl.id,
                "staff_profile_id": self.pl_staff.id,
                "id": self.pl.id,
            },
        )()
        pl_scope = resolve_user_scope(pl_principal)
        self.assertIn(school.id, pl_scope.team_school_ids)
        self.assertIn(school.id, pl_scope.school_ids)

    # ── CD project-manager assignment ────────────────────────────────────────
    def test_cd_sets_project_manager(self):
        proj = Project.objects.create(
            code="SP-TEST", name="Test Project", category="pilot"
        )
        self._as(self.admin)
        res = self.client.patch(
            f"/api/special-projects/{proj.id}",
            {"managerStaffId": self.pl_staff.id},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        proj.refresh_from_db()
        self.assertEqual(proj.manager_staff_id, self.pl_staff.id)

    # ── Staff list endpoint ──────────────────────────────────────────────────
    def test_staff_list_returns_roster_with_supervisor(self):
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_staff, supervisor=self.pl_staff
        )
        self._as(self.admin)
        res = self.client.get("/api/staff")
        self.assertEqual(res.status_code, 200, res.content)
        roster = res.json()
        cceo_row = next(r for r in roster if r["id"] == self.cceo_staff.id)
        self.assertEqual(cceo_row["supervisorId"], self.pl_staff.id)
