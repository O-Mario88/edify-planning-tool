"""Route Intelligence tests — location hierarchy, phrase parsing, quality
scoring, district rules, working-day feasibility, CD-target integration,
costing↔route batch sync, To-Dos and health checks."""

from __future__ import annotations

from datetime import date

from django.test import TestCase
from freezegun import freeze_time

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.rbac import EdifyRole
from apps.geography.models import (
    District,
    Region,
    SecondaryDistrictGroup,
    SecondaryDistrictGroupMember,
    SubCounty,
)
from apps.schools.models import School

from apps.daily_visit_batches.services import remove_school, schedule_visits
from apps.routes.engine import (
    PlanningRoutePreviewService,
)
from apps.routes.health import route_intelligence_checks
from apps.routes.location import (
    SchoolLocationParserService,
    extract_location_phrases,
)
from apps.routes.models import DailyVisitRouteBatch, SchoolGeoPoint

PRIMARY_RATES = [
    ("primary_transport_per_day", 280000),
    ("primary_lunch_per_day", 30000),
]
SECONDARY_RATES = [
    ("secondary_transport_per_day", 330000),
    ("secondary_lunch_per_day", 30000),
    ("secondary_accommodation_per_night", 150000),
    ("secondary_overnight_dinner_per_day", 50000),
]
VISIT_DAY = date(2026, 8, 3)


