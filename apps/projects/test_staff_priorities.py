from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.permissions import has_permission
from apps.core.rbac import EdifyRole, Permission
from apps.geography.models import District, Region
from apps.schools.models import School

from .models import Project, ProjectCategory, ProjectStaffAssignment
from .services import assign_school, assign_staff, create_project
from .staff_priorities import staff_project_priorities, team_project_priorities


class ProjectStaffPriorityWorkflowTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Project Priority Region")
        self.district = District.objects.create(
            name="Project Priority District",
            region=self.region,
            district_type="primary",
        )
        self.ia, self.ia_staff = self._staff(
            "project-ia@example.test",
            "Project IA",
            EdifyRole.IMPACT_ASSESSMENT.value,
        )
        self.cd, self.cd_staff = self._staff(
            "project-cd@example.test",
            "Project CD",
            EdifyRole.COUNTRY_DIRECTOR.value,
        )
        self.admin, self.admin_staff = self._staff(
            "project-admin@example.test",
            "Project Admin",
            EdifyRole.ADMIN.value,
        )
        self.cceo, self.cceo_staff = self._staff(
            "project-cceo@example.test",
            "Project CCEO",
            EdifyRole.CCEO.value,
        )
        self.pl, self.pl_staff = self._staff(
            "project-pl@example.test",
            "Project PL",
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        )
        self.coordinator, self.coordinator_staff = self._staff(
            "project-coordinator@example.test",
            "Project Coordinator",
            EdifyRole.PROJECT_COORDINATOR.value,
        )
        self.client_school = self._school("PCLIENT", "Client Priority School", "client")
        self.core_school = self._school("PCORE", "Core Priority School", "core")
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_staff, school_id=self.client_school.id
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_staff, school_id=self.core_school.id
        )

    def _staff(self, email, name, role):
        user = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="test-password",
            is_active=True,
        )
        return user, StaffProfile.objects.create(
            user=user,
            title=role,
            country="Uganda",
        )

    def _school(self, school_id, name, school_type):
        return School.objects.create(
            school_id=school_id,
            name=name,
            school_type=school_type,
            region=self.region,
            district=self.district,
        )

    def _project(self, suffix, school_focus="all"):
        return Project.objects.create(
            code=f"STAFF-{suffix}",
            name=f"Staff Project {suffix}",
            category=ProjectCategory.INTERVENTION_SPECIFIC,
            status="active",
            school_focus=school_focus,
        )

    def _assign_to_cceo(self, project):
        assign_staff(
            project.id,
            {"staffIds": [self.cceo_staff.id]},
            self.ia,
        )

    def test_ia_cd_and_admin_can_create_projects_but_coordinator_cannot(self):
        item = ActivityCatalogueItem.objects.filter(
            status="active",
            project_delivery_allowed=True,
        ).first()
        payload = {
            "name": "Literacy Project Priority",
            "code": "LITERACY-PRIORITY",
            "category": ProjectCategory.INTERVENTION_SPECIFIC,
            "targetInterventions": ["teaching_environment"],
            "catalogueItemIds": [item.id],
            "schoolFocus": "all",
        }
        result = create_project(payload, self.ia)
        self.assertEqual(result["schoolFocus"], "all")
        self.assertTrue(
            has_permission(
                self.admin,
                Permission.PROJECT_CONFIGURE_PRIORITIES.value,
            )
        )
        with self.assertRaises(Forbidden):
            create_project({**payload, "code": "PC-DENIED"}, self.coordinator)

    def test_role_group_assignment_becomes_each_staff_project_priority(self):
        project = self._project("LITERACY")

        result = assign_staff(
            project.id,
            {
                "fy": "2027",
                "roleGroups": [
                    EdifyRole.CCEO.value,
                    EdifyRole.COUNTRY_PROGRAM_LEAD.value,
                ]
            },
            self.cd,
        )

        self.assertEqual(result["assigned"], 2)
        self.assertTrue(
            ProjectStaffAssignment.objects.filter(
                project=project,
                staff=self.cceo_staff,
                is_active=True,
            ).exists()
        )
        self.assertEqual(
            staff_project_priorities(user=self.cceo, fy="2027")[0][
                "projectName"
            ],
            project.name,
        )
        team_rows = team_project_priorities(
            users=[self.cceo, self.pl],
            fy="2027",
        )
        self.assertEqual(
            {row["teamMember"] for row in team_rows},
            {self.cceo.name, self.pl.name},
        )

    def test_client_school_can_join_only_one_active_project(self):
        first = self._project("CLIENT-1")
        second = self._project("CLIENT-2")
        self._assign_to_cceo(first)
        self._assign_to_cceo(second)

        assign_school(
            first.id,
            {"schoolId": self.client_school.school_id},
            self.cceo,
        )

        with self.assertRaisesMessage(BadRequest, "maximum of 1 active Project"):
            assign_school(
                second.id,
                {"schoolId": self.client_school.school_id},
                self.cceo,
            )

    def test_core_school_can_join_four_active_projects_but_not_five(self):
        projects = [self._project(f"CORE-{index}") for index in range(1, 6)]
        for project in projects:
            self._assign_to_cceo(project)
        for project in projects[:4]:
            assign_school(
                project.id,
                {"schoolId": self.core_school.school_id},
                self.cceo,
            )

        with self.assertRaisesMessage(BadRequest, "maximum of 4 active Projects"):
            assign_school(
                projects[4].id,
                {"schoolId": self.core_school.school_id},
                self.cceo,
            )

    def test_core_focused_project_rejects_client_school(self):
        project = self._project("CORE-ONLY", school_focus="core")
        self._assign_to_cceo(project)

        with self.assertRaisesMessage(BadRequest, "limited to Core Schools"):
            assign_school(
                project.id,
                {"schoolId": self.client_school.school_id},
                self.cceo,
            )

    def test_assigned_staff_can_open_project_priority_and_add_schools(self):
        project = self._project("DETAIL")
        self._assign_to_cceo(project)
        client = Client()
        client.force_login(self.cceo)

        response = client.get(f"/projects/{project.id}")

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Add Schools to This Priority", html)
        self.assertIn(self.client_school.name, html)
        self.assertNotIn("Assign as Staff Priority", html)

    def test_ia_project_detail_exposes_staff_priority_assignment(self):
        project = self._project("IA-DETAIL")
        client = Client()
        client.force_login(self.ia)

        response = client.get(f"/projects/{project.id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Assign as Staff Priority", response.content.decode())

    def test_assigned_project_appears_on_staff_my_targets_dashboard(self):
        project = self._project("MY-TARGETS")
        assign_staff(
            project.id,
            {"staffIds": [self.cceo_staff.id], "fy": "2027"},
            self.admin,
        )
        client = Client()
        client.force_login(self.cceo)

        response = client.get("/my-targets", {"fy": "2027", "month": 1})

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Assigned Project Priorities", html)
        self.assertIn(project.name, html)
        self.assertIn("Plan this Project", html)

    def test_my_targets_uses_the_current_partner_type_breakdown(self):
        project = self._project("TYPE-BREAKDOWN")
        self._assign_to_cceo(project)
        graduate = self._school(
            "PGRAD",
            "Graduate Priority School",
            "core_graduate",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_staff,
            school_id=graduate.id,
        )
        assign_school(
            project.id,
            {"schoolId": graduate.school_id},
            self.cceo,
        )

        row = staff_project_priorities(user=self.cceo, fy="2026")[0]

        self.assertEqual(
            row["schoolTypeBreakdown"],
            [{"value": "core_graduate", "label": "Core Graduate", "count": 1}],
        )
