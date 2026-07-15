from __future__ import annotations

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import StaffProfile, User
from apps.core.enums import SsaIntervention
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.clusters.models import Cluster, ClusterSubCounty, SchoolClusterAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.planning.services import plan_builder


class ClusterSetupTest(APITestCase):
    def setUp(self):
        # Create standard geo hierarchy
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Mukono", region=self.region)
        self.sub_county1 = SubCounty.objects.create(
            name="Ntunga", district=self.district
        )
        self.sub_county2 = SubCounty.objects.create(
            name="Ntunga South", district=self.district
        )

        # Create user / planner context
        self.user = User.objects.create_user(
            email="planner@test.edify.org",
            name="Cceo Planner",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.profile = StaffProfile.objects.create(
            user=self.user, title="CCEO", id="STF-001"
        )

        # Create clusters
        self.cluster1 = Cluster.objects.create(
            name="Mukono Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            cluster_type="mixed",
            status="active",
        )
        ClusterSubCounty.objects.create(
            cluster=self.cluster1, sub_county=self.sub_county1
        )

        self.cluster2 = Cluster.objects.create(
            name="Wakiso Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county2,
            cluster_type="mixed",
            status="active",
        )
        ClusterSubCounty.objects.create(
            cluster=self.cluster2, sub_county=self.sub_county2
        )

    def test_auto_classification_on_create(self):
        """Creating a school automatically assigns it to a cluster covering its sub-county."""
        school = School.objects.create(
            school_id="SCH-901",
            name="Test School Alpha",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
        )
        # Should auto-assign to cluster1
        self.assertEqual(school.cluster_id, self.cluster1.id)
        self.assertEqual(school.cluster_status, "clustered")
        self.assertTrue(
            SchoolClusterAssignment.objects.filter(
                school=school, cluster=self.cluster1
            ).exists()
        )

    def test_real_time_reclassification_on_update(self):
        """Updating a school's sub-county reassigns it to the correct cluster in real-time."""
        school = School.objects.create(
            school_id="SCH-902",
            name="Test School Beta",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
        )
        self.assertEqual(school.cluster_id, self.cluster1.id)

        # Move to sub_county2
        school.sub_county = self.sub_county2
        school.save()

        # Reload
        school.refresh_from_db()
        self.assertEqual(school.cluster_id, self.cluster2.id)
        self.assertEqual(school.cluster_status, "clustered")
        self.assertFalse(
            SchoolClusterAssignment.objects.filter(
                school=school, cluster=self.cluster1
            ).exists()
        )
        self.assertTrue(
            SchoolClusterAssignment.objects.filter(
                school=school, cluster=self.cluster2
            ).exists()
        )

    def test_reclassification_to_unclustered(self):
        """Updating a school's geography to a sub-county with no cluster clears its assignment."""
        school = School.objects.create(
            school_id="SCH-903",
            name="Test School Gamma",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
        )
        self.assertEqual(school.cluster_id, self.cluster1.id)

        # Set sub-county to None/empty or an unclustered sub-county
        unclustered_sub = SubCounty.objects.create(
            name="Ntunga East", district=self.district
        )
        school.sub_county = unclustered_sub
        school.save()

        school.refresh_from_db()
        self.assertIsNone(school.cluster_id)
        self.assertEqual(school.cluster_status, "unclustered")
        self.assertFalse(SchoolClusterAssignment.objects.filter(school=school).exists())

    def test_dynamic_cluster_metrics_and_feed(self):
        """Plan builder feed dynamic metrics are calculated from member schools' latest SSA."""
        # Create member schools in cluster1
        school1 = School.objects.create(
            school_id="SCH-101",
            name="Alpha Acad",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
            current_fy_ssa_status="done",
        )
        school2 = School.objects.create(
            school_id="SCH-102",
            name="Beta Acad",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
            current_fy_ssa_status="done",
        )

        from apps.accounts.models import StaffSchoolAssignment

        StaffSchoolAssignment.objects.create(staff=self.profile, school_id=school1.id)
        StaffSchoolAssignment.objects.create(staff=self.profile, school_id=school2.id)

        # Create verified SSA records
        now = timezone.now()
        r1 = SsaRecord.objects.create(
            school=school1,
            date_of_ssa=now,
            fy="2026",
            quarter="Q1",
            average_score=6.0,
            verification_status="confirmed",
        )
        r2 = SsaRecord.objects.create(
            school=school2,
            date_of_ssa=now,
            fy="2026",
            quarter="Q1",
            average_score=8.0,
            verification_status="confirmed",
        )

        # Let's add scores
        # We will make financial_health weak on school 1 (score 2.0) and school 2 (score 4.0) -> avg 3.0
        # teaching_environment will be strong (score 8.0) and school 2 (score 9.0) -> avg 8.5
        SsaScore.objects.create(
            ssa_record=r1,
            intervention=SsaIntervention.FINANCIAL_HEALTH.value,
            score=2.0,
        )
        SsaScore.objects.create(
            ssa_record=r1,
            intervention=SsaIntervention.TEACHING_ENVIRONMENT.value,
            score=8.0,
        )

        SsaScore.objects.create(
            ssa_record=r2,
            intervention=SsaIntervention.FINANCIAL_HEALTH.value,
            score=4.0,
        )
        SsaScore.objects.create(
            ssa_record=r2,
            intervention=SsaIntervention.TEACHING_ENVIRONMENT.value,
            score=9.0,
        )

        # Call plan_builder service
        self.client.force_authenticate(user=self.user)
        payload = plan_builder({"fy": "2026"}, self.user)

        self.assertIn("schools", payload)
        self.assertIn("clusters", payload)

        clusters = payload["clusters"]
        cluster_data = next(c for c in clusters if c["clusterId"] == self.cluster1.id)

        # Average of 6.0 and 8.0 is 7.0
        self.assertEqual(cluster_data["averageSsa"], 7.0)
        self.assertEqual(cluster_data["schoolCount"], 2)

        # Weakest is financial_health (average 3.0)
        self.assertEqual(
            cluster_data["weakest"]["intervention"],
            SsaIntervention.FINANCIAL_HEALTH.value,
        )
        self.assertEqual(cluster_data["weakest"]["avg"], 3.0)

    def test_get_eligible_staff_filtering(self):
        """get_eligible_staff correctly filters based on school assignments or fallback."""
        from apps.frontend.views.cluster_views import get_eligible_staff
        from apps.accounts.models import StaffSchoolAssignment

        # Create a second staff user
        user2 = User.objects.create_user(
            email="cceo2@test.edify.org",
            name="Esther Cceo",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        profile2 = StaffProfile.objects.create(user=user2, title="CCEO", id="STF-002")

        school = School.objects.create(
            school_id="SCH-800",
            name="School Eight",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
        )
        # Assign profile2 to school in Mukono district
        StaffSchoolAssignment.objects.create(staff=profile2, school_id=school.id)

        # Mukono district has district_id = self.district.id
        staff = get_eligible_staff(self.district.id)
        # Should return profile2 (Esther Cceo) first
        staff_ids = [s.id for s in staff]
        self.assertIn(profile2.id, staff_ids)

    def test_edit_cluster_view_updates_fields(self):
        """POST request to edit endpoint successfully updates the cluster attributes and covered subcounties."""
        from django.urls import reverse
        from apps.accounts.models import StaffSchoolAssignment

        # edit_cluster_view is a plain Django view (require_page_permission,
        # not DRF) — force_authenticate() only sets DRF's request.auth and
        # never touches the session, so the view sees an anonymous user.
        # force_login() is the one that actually works here.
        self.client.force_login(self.user)

        # update_cluster() scope-checks the target district against the
        # principal's assigned schools for CCEO/PL — give this CCEO a school
        # in-district so the edit isn't rejected as "outside your scope".
        school = School.objects.create(
            school_id="SCH-777",
            name="Scope School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=self.profile, school_id=school.id)

        url = reverse("frontend:edit_cluster", args=[self.cluster1.id])

        data = {
            "name": "Updated Mukono Cluster",
            "district_id": self.district.id,
            "cluster_type": "primary",
            "cluster_leader_name": "New Leader Name",
            "cluster_leader_phone": "+256 772 111 222",
            "responsible_staff_id": self.user.id,
            "sub_county_ids": [self.sub_county2.id],
        }

        # edit_cluster_view is a plain Django view that reads request.POST —
        # APITestCase's client defaults to JSON bodies (TEST_REQUEST_DEFAULT_FORMAT
        # = "json" in REST_FRAMEWORK settings), which Django never parses into
        # request.POST. Force multipart so the view actually sees the fields.
        response = self.client.post(url, data, format="multipart")
        self.assertEqual(response.status_code, 302)  # Redirect to list

        self.cluster1.refresh_from_db()
        self.assertEqual(self.cluster1.name, "Updated Mukono Cluster")
        self.assertEqual(self.cluster1.cluster_type, "primary")
        self.assertEqual(self.cluster1.cluster_leader_name, "New Leader Name")
        self.assertEqual(self.cluster1.cluster_leader_phone, "+256 772 111 222")
        self.assertEqual(self.cluster1.responsible_staff_id, self.user.id)

        # Verify subcounties update
        covered = list(
            ClusterSubCounty.objects.filter(cluster=self.cluster1).values_list(
                "sub_county_id", flat=True
            )
        )
        self.assertEqual(covered, [self.sub_county2.id])

    def test_eligible_staff_options_view_htmx(self):
        """GET request to eligible-staff endpoint returns HTML option tags."""
        from django.urls import reverse

        # Same plain-Django-view caveat as test_edit_cluster_view_updates_fields.
        self.client.force_login(self.user)
        url = (
            reverse("frontend:eligible_staff_options")
            + f"?district_id={self.district.id}"
        )

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("option", response.content.decode())
        self.assertIn(self.user.name, response.content.decode())

    # ── Regressions: planning_readiness dual vocabulary (HIGH finding §1) ──────

    def test_planning_ready_counters_recognize_production_vocabulary(self):
        """ "Planning Ready" counters must count production-vocabulary states
        (ready_for_support_planning/ready_for_baseline_ssa), not just the
        legacy "ready" literal that recompute_quality_and_readiness() only
        ever writes under pytest — production never writes "ready", so
        before this fix the counters were structurally zero outside tests.

        recompute() always takes the test-mode branch under the test
        runner (sys.argv contains "test"), so School.objects.create()/.save()
        can never itself produce a production-vocabulary value here —
        .update() (which bypasses save()) is the only way to reproduce a
        production row inside this test.
        """
        from apps.accounts.models import StaffSchoolAssignment
        from apps.core.enums import PlanningReadiness

        school = School.objects.create(
            school_id="SCH-950",
            name="Prod Vocab School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
            current_fy_ssa_status="done",
        )
        StaffSchoolAssignment.objects.create(staff=self.profile, school_id=school.id)
        School.objects.filter(pk=school.pk).update(
            planning_readiness=PlanningReadiness.READY_FOR_SUPPORT_PLANNING
        )

        self.assertIn(
            PlanningReadiness.READY_FOR_SUPPORT_PLANNING,
            PlanningReadiness.planning_ready_values(),
        )

        from apps.analytics.services import dashboard_summary

        summary = dashboard_summary(self.user, {})
        self.assertGreaterEqual(summary["planningReady"], 1)

        from apps.system_health.services import report as system_health_report

        health = system_health_report()
        self.assertGreaterEqual(health["planningReady"], 1)

        from django.urls import reverse

        self.client.force_login(self.user)
        resp = self.client.get(reverse("frontend:schools_directory"))
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.context["planning_ready_schools"], 1)

    # ── Regressions: assign_school() dropping recomputed fields (§2) ───────────

    def test_assign_school_persists_recomputed_readiness_and_quality(self):
        """assign_school()'s update_fields must include the recomputed
        planning_readiness/data_quality_score fields. School.save()
        unconditionally recomputes them in memory before writing, but a
        too-narrow update_fields silently dropped them from the actual
        UPDATE, leaving the school's own readiness badge stale relative to
        the Data Quality Center after a cluster assignment."""
        from apps.clusters.services import assign_school

        school = School.objects.create(
            school_id="SCH-960",
            name="Assign School Test",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        self.assertIsNone(school.cluster_id)
        self.assertEqual(school.planning_readiness, "locked")
        self.assertEqual(school.data_quality_score, 10)

        assign_school(school.school_id, {"clusterId": self.cluster1.id}, self.user)

        school.refresh_from_db()
        self.assertEqual(school.cluster_id, self.cluster1.id)
        self.assertEqual(school.cluster_status, "clustered")
        # Before the fix these stayed at their pre-assignment (missing-cluster)
        # values in the DB because update_fields excluded them — only
        # cluster_id/cluster_status/updated_at actually reached the row.
        self.assertEqual(school.planning_readiness, "ready")
        self.assertEqual(school.data_quality_score, 30)

    # ── Regressions: SchoolClusterAssignment desync (§3) ────────────────────────

    def test_sync_school_cluster_assignment_removes_stale_rows(self):
        """The shared helper must ensure exactly one active
        SchoolClusterAssignment row per school, deleting any stale row
        pointing at a different cluster before (re)creating the target row —
        this is what every assign/reassign call site now delegates to
        instead of reimplementing get_or_create/update_or_create."""
        from apps.clusters.services import sync_school_cluster_assignment

        school = School.objects.create(
            school_id="SCH-972",
            name="Sync Helper School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
        )
        # Auto-assigned to cluster1 on create.
        self.assertTrue(
            SchoolClusterAssignment.objects.filter(
                school=school, cluster=self.cluster1
            ).exists()
        )

        sync_school_cluster_assignment(school, self.cluster2, self.user.user_id)

        rows = list(SchoolClusterAssignment.objects.filter(school=school))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].cluster_id, self.cluster2.id)

        # Idempotent: calling again with the same cluster doesn't duplicate.
        sync_school_cluster_assignment(school, self.cluster2, self.user.user_id)
        self.assertEqual(
            SchoolClusterAssignment.objects.filter(school=school).count(), 1
        )

    def test_school_edit_drawer_syncs_cluster_assignment(self):
        """Reassigning a school's cluster via the edit drawer must sync
        SchoolClusterAssignment — previously this path updated
        School.cluster_id/cluster_status without ever touching the join
        table, so the school never appeared in its new cluster's school list
        and never disappeared from the old one."""
        from django.urls import reverse

        self.client.force_login(self.user)
        school = School.objects.create(
            school_id="SCH-971",
            name="Edit Drawer School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county1,
            school_type="client",
        )
        # Auto-assigned to cluster1 on create.
        self.assertTrue(
            SchoolClusterAssignment.objects.filter(
                school=school, cluster=self.cluster1
            ).exists()
        )
        # get_scoped_object_or_404 requires the school in this CCEO's own
        # portfolio.
        from apps.accounts.models import StaffSchoolAssignment

        StaffSchoolAssignment.objects.create(staff=self.profile, school_id=school.id)

        url = reverse("frontend:school_edit_drawer", args=[school.id])
        response = self.client.post(
            url,
            {
                "name": school.name,
                "school_phone": "",
                "primary_contact_name": "",
                "director_name": "",
                "headteacher_name": "",
                "shipping_address": "",
                "cluster_id": self.cluster2.id,
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)

        school.refresh_from_db()
        self.assertEqual(school.cluster_id, self.cluster2.id)
        self.assertEqual(school.cluster_status, "clustered")
        rows = list(SchoolClusterAssignment.objects.filter(school=school))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].cluster_id, self.cluster2.id)

    # ── Regressions: inline cluster-creation bypass (§4) ────────────────────────

    def test_add_to_cluster_drawer_blocks_overlapping_new_cluster(self):
        """The Add-to-Cluster drawer's inline "create new cluster" branch
        must go through the real create_cluster() service and be rejected
        when it overlaps an existing active cluster's sub-county. A CCEO
        holds CLUSTER_ASSIGN but not CLUSTER_OVERRIDE, so this must be
        blocked the same way the dedicated Create-Cluster flow blocks it —
        previously it built the Cluster directly via the ORM with no
        overlap check at all."""
        from django.urls import reverse

        self.client.force_login(self.user)

        # A third sub-county with no covering cluster, so the drawer's
        # "existing_covering_cluster" guard (which only checks the school's
        # OWN sub-county) doesn't force the "use existing" path — this
        # reaches the "create new cluster" branch.
        sub_county3 = SubCounty.objects.create(
            name="Ntunga West", district=self.district
        )
        school = School.objects.create(
            school_id="SCH-973",
            name="Overlap Test School",
            region=self.region,
            district=self.district,
            sub_county=sub_county3,
            school_type="client",
        )
        self.assertIsNone(school.cluster_id)
        # get_scoped_object_or_404 requires the school in this CCEO's own
        # portfolio.
        from apps.accounts.models import StaffSchoolAssignment

        StaffSchoolAssignment.objects.create(staff=self.profile, school_id=school.id)

        clusters_before = Cluster.objects.count()

        url = reverse("frontend:add_to_cluster_drawer", args=[school.id])
        response = self.client.post(
            url,
            {
                "cluster_action_type": "new",
                "new_cluster_name": "Overlapping Cluster",
                "new_district_id": self.district.id,
                # sub_county2 already belongs to self.cluster2 — this must
                # be rejected by create_cluster()'s sub-county-uniqueness
                # rule instead of silently succeeding.
                "new_sub_county_ids": [self.sub_county2.id],
                "responsible_staff_id": "",
                "notes": "",
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("validation_error", response.context)
        self.assertIn(
            "already covers", (response.context["validation_error"] or "").lower()
        )

        # No new cluster was created bypassing the uniqueness rule, and the
        # school was never assigned to anything.
        self.assertEqual(Cluster.objects.count(), clusters_before)
        self.assertFalse(Cluster.objects.filter(name="Overlapping Cluster").exists())
        school.refresh_from_db()
        self.assertIsNone(school.cluster_id)
