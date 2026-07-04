from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.geography.models import Region, District, SubCounty
from apps.schools.models import School
from apps.clusters.models import Cluster, ClusterSubCounty, SchoolClusterAssignment
from apps.accounts.models import StaffProfile

class BulkAssignmentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(
            id="user-1",
            email="cceo@edify.org",
            name="CCEO User",
            roles=["Admin"],
            active_role="Admin"
        )
        self.staff_profile = StaffProfile.objects.create(
            id="staff-1",
            user=self.user,
            title="Admin"
        )
        
        self.region = Region.objects.create(id="reg-1", name="Central Region")
        self.district = District.objects.create(id="dist-1", name="Mukono District", region=self.region)
        self.district_other = District.objects.create(id="dist-2", name="Wakiso District", region=self.region)
        
        self.sub_county_1 = SubCounty.objects.create(id="sc-1", name="Mukono Central", district=self.district)
        self.sub_county_2 = SubCounty.objects.create(id="sc-2", name="Mukono North", district=self.district)
        self.sub_county_other = SubCounty.objects.create(id="sc-3", name="Wakiso Central", district=self.district_other)
        
        self.school = School.objects.create(
            id="sch-1",
            school_id="S-1001",
            name="Mukono Primary School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county_1,
            school_type="client",
            cluster_status="unclustered"
        )
        
        self.school_other = School.objects.create(
            id="sch-2",
            school_id="S-1002",
            name="Mukono Secondary School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county_2,
            school_type="client",
            cluster_status="unclustered"
        )
        
        self.cluster = Cluster.objects.create(
            id="cl-1",
            name="Mukono Hub Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county_1,
            status="active"
        )
        ClusterSubCounty.objects.create(cluster=self.cluster, sub_county=self.sub_county_1)

    def test_add_to_cluster_drawer_sub_counties_scoping(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        self.assertEqual(response.status_code, 200)
        
        sub_counties = response.context["sub_counties"]
        # Should only contain sub-counties in Mukono District (sc-1 and sc-2, NOT sc-3)
        sub_county_ids = [sc.id for sc in sub_counties]
        self.assertIn("sc-1", sub_county_ids)
        self.assertIn("sc-2", sub_county_ids)
        self.assertNotIn("sc-3", sub_county_ids)
        
        # Verify counts are attached
        sc_1_obj = next(sc for sc in sub_counties if sc.id == "sc-1")
        self.assertEqual(sc_1_obj.unclustered_schools_count, 1)

    def test_create_new_cluster_multi_sub_counties(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/schools/{self.school_other.id}/add-to-cluster",
            {
                "cluster_action_type": "new",
                "new_cluster_name": "New Mukono Extended Cluster",
                "new_district_id": "dist-1",
                "new_sub_county_ids": ["sc-2"],
                "notes": "Grouping Mukono sub-counties."
            }
        )
        self.assertEqual(response.status_code, 200)
        
        # Assert cluster was created and assigned
        self.school_other.refresh_from_db()
        self.assertEqual(self.school_other.cluster_status, "clustered")
        
        new_cluster = Cluster.objects.get(name="New Mukono Extended Cluster")
        self.assertEqual(self.school_other.cluster_id, new_cluster.id)
        
        # Assert ClusterSubCounty joins were created
        covered = ClusterSubCounty.objects.filter(cluster=new_cluster).values_list("sub_county_id", flat=True)
        self.assertIn("sc-2", covered)

    def test_bulk_assign_drawer_candidate_list(self):
        self.client.force_login(self.user)
        # Link sc-2 to the cluster
        ClusterSubCounty.objects.get_or_create(cluster=self.cluster, sub_county=self.sub_county_2)
        
        response = self.client.get(f"/clusters/{self.cluster.id}/bulk-assign-drawer")
        self.assertEqual(response.status_code, 200)
        
        schools = response.context["schools"]
        school_ids = [s.id for s in schools]
        # Should include both unclustered schools (sch-1 and sch-2) since both sub-counties are linked
        self.assertIn("sch-1", school_ids)
        self.assertIn("sch-2", school_ids)

    def test_bulk_assign_drawer_post(self):
        self.client.force_login(self.user)
        # Link sc-2 to the cluster so the schools in sc-2 are eligible for assignment
        ClusterSubCounty.objects.get_or_create(cluster=self.cluster, sub_county=self.sub_county_2)
        
        response = self.client.post(
            f"/clusters/{self.cluster.id}/bulk-assign-drawer",
            {
                "school_ids": ["sch-1", "sch-2"]
            }
        )
        self.assertEqual(response.status_code, 200)
        
        self.school.refresh_from_db()
        self.school_other.refresh_from_db()
        
        self.assertEqual(self.school.cluster_id, self.cluster.id)
        self.assertEqual(self.school.cluster_status, "clustered")
        self.assertEqual(self.school_other.cluster_id, self.cluster.id)
        self.assertEqual(self.school_other.cluster_status, "clustered")
        
        # Assert assignments recorded
        self.assertTrue(SchoolClusterAssignment.objects.filter(school=self.school, cluster=self.cluster).exists())
        self.assertTrue(SchoolClusterAssignment.objects.filter(school=self.school_other, cluster=self.cluster).exists())

    def test_add_to_cluster_drawer_get_with_existing_covering_cluster(self):
        self.client.force_login(self.user)
        # self.school is in sub_county_1 which is covered by self.cluster
        response = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["existing_covering_cluster"].id, self.cluster.id)

    def test_add_to_cluster_drawer_sub_counties_claimed_flag(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        self.assertEqual(response.status_code, 200)
        sub_counties = response.context["sub_counties"]
        
        # sc-1 is covered by self.cluster
        sc_1_obj = next(sc for sc in sub_counties if sc.id == "sc-1")
        self.assertEqual(sc_1_obj.covering_cluster_name, self.cluster.name)
        
        # sc-2 is not covered
        sc_2_obj = next(sc for sc in sub_counties if sc.id == "sc-2")
        self.assertIsNone(sc_2_obj.covering_cluster_name)

    def test_create_new_cluster_routing_safeguard(self):
        self.client.force_login(self.user)
        # Get count of clusters before POST
        cluster_count_before = Cluster.objects.count()
        
        # Try to post "new" cluster for school in sc-1 (which is already covered by self.cluster)
        response = self.client.post(
            f"/schools/{self.school.id}/add-to-cluster",
            {
                "cluster_action_type": "new",
                "new_cluster_name": "Duplicate Mukono Hub Cluster",
                "new_district_id": "dist-1",
                "new_sub_county_ids": ["sc-1"],
                "notes": "Trying to bypass."
            }
        )
        self.assertEqual(response.status_code, 200)
        
        # Verify no new cluster was created
        self.assertEqual(Cluster.objects.count(), cluster_count_before)
        
        # Verify the school was auto-routed and assigned to self.cluster
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.cluster.id)
        self.assertEqual(self.school.cluster_status, "clustered")

    def test_core_dashboard_pagination(self):
        self.client.force_login(self.user)
        
        # Delete existing core schools first to ensure predictable counts
        School.objects.filter(school_type="core").delete()
        
        # Create 15 core schools
        for i in range(15):
            School.objects.create(
                school_id=f"CS-{100 + i}",
                name=f"Core School {i}",
                region=self.region,
                district=self.district,
                sub_county=self.sub_county_1,
                school_type="core",
                current_fy_ssa_status="done"
            )
            
        # Get page 1
        response = self.client.get("/core-schools?page=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["matrix_rows"]), 10)
        self.assertTrue(response.context["is_paginated"])
        self.assertIn(1, response.context["pages_list"])
        self.assertIn(2, response.context["pages_list"])
        
        # Get page 2
        response = self.client.get("/core-schools?page=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["matrix_rows"]), 5)

    def test_next_missing_milestone_calculation(self):
        from apps.core_schools.models import CorePlan, CoreActivitySlot, cplan_id, cslot_id
        self.client.force_login(self.user)
        
        # Delete existing core schools first to avoid interference
        School.objects.filter(school_type="core").delete()
        
        # 1. School without plan -> "Missing First Visit"
        School.objects.create(
            school_id="CS-999",
            name="No Plan School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county_1,
            school_type="core",
            current_fy_ssa_status="done"
        )
        response = self.client.get("/core-schools")
        rows = {r["school_id"]: r for r in response.context["matrix_rows"]}
        self.assertEqual(rows["CS-999"]["next_missing_milestone"], "Missing First Visit")
        
        # 2. School with plan, first visit completed -> "Missing First Training"
        school_plan = School.objects.create(
            school_id="CS-888",
            name="Plan School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county_1,
            school_type="core",
            current_fy_ssa_status="done"
        )
        plan = CorePlan.objects.create(
            id=cplan_id(school_plan.school_id),
            school_id=school_plan.school_id,
            fy="2026"
        )
        # Add a completed visit slot for first sequence
        CoreActivitySlot.objects.create(
            id=cslot_id(school_plan.school_id, "visit", 1),
            core_plan=plan,
            school_id=school_plan.school_id,
            intervention="Reading Fluency",
            activity_type="visit",
            sequence_number=1,
            status="completed"
        )
        response = self.client.get("/core-schools")
        rows = {r["school_id"]: r for r in response.context["matrix_rows"]}
        self.assertEqual(rows["CS-888"]["next_missing_milestone"], "Missing First Training")