@freeze_time("2026-07-27")  # fixed Monday on/before VISIT_DAY — REG-02 §1.1:
# apps.command_center.todo_service._route_todos and
# apps.routes.health.route_intelligence_checks both filter route batches by
# `visit_date__gte=date.today()`, so this whole class implicitly needs
# "today" to be on or before VISIT_DAY for those to see it as upcoming —
# without freezing, this test class silently breaks once the real
# wall-clock date passes VISIT_DAY.
class RouteIntelligenceTestCase(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Route Region")
        self.primary = District.objects.create(
            name="Route Primary", region=self.region, district_type="primary"
        )
        self.sec_a = District.objects.create(
            name="Route Secondary A", region=self.region, district_type="secondary"
        )
        self.sec_b = District.objects.create(
            name="Route Secondary B", region=self.region, district_type="secondary"
        )
        self.sc_goma = SubCounty.objects.create(name="Goma", district=self.primary)
        self.sc_kasawo = SubCounty.objects.create(name="Kasawo", district=self.primary)
        self.sc_nama = SubCounty.objects.create(name="Nama", district=self.primary)
        self.sc_ntenjeru = SubCounty.objects.create(
            name="Ntenjeru", district=self.primary
        )

        self.catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda",
            fy="2026",
            version=1,
            defaults={
                "is_active": True,
                "label": "Route Test Catalogue",
                "required_school_visits_per_day": 3,
            },
        )
        self.catalogue.required_school_visits_per_day = 3
        self.catalogue.is_active = True
        self.catalogue.save(
            update_fields=["required_school_visits_per_day", "is_active"]
        )
        for key, cost in PRIMARY_RATES + SECONDARY_RATES:
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key,
                    "unit_cost": cost,
                    "fy": "2026",
                    "catalogue": self.catalogue,
                    "version": 1,
                },
            )

        self.staff = User.objects.create_user(
            email="route@test.com",
            name="Route Staff",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff_profile = StaffProfile.objects.create(user=self.staff, title="CCEO")

        def mk(school_id, name, district, sub_county, **extra):
            s = School.objects.create(
                school_id=school_id,
                name=name,
                region=self.region,
                district=district,
                sub_county=sub_county,
                current_fy_ssa_status="done",
                planning_readiness="ready",
                **extra,
            )
            StaffSchoolAssignment.objects.create(
                staff=self.staff_profile, school_id=s.id
            )
            return s

        # Goma cluster of schools (same sub-county).
        self.g1 = mk("RT-G1", "Goma Hill Academy", self.primary, self.sc_goma)
        self.g2 = mk("RT-G2", "Goma Parents School", self.primary, self.sc_goma)
        self.g3 = mk("RT-G3", "Goma Central School", self.primary, self.sc_goma)
        self.g4 = mk("RT-G4", "Goma Lakeside School", self.primary, self.sc_goma)
        # Spread across other sub-counties.
        self.k1 = mk("RT-K1", "Kasawo Junior", self.primary, self.sc_kasawo)
        self.n1 = mk("RT-N1", "Nama Primary", self.primary, self.sc_nama)
        self.t1 = mk("RT-T1", "Ntenjeru Primary", self.primary, self.sc_ntenjeru)
        # Secondary district schools.
        self.sa = mk("RT-SA", "Sec A School", self.sec_a, None)
        self.sb = mk("RT-SB", "Sec B School", self.sec_b, None)
        # Weak-location school: no sub-county/parish/coords, only address text.
        self.weak = mk(
            "RT-WK",
            "Weak Location School",
            self.primary,
            None,
            shipping_address="Route Primary, Nakifuma Hill",
        )

        self.base_fields = {
            "activityType": "school_visit",
            "deliveryType": "staff",
            "activityPurposeText": "Routine visit",
            "focusIntervention": "leadership",
        }

    def _schedule(self, school_ids, visit_date=VISIT_DAY, reason=None):
        return schedule_visits(
            school_ids=school_ids,
            scheduled_date=visit_date,
            activity_common_fields=self.base_fields,
            reason=reason,
            principal=self.staff,
        )

    def _preview(self, schools):
        return PlanningRoutePreviewService.preview(
            school_ids=[s.school_id for s in schools], responsible_user=self.staff.id
        )

    # ── 1. Location source hierarchy ─────────────────────────────────────────
    def test_location_priority_coordinates_first(self):
        School.objects.filter(id=self.g1.id).update(latitude=0.35, longitude=32.75)
        self.g1.refresh_from_db()
        r = SchoolLocationParserService.resolve(self.g1)
        self.assertEqual(r["source"], "coordinates")
        self.assertEqual(r["confidence"], "high")
        # Structured sub-county when no coordinates.
        r2 = SchoolLocationParserService.resolve(self.g2)
        self.assertEqual(r2["source"], "district_subcounty")
        self.assertEqual(r2["confidence"], "high")
        # Address text only → LOW, phrase extracted, never rejected.
        r3 = SchoolLocationParserService.resolve(self.weak)
        self.assertEqual(r3["source"], "address_text")
        self.assertEqual(r3["confidence"], "low")
        self.assertIn("Nakifuma Hill", r3["tokens"])
        # A verified GeoPoint outranks everything.
        SchoolGeoPoint.objects.create(
            school_id=self.weak.id, latitude=0.3, longitude=32.7
        )
        r4 = SchoolLocationParserService.resolve(self.weak)
        self.assertEqual(r4["source"], "coordinates")
        self.assertEqual(r4["confidence"], "high")

    # ── 2. Phrase parsing, not most-common word ──────────────────────────────
    def test_text_parser_extracts_phrases_not_generic_words(self):
        self.assertEqual(
            extract_location_phrases(
                "Mukono, Goma Division, Goma Division, Nakifuma Hill", "Mukono"
            ),
            ["Goma", "Nakifuma Hill"],
        )
        # Generic words alone prove nothing → no phrases.
        self.assertEqual(
            extract_location_phrases(
                "Mukono, Central Trading Centre, Primary School", "Mukono"
            ),
            [],
        )

    # ── 3. Same sub-county day = Excellent ───────────────────────────────────
    def test_same_subcounty_day_is_excellent(self):
        p = self._preview([self.g1, self.g2, self.g3])  # 3 = CD target
        self.assertEqual(p["status"], "excellent")
        self.assertGreaterEqual(p["score"], 85)
        self.assertTrue(p["feasible"])
        self.assertEqual(p["detected_area"], "Goma")
        self.assertEqual(p["warnings"], [])

    # ── 4. Scattered day degrades ────────────────────────────────────────────
    def test_scattered_day_is_risky_or_worse(self):
        p = self._preview([self.g1, self.k1, self.n1, self.t1])
        self.assertIn(p["status"], ("risky", "not_feasible"))
        self.assertTrue(any("spread across" in w for w in p["warnings"]))

    # ── 5. Primary + secondary mix is Blocked ────────────────────────────────
    def test_mixed_primary_secondary_is_blocked(self):
        p = self._preview([self.g1, self.sa])
        self.assertEqual(p["status"], "blocked")
        self.assertTrue(p["blocked"])
        self.assertTrue(
            any(
                "mixed" in w.lower() or "primary district" in w.lower()
                for w in p["warnings"]
            )
        )

    # ── 6. Secondary route group exception ───────────────────────────────────
    def test_secondary_group_exception(self):
        p = self._preview([self.sa, self.sb])
        self.assertEqual(p["status"], "blocked")  # ungrouped secondary districts
        group = SecondaryDistrictGroup.objects.create(
            name="North Route", status="approved"
        )
        SecondaryDistrictGroupMember.objects.create(group=group, district=self.sec_a)
        SecondaryDistrictGroupMember.objects.create(group=group, district=self.sec_b)
        p2 = self._preview([self.sa, self.sb])
        self.assertNotEqual(p2["status"], "blocked")

    # ── 7. Working-day overload → Not Feasible + split/reduce advice ─────────
    def test_working_day_overload_not_feasible(self):
        many = [
            self.g1,
            self.g2,
            self.g3,
            self.g4,
            self.k1,
            self.n1,
            self.t1,
        ]  # 7 schools
        p = self._preview(many)
        self.assertFalse(p["feasible"])
        self.assertTrue(any("exceeds the 8h working day" in w for w in p["warnings"]))
        self.assertTrue(
            any(r["kind"] in ("reduce", "split") for r in p["recommendations"])
        )

    # ── 8. Coordinates confirm the route ─────────────────────────────────────
    def test_coordinates_confirm_route_and_drive_distance(self):
        School.objects.filter(id=self.g1.id).update(latitude=0.350, longitude=32.750)
        School.objects.filter(id=self.g2.id).update(latitude=0.360, longitude=32.760)
        School.objects.filter(id=self.g3.id).update(latitude=0.370, longitude=32.770)
        p = self._preview([self.g1, self.g2, self.g3])
        self.assertEqual(p["coords_used"], 3)
        self.assertIsNotNone(p["est_distance_km"])
        self.assertEqual(p["status"], "excellent")
        self.assertEqual(p["score"], 100)  # 30 + 25 + 20 + 15 + 10

    # ── 9. Far-apart coordinates kill the coordinate bonus ───────────────────
    def test_far_coordinates_lower_score(self):
        School.objects.filter(id=self.g1.id).update(latitude=0.30, longitude=32.50)
        School.objects.filter(id=self.g2.id).update(
            latitude=0.30, longitude=33.10
        )  # ~67 km east
        School.objects.filter(id=self.g3.id).update(
            latitude=0.90, longitude=32.50
        )  # ~67 km north
        p = self._preview([self.g1, self.g2, self.g3])
        self.assertLess(p["score"], 100)
        self.assertFalse(p["feasible"])  # >130 km of legs at 30 km/h swallows the day

    # ── 10. CD target integration ────────────────────────────────────────────
    def test_cd_target_warning_and_add_recommendation(self):
        p = self._preview([self.g1, self.g2])  # 2 of target 3
        self.assertFalse(p["meets_target"])
        self.assertTrue(
            any("CD target is 3" in w and "You selected 2" in w for w in p["warnings"])
        )
        add = next((r for r in p["recommendations"] if r["kind"] == "add"), None)
        self.assertIsNotNone(add)
        self.assertIn("Goma", add["message"])  # suggests nearby Goma schools

    # ── 11. Scheduling builds the route twin; counts stay in step ────────────
    def test_schedule_visits_builds_route_batch_and_counts_match(self):
        self._schedule(["RT-G1", "RT-G2", "RT-G3"])
        rb = DailyVisitRouteBatch.objects.get(
            responsible_user=self.staff.id, visit_date=VISIT_DAY
        )
        self.assertEqual(rb.school_count, 3)
        self.assertIsNotNone(rb.cost_batch)
        self.assertEqual(rb.school_count, rb.cost_batch.school_count)
        self.assertEqual(rb.status, "excellent")
        self.assertEqual(rb.target_snapshot, 3)
        # Removing a school re-syncs both twins.
        from apps.activities.models import Activity

        act = Activity.objects.filter(daily_visit_batch=rb.cost_batch).first()
        remove_school(activity_id=act.id)
        rb.refresh_from_db()
        self.assertEqual(rb.school_count, 2)
        self.assertEqual(rb.school_count, rb.cost_batch.school_count)

    # ── 12. Low location confidence → Data Quality To-Do (never a rejection) ─
    def test_low_confidence_creates_data_quality_todo(self):
        self._schedule(["RT-WK", "RT-G1", "RT-G2"], reason=None)
        rb = DailyVisitRouteBatch.objects.get(
            responsible_user=self.staff.id, visit_date=VISIT_DAY
        )
        self.assertEqual(rb.confidence, "low")  # worst school in the day
        from apps.command_center.todo_service import _route_todos

        todos = _route_todos(self.staff, "CCEO")
        self.assertTrue(
            any(t["title"] == "Fix school location / coordinates" for t in todos)
        )

    # ── 13. Health checks count real workflow gaps ───────────────────────────
    def test_health_checks_report_real_gaps(self):
        self._schedule(
            ["RT-G1", "RT-G2"], reason="area recovery week"
        )  # below target, with reason
        checks = route_intelligence_checks()
        self.assertEqual(checks["belowTargetNoReason"], 0)
        # Strip the recorded reason (legacy-data simulation) → flagged.
        from apps.daily_visit_batches.models import DailyVisitBatch

        DailyVisitBatch.objects.all().update(reason=None)
        checks = route_intelligence_checks()
        self.assertEqual(checks["belowTargetNoReason"], 1)
        # Cost/route count drift is flagged.
        DailyVisitRouteBatch.objects.all().update(school_count=9)
        checks = route_intelligence_checks()
        self.assertEqual(checks["costRouteCountMismatch"], 1)
        # A planned day with no route twin is flagged.
        DailyVisitRouteBatch.objects.all().delete()
        checks = route_intelligence_checks()
        self.assertEqual(checks["plannedVisitNoRouteBatch"], 1)

    # ── 14. Preview endpoint is schedule-role gated + renders ────────────────
    def test_route_preview_endpoint(self):
        self.client.force_login(self.staff)
        resp = self.client.post(
            "/planning/route-preview",
            {"school_ids": ["RT-G1", "RT-G2", "RT-G3"], "scheduled_date": "2026-08-03"},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Route Quality: Excellent", body)
        self.assertIn("Detected area", body)
