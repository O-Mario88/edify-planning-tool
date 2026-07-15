"""My Targets — the personal performance operating page (mandate §33).

Covers the monthly-first model end to end: strict request.user scoping, the
Current Month → Q1–Q4 → FY Cumulative period set (no Mid-Year), the five
official target areas, validated-only counting per area (Activity SF ID,
IA confirmation, MSCS approval), crediting to the month the work actually
happened, monthly→quarter→FY rollups, ledger idempotency, credit reversal,
weighted overall with zero-target renormalization, working-day pacing,
statuses, export scoping and the auto-closing To-Do integration.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    PublicHoliday,
    StaffProfile,
    StaffSchoolAssignment,
    StaffTargetProfile,
)
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord
from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
from apps.targets.models import (
    MonthlyPersonalTarget,
    MostSignificantChangeStory,
    TargetAchievementLedger,
    TargetArea,
)
from apps.targets.my_targets import MyTargetQueryService, TargetAchievementService

User = get_user_model()
FY = "2026"  # Oct 1 2025 – Sep 30 2026
TODAY = date(2026, 7, 15)  # month_of_fy 10 (July), quarter Q4
JULY = 10  # month-of-FY index for July
NOVEMBER = 2  # month-of-FY index for November


def _fixed_current(at=None):
    return {
        "today": TODAY,
        "fy": FY,
        "month_of_fy": JULY,
        "quarter": "Q4",
        "month_label": "July 2026",
    }


class MyTargetsPageTest(TestCase):
    """All service math + page behaviour pinned to a fixed 'today'."""

    def setUp(self):
        self.region = Region.objects.create(name="R")
        self.district = District.objects.create(
            name="D", region=self.region, district_type="primary"
        )
        self.user, self.sp = self._staff("me@t.org", "Me One", EdifyRole.CCEO.value)
        self.other, self.other_sp = self._staff(
            "other@t.org", "Other Two", EdifyRole.CCEO.value
        )
        self.school = School.objects.create(
            school_id="S-1",
            name="School One",
            region=self.region,
            district=self.district,
            current_fy_ssa_status="done",
        )
        StaffSchoolAssignment.objects.create(staff=self.sp, school_id=self.school.id)
        self._current = patch.object(Cal, "current", side_effect=_fixed_current)
        self._current.start()
        self.addCleanup(self._current.stop)

    def _staff(self, email, name, role):
        u = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        return u, StaffProfile.objects.create(user=u, title=role)

    def _monthly(self, area_key, month, target, user=None):
        MonthlyPersonalTarget.objects.update_or_create(
            user_id=(user or self.user).id,
            area=TargetArea.objects.get(key=area_key),
            fy=FY,
            month_of_fy=month,
            defaults={"target": target},
        )

    # Default status is ia_verified: target CREDIT requires IA verification
    # (§8), so a "done, credited" fixture visit must be IA-verified, not merely
    # "completed" (which is pre-IA and only ever provisional).
    def _visit(self, planned, status="ia_verified", sf_id="SF-1", user=None, sp=None):
        return Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            delivery_type="staff",
            status=status,
            responsible_staff_id=(sp or self.sp).id,
            fy=FY,
            quarter=Cal.quarter_of_month(Cal.month_of_fy_for(planned, FY) or 1),
            planned_date=planned,
            salesforce_activity_id=sf_id,
            scheduled_date=timezone.make_aware(
                timezone.datetime(planned.year, planned.month, planned.day, 9)
            ),
        )

    def _achieved(self, area_key="school_visits", user=None):
        return MyTargetQueryService.monthly_achievements(user or self.user, FY)[
            area_key
        ]

    # ── 1–5: page shape, scope, defaults ─────────────────────────────────────
    def test_my_targets_shows_only_logged_in_user(self):
        """Another user's validated work must never appear — and there is no
        URL parameter that can widen the scope."""
        self._visit(date(2026, 7, 6), user=self.other, sp=self.other_sp)
        TargetAchievementService.rebuild(self.other, FY)
        self._monthly("school_visits", JULY, 4)
        page = MyTargetQueryService.get_page(self.user)
        visits = next(a for a in page["area_cards"] if a["key"] == "school_visits")
        self.assertEqual(visits["achieved"], 0)  # other's credit invisible
        c = Client()
        c.force_login(self.user)
        base = c.get("/my-targets")
        tampered = c.get(f"/my-targets?user={self.other.id}&user_id={self.other.id}")

        def extract(r):
            return [
                (a["key"], a["target"], a["achieved"]) for a in r.context["area_cards"]
            ]

        self.assertEqual(extract(base), extract(tampered))  # params ignored
        self.assertIn(("school_visits", 4, 0), extract(tampered))

    def test_default_month_is_current_month(self):
        page = MyTargetQueryService.get_page(self.user)
        self.assertEqual(page["month_of_fy"], JULY)
        self.assertEqual(page["month_label"], "July 2026")
        self.assertEqual(page["period_cards"][0]["kind"], "month")
        self.assertTrue(page["period_cards"][0]["current"])

    def test_quarter_derived_from_fy_configuration(self):
        self.assertEqual(Cal.month_of_fy_for(date(2025, 10, 1), FY), 1)  # FY starts Oct
        self.assertEqual(Cal.quarter_of_month(1), "Q1")
        self.assertEqual(Cal.quarter_of_month(JULY), "Q4")
        self.assertEqual(Cal.months_of_quarter("Q2"), [4, 5, 6])
        labels = [
            c["label"] for c in MyTargetQueryService.get_page(self.user)["period_cards"]
        ]
        self.assertEqual(labels[1:5], ["Q1", "Q2", "Q3", "Q4"])

    def test_mid_year_not_rendered(self):
        c = Client()
        c.force_login(self.user)
        html = c.get("/my-targets").content.decode()
        self.assertNotIn("Mid-Year", html)
        for needle in ("Q1", "Q2", "Q3", "Q4", "FY Cumulative"):
            self.assertIn(needle, html)

    def test_only_five_official_target_areas(self):
        self.assertEqual(
            list(
                TargetArea.objects.filter(active=True)
                .order_by("sort_order")
                .values_list("label", flat=True)
            ),
            [
                "School Visits",
                "Cluster Meetings",
                "Cluster Trainings",
                "SSA Completed",
                "MSCS",
            ],
        )
        c = Client()
        c.force_login(self.user)
        html = c.get("/my-targets").content.decode()
        for area in (
            "School Visits",
            "Cluster Meetings",
            "Cluster Trainings",
            "SSA Completed",
            "MSCS",
        ):
            self.assertIn(area, html)
        self.assertNotIn("New School", html)  # superseded areas gone

    # ── 6–10: validity rules per area ────────────────────────────────────────
    def test_visit_counts_only_when_ia_verified(self):
        """Target credit requires IA verification (§8). Scheduled → no credit.
        Completed (pre-IA) with SF ID → provisional, still no credit. Only once
        IA-verified does it become validated credit."""
        self._visit(date(2026, 7, 2), status="scheduled", sf_id="")
        pre_ia = self._visit(date(2026, 7, 3), status="completed", sf_id="SF-9")
        TargetAchievementService.rebuild(self.user, FY)
        # Executed + SF ID but not yet IA-verified → provisional, NOT counted.
        self.assertEqual(self._achieved()[JULY - 1], 0)
        row = TargetAchievementLedger.objects.get(source_id=pre_ia.id)
        self.assertEqual(row.validation_status, "provisional")
        # IA verifies → credited.
        Activity.objects.filter(id=pre_ia.id).update(status="ia_verified")
        TargetAchievementService.rebuild(self.user, FY)
        self.assertEqual(self._achieved()[JULY - 1], 1)

    def test_ssa_counts_only_after_ia_confirmation(self):
        rec = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=timezone.make_aware(timezone.datetime(2026, 7, 6, 10)),
            fy=FY,
            quarter="Q4",
            verification_status="pending",
            collected_by_user_id=self.user.id,
            uploaded_by=self.user.id,
        )
        TargetAchievementService.rebuild(self.user, FY)
        self.assertEqual(self._achieved("ssa_completed")[JULY - 1], 0)
        SsaRecord.objects.filter(id=rec.id).update(verification_status="confirmed")
        TargetAchievementService.rebuild(self.user, FY)
        self.assertEqual(self._achieved("ssa_completed")[JULY - 1], 1)

    def test_mscs_counts_only_after_approval(self):
        story = MostSignificantChangeStory.objects.create(
            user_id=self.user.id,
            title="Reading corner",
            narrative="…",
            story_date=date(2026, 7, 8),
            status="submitted",
        )
        TargetAchievementService.rebuild(self.user, FY)
        self.assertEqual(self._achieved("mscs")[JULY - 1], 0)
        story.status = "approved"
        story.save(update_fields=["status"])
        TargetAchievementService.rebuild(self.user, FY)
        self.assertEqual(self._achieved("mscs")[JULY - 1], 1)
        story.status = "rejected"
        story.save(update_fields=["status"])
        TargetAchievementService.rebuild(self.user, FY)
        self.assertEqual(self._achieved("mscs")[JULY - 1], 0)

    def test_late_validation_credits_actual_activity_month(self):
        """Work done in November validated today still credits November/Q1."""
        a = self._visit(date(2025, 11, 10))
        TargetAchievementService.rebuild(self.user, FY)
        row = TargetAchievementLedger.objects.get(source_id=a.id)
        self.assertEqual(row.credited_month, NOVEMBER)
        self.assertEqual(row.credited_quarter, "Q1")
        series = self._achieved()
        self.assertEqual(series[NOVEMBER - 1], 1)
        self.assertEqual(series[JULY - 1], 0)

    def test_returned_activity_reverses_target_credit(self):
        a = self._visit(date(2026, 7, 6))
        TargetAchievementService.rebuild(self.user, FY)
        self.assertEqual(self._achieved()[JULY - 1], 1)
        Activity.objects.filter(id=a.id).update(status="returned_by_ia")
        TargetAchievementService.rebuild(self.user, FY)
        row = TargetAchievementLedger.objects.get(source_id=a.id)
        self.assertEqual(row.validation_status, "reversed")
        self.assertEqual(self._achieved()[JULY - 1], 0)

    # ── 11–14: rollups + ledger integrity ────────────────────────────────────
    def test_monthly_targets_roll_up_to_quarter_and_fy(self):
        for m in range(1, 13):
            self._monthly("school_visits", m, 2)
        self._visit(date(2025, 10, 6))  # Oct = Q1
        self._visit(date(2025, 11, 10))  # Nov = Q1
        self._visit(date(2026, 7, 6))  # Jul = Q4
        page = MyTargetQueryService.get_page(self.user)
        row = next(r for r in page["matrix_rows"] if r["key"] == "school_visits")
        month_c, q1, q2, q3, q4, fy = row["cells"]
        self.assertEqual((q1["t"], q1["a"]), (6, 2))  # 3 months × 2; Oct+Nov work
        self.assertEqual((q2["t"], q2["a"]), (6, 0))
        self.assertEqual((q4["t"], q4["a"]), (6, 1))
        self.assertEqual((fy["t"], fy["a"]), (24, 3))  # FY = sum of months
        self.assertEqual(month_c["a"], 1)  # July card

    def test_annual_fallback_split_sums_to_annual(self):
        """No explicit monthly rows → the annual profile splits across the 12
        FY months and the FY rollup still equals the annual value."""
        StaffTargetProfile.objects.create(staff=self.sp, fy=FY, visits_target=8)
        months = MyTargetQueryService.monthly_targets(self.user, FY)["school_visits"]
        self.assertEqual(sum(months), 8)
        self.assertEqual(len(months), 12)
        self.assertTrue(all(m in (0, 1) for m in months))

    def test_duplicate_source_never_counted_twice(self):
        a = self._visit(date(2026, 7, 6))
        TargetAchievementService.rebuild(self.user, FY)
        TargetAchievementService.rebuild(self.user, FY)  # idempotent rebuild
        self.assertEqual(
            TargetAchievementLedger.objects.filter(
                user_id=self.user.id, source_type="activity", source_id=a.id
            ).count(),
            1,
        )
        self.assertEqual(self._achieved()[JULY - 1], 1)

    def test_zero_target_area_excluded_from_overall(self):
        """Only School Visits is assigned (4, 2 done) — the overall must be 50%,
        not 50% × its 30% weight."""
        self._monthly("school_visits", JULY, 4)
        self._visit(date(2026, 7, 2))
        self._visit(date(2026, 7, 3), sf_id="SF-2")
        page = MyTargetQueryService.get_page(self.user)
        self.assertEqual(page["period_cards"][0]["pct"], 50)

    def test_weighted_overall_uses_configured_weights(self):
        """Visits (w30) at 100% + Meetings (w15) at 0% → (100·30+0·15)/45 = 67."""
        self._monthly("school_visits", JULY, 1)
        self._monthly("cluster_meetings", JULY, 4)
        self._visit(date(2026, 7, 2))
        page = MyTargetQueryService.get_page(self.user)
        self.assertEqual(page["period_cards"][0]["pct"], 67)

    # ── 15–17: pacing + statuses ─────────────────────────────────────────────
    def test_future_quarter_shows_not_started(self):
        self._current.stop()  # re-pin 'today' inside Q1 for this test
        nov = patch.object(
            Cal,
            "current",
            side_effect=lambda at=None: {
                "today": date(2025, 11, 15),
                "fy": FY,
                "month_of_fy": NOVEMBER,
                "quarter": "Q1",
                "month_label": "November 2025",
            },
        )
        nov.start()
        self.addCleanup(nov.stop)
        for m in range(1, 13):
            self._monthly("school_visits", m, 2)
        page = MyTargetQueryService.get_page(self.user)
        q3 = next(c for c in page["period_cards"] if c["label"] == "Q3")
        self.assertEqual(q3["status"], "Not Started")
        self.assertEqual(q3["pace"], 0)

    def test_working_days_exclude_holidays_and_approved_leave(self):
        start, end = date(2026, 7, 1), date(2026, 8, 1)
        self.assertEqual(Cal.working_days(start, end), 23)  # July 2026 weekdays
        PublicHoliday.objects.create(date=date(2026, 7, 6), name="Holiday")
        self.assertEqual(Cal.working_days(start, end), 22)
        Leave.objects.create(
            staff=self.sp,
            type="annual",
            status="approved",
            start_date="2026-07-07",
            end_date="2026-07-08",
            days=2,
        )
        self.assertEqual(Cal.working_days(start, end, self.user), 20)

    def test_pacing_status_bands(self):
        s = MyTargetQueryService.status_for
        self.assertEqual(s(0, 0, 50, True)[0], "Not Assigned")
        self.assertEqual(s(0, 10, 0, False)[0], "Not Started")
        self.assertEqual(s(10, 10, 50, True)[0], "Complete")
        self.assertEqual(s(12, 10, 50, True)[0], "Exceeded")
        self.assertEqual(s(5, 10, 50, True)[0], "On Track")  # gap 0
        self.assertEqual(s(45, 100, 50, True)[0], "On Track")  # gap 5 ≤ band
        self.assertEqual(s(3, 10, 50, True)[0], "At Risk")  # gap 20
        self.assertEqual(s(2, 10, 50, True)[0], "Off Track")  # gap 30

    # ── 18–21: HTTP endpoints + To-Do integration ────────────────────────────
    def test_export_respects_user_scope(self):
        self._visit(date(2026, 7, 6), user=self.other, sp=self.other_sp)
        TargetAchievementService.rebuild(self.other, FY)
        self._monthly("school_visits", JULY, 4)
        c = Client()
        resp_anon = c.get(f"/my-targets/export?fy={FY}")
        self.assertIn(resp_anon.status_code, (301, 302))  # login required
        c.force_login(self.user)
        resp = c.get(f"/my-targets/export?fy={FY}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp["Content-Type"])
        body = resp.content.decode()
        self.assertIn("School Visits,July 2026,4,0", body)  # own numbers only
        self.assertIn("FY Cumulative", body)

    def test_area_drawer_explains_missing_sf_id(self):
        self._visit(date(2026, 7, 6), status="completed", sf_id="")
        c = Client()
        c.force_login(self.user)
        resp = c.get(f"/my-targets/area-drawer?area=school_visits&fy={FY}&month={JULY}")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("Activity SF ID missing", html)
        self.assertIn("School One", html)

    def test_mscs_submission_enters_review_not_credit(self):
        c = Client()
        c.force_login(self.user)
        resp = c.post(
            "/my-targets/mscs",
            {
                "title": "Teacher-led reading club",
                "story_date": "2026-07-10",
                "narrative": "P4 learners now run a daily reading club.",
            },
        )
        self.assertIn(resp.status_code, (200, 302))
        story = MostSignificantChangeStory.objects.get(user_id=self.user.id)
        self.assertEqual(story.status, "submitted")
        TargetAchievementService.rebuild(self.user, FY)
        self.assertEqual(self._achieved("mscs")[JULY - 1], 0)  # not yet approved

    def test_behind_target_todo_appears_and_auto_closes(self):
        from apps.command_center.todo_service import get_todos

        self._monthly("school_visits", JULY, 4)  # 0/4 mid-month → Off Track
        titles = [t["title"] for t in get_todos(self.user)["todos"]]
        self.assertIn("Recover School Visits target", titles)
        for d in (2, 3, 6, 7):  # complete the month's target
            self._visit(date(2026, 7, d), sf_id=f"SF-{d}")
        titles = [t["title"] for t in get_todos(self.user)["todos"]]
        self.assertNotIn("Recover School Visits target", titles)  # auto-closed
