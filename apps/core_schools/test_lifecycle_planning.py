from datetime import date

from apps.schools.test_programme_schools import _Fixture
from apps.accounts.models import StaffSupervisorAssignment
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.clusters.test_cluster_oversight_views import _create_user
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.core_schools.models import CorePlan
from apps.core_schools.lifecycle import programme_sections, school_work
from apps.core_schools.oversight_service import core_schools_oversight_data


class LifecyclePlanningTest(_Fixture):
    def setUp(self):
        self.fy = get_operational_fy()
        self.cluster = Cluster.objects.create(
            name="Lifecycle Cluster",
            region=self.region,
            district=self.district,
            responsible_staff_id=self.staff.id,
        )
        self.training = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            responsible_staff_id=self.staff.id,
            fy=self.fy,
            planned_date=date.today(),
            status="scheduled",
            delivery_type="staff",
        )
        for school in (
            self.core,
            self.trained,
            self.graduate,
            self.champion,
            self.client_school,
        ):
            ClusterActivityAttendance.objects.create(
                activity=self.training, school=school, invited=True
            )

    def test_each_type_has_its_own_table_without_package_initialization(self):
        sections = programme_sections(self.user, {"fy": self.fy})
        self.assertEqual([len(s["rows"]) for s in sections], [1, 1, 1])
        for section in sections:
            row = section["rows"][0]
            self.assertEqual([w["id"] for w in row["work"]], [self.training.id])
            self.assertTrue(row["can_schedule"])
        self.assertFalse(
            CorePlan.objects.filter(
                school_id__in=[
                    self.trained.school_id,
                    self.graduate.school_id,
                    self.champion.school_id,
                ]
            ).exists()
        )
        self.client.force_login(self.user)
        response = self.client.get("/core-schools", {"fy": self.fy})
        self.assertEqual(response.status_code, 200)
        for name in ("Core Trained", "Core Graduate", "Champion"):
            self.assertContains(response, f'aria-label="{name} schools"')
        self.assertFalse(
            CorePlan.objects.filter(school_id=self.champion.school_id).exists()
        )

    def test_my_plan_moves_core_invitations_even_without_a_package_slot(self):
        self.client.force_login(self.user)
        response = self.client.get("/my-plan", {"period": "fy", "fy": self.fy})
        self.assertEqual(response.status_code, 200)
        rows = response.context["core_school_trainings"]
        self.assertEqual([r["school_id"] for r in rows], [self.core.school_id])
        for section in response.context["programme_school_work"]:
            self.assertEqual(len(section["rows"]), 1)
            self.assertEqual(section["rows"][0]["training_number"], "")
        shared = response.context["cluster_trainings"]
        self.assertEqual(
            {r["school_id"] for r in shared}, {self.client_school.school_id}
        )

    def test_old_core_visit_without_slot_is_classified_as_core(self):
        visit = Activity.objects.create(
            activity_type="school_visit",
            school=self.core,
            responsible_staff_id=self.staff.id,
            fy=self.fy,
            planned_date=date.today(),
            status="scheduled",
            delivery_type="staff",
        )
        self.client.force_login(self.user)
        response = self.client.get("/my-plan", {"period": "fy", "fy": self.fy})
        self.assertIn(
            visit.id, {r["id"] for r in response.context["core_school_visits"]}
        )
        self.assertNotIn(visit.id, {r["id"] for r in response.context["school_visits"]})

    def test_all_oversight_roles_see_all_types_without_programme_targets(self):
        lead = _create_user("lifecycle-lead@test.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        StaffSupervisorAssignment.objects.create(
            supervisor=lead.staff_profile, supervisee=self.staff
        )
        for role in (
            EdifyRole.COUNTRY_PROGRAM_LEAD,
            EdifyRole.IMPACT_ASSESSMENT,
            EdifyRole.COUNTRY_DIRECTOR,
            EdifyRole.REGIONAL_PROGRAM_LEAD,
        ):
            user = (
                lead
                if role == EdifyRole.COUNTRY_PROGRAM_LEAD
                else _create_user(f"{role.value}@lifecycle.test", role)
            )
            with self.subTest(role=role):
                data = core_schools_oversight_data(user, fy=self.fy)
                groups = (
                    data["cceo_tabs"]
                    if data["is_programme_lead"]
                    else [t for p in data["leads"] for t in p["cceo_tabs"]]
                )
                rows = [r for g in groups for r in g["schools"]]
                self.assertEqual(
                    {r["school_type"] for r in rows},
                    {"core", "core_trained", "core_graduate", "champion"},
                )
                for row in rows:
                    if row["school_type"] != "core":
                        self.assertEqual(
                            (row["visits_target"], row["trainings_target"]), (0, 0)
                        )
                self.client.force_login(user)
                response = self.client.get("/core-schools-oversight/", {"fy": self.fy})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, self.champion.name)

    def test_uninvited_school_gets_no_training_and_cancelled_work_is_hidden(self):
        ClusterActivityAttendance.objects.filter(
            activity=self.training, school=self.champion
        ).update(invited=False)
        self.assertEqual(school_work([self.champion], self.fy)[self.champion.id], [])
        self.training.status = "cancelled"
        self.training.save()
        self.assertEqual(school_work([self.trained], self.fy)[self.trained.id], [])

    def test_category_pagination_keeps_every_school_accessible(self):
        second = self._school("PS-CHAMP-2", "champion")
        first_page = programme_sections(self.user, {"fy": self.fy}, per_page=1)
        second_page = programme_sections(
            self.user, {"fy": self.fy}, per_page=1, params={"champion_page": "2"}
        )
        self.assertEqual(first_page[2]["page"].paginator.count, 2)
        self.assertEqual(
            {first_page[2]["rows"][0]["id"], second_page[2]["rows"][0]["id"]},
            {self.champion.id, second.id},
        )

    def test_unrelated_lead_cannot_see_the_lifecycle_schools(self):
        outsider = _create_user(
            "outside-lifecycle@test.test", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        self.assertEqual(
            core_schools_oversight_data(outsider, fy=self.fy)["total_schools"], 0
        )
        self.assertTrue(
            all(
                not section["rows"]
                for section in programme_sections(outsider, {"fy": self.fy})
            )
        )

    def test_matrix_search_updates_the_full_width_lifecycle_tables(self):
        self.client.force_login(self.user)
        response = self.client.get('/core-schools', {'fy': self.fy, 'q': self.champion.school_id}, HTTP_HX_REQUEST='true', HTTP_HX_TARGET='core-schools-table-container')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="core-lifecycle-tables"')
        self.assertContains(response, 'hx-swap-oob="outerHTML"')
        self.assertContains(response, self.champion.name)
        self.assertNotContains(response, self.trained.name)
