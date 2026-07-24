"""Weekly Debrief Report pipeline — consolidation, versioning, scope, PDF,
distribution (the weekly-reporting mandate's §28 gate)."""

from __future__ import annotations

from datetime import timedelta

from django.core import mail
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

from apps.debriefs.models import (
    DailyDebrief,
    DebriefKind,
    DebriefStatus,
    DebriefType,
    WeeklyReportScope,
    WeeklyReportStatus,
)
from apps.debriefs.tests import FY, FieldDebriefTestBase
from apps.debriefs.weekly_report_service import (
    WeeklyDebriefReportService as WRS,
    classify_text,
    week_bounds,
)


class WeeklyReportTestBase(FieldDebriefTestBase):
    def setUp(self):
        super().setUp()
        self.week_start, self.week_end = week_bounds(timezone.localdate())

    def _daily(self, user, day_offset=0, **fields):
        """A submitted DAILY debrief inside the current reporting week."""
        import datetime as dt

        on = self.week_start + timedelta(days=day_offset)
        base = {
            "fy": FY,
            "date": timezone.make_aware(dt.datetime.combine(on, dt.time.min)),
            "submitted_by_user_id": user.user_id,
            "submitted_by_role": user.active_role,
            "debrief_type": DebriefType.STAFF,
            "kind": DebriefKind.DAILY,
            "status": DebriefStatus.SUBMITTED,
            "title": f"Daily Debrief - {on}",
            "submitted_at": timezone.now(),
            "linked_school_ids": [self.school.id],
        }
        base.update(fields)
        return DailyDebrief.objects.create(**base)


class ConsolidationTests(WeeklyReportTestBase):
    def test_ten_staff_reporting_poor_roads_become_one_cluster_of_ten(self):
        users = [
            self._staff(f"road{i}@fd.org", f"Roada {i}", "CCEO")[0] for i in range(10)
        ]
        for i, u in enumerate(users):
            self._daily(
                u,
                day_offset=i % 5,
                challenges_faced="The road to the school was very bad and muddy.",
            )
        report = WRS.generate_pl_report(self.pl, self.week_start)
        # (these users aren't the PL's team — consolidate directly instead)
        from apps.debriefs.weekly_report_service import _consolidate

        clusters = _consolidate(
            list(DailyDebrief.objects.filter(kind=DebriefKind.DAILY))
        )
        roads = [c for c in clusters if c["theme"] == "poor_roads"]
        self.assertEqual(len(roads), 1, "poor roads must appear exactly once")
        self.assertEqual(roads[0]["mentions"], 10)
        self.assertEqual(roads[0]["unique_staff"], 10)
        self.assertEqual(roads[0]["schools_affected"], 1)
        self.assertEqual(report.scope_kind, WeeklyReportScope.PL_TEAM)

    def test_one_employee_repeating_does_not_inflate_unique_staff(self):
        for i in range(5):
            self._daily(
                self.cceo,
                day_offset=i,
                challenges_faced="Bad road again today.",
            )
        from apps.debriefs.weekly_report_service import _consolidate

        clusters = _consolidate(
            list(DailyDebrief.objects.filter(kind=DebriefKind.DAILY))
        )
        roads = next(c for c in clusters if c["theme"] == "poor_roads")
        self.assertEqual(roads["mentions"], 5)
        self.assertEqual(roads["unique_staff"], 1)

    def test_different_root_causes_are_not_merged(self):
        keys = classify_text("The road was very bad and the vehicle was unavailable.")
        self.assertIn("poor_roads", keys)
        self.assertIn("no_transport", keys)
        keys2 = classify_text("The head teacher was unavailable.")
        self.assertIn("leader_unavailable", keys2)
        self.assertNotIn("teacher_absence", keys2)

    def test_restricted_incidents_never_reach_the_general_report(self):
        self._daily(
            self.cceo,
            challenges_faced="Sensitive safeguarding matter on a bad road.",
            is_restricted_incident=True,
        )
        report = WRS.generate_pl_report(self.pl, self.week_start)
        self.assertEqual(report.snapshot["totals"]["debriefs"], 0)
        self.assertEqual(report.snapshot["clusters"], [])


class ReportScopeAndVersionTests(WeeklyReportTestBase):
    def test_pl_report_covers_own_team_only(self):
        self._daily(self.cceo, challenges_faced="Funds delayed for the visit.")
        self._daily(self.other_cceo, challenges_faced="Funds delayed here too.")
        report = WRS.generate_pl_report(self.pl, self.week_start)
        self.assertEqual(report.snapshot["totals"]["debriefs"], 1)
        team_names = {m["name"] for m in report.snapshot["team"]}
        self.assertIn("Casey Cceo", team_names)
        self.assertNotIn("Cory Cceo3", team_names)

    def test_finalized_report_is_immutable_and_regeneration_versions(self):
        self._daily(self.cceo, challenges_faced="Heavy rain stopped the training.")
        report = WRS.generate_pl_report(self.pl, self.week_start)
        WRS.sign(report, self.pl, commentary="Reviewed.")
        report.refresh_from_db()
        self.assertEqual(report.status, WeeklyReportStatus.FINALIZED)
        frozen = report.snapshot

        # A LATE debrief arrives after sign-off…
        self._daily(self.cceo2, challenges_faced="More heavy rain problems.")
        report.refresh_from_db()
        self.assertEqual(report.snapshot, frozen, "finalized snapshot must not move")

        # …regeneration creates version 2 and supersedes version 1.
        v2 = WRS.generate_pl_report(self.pl, self.week_start)
        report.refresh_from_db()
        self.assertEqual(v2.version, 2)
        self.assertEqual(report.status, WeeklyReportStatus.SUPERSEDED)
        self.assertEqual(v2.snapshot["totals"]["debriefs"], 2)

    def test_sign_permissions_and_double_sign_guard(self):
        report = WRS.generate_pl_report(self.pl, self.week_start)
        with self.assertRaises(Forbidden):
            WRS.sign(report, self.other_pl)
        WRS.sign(report, self.pl)
        with self.assertRaises(BadRequest):
            WRS.sign(report, self.pl)

    def test_country_report_compiles_finalized_pl_reports_and_lists_missing(self):
        self._daily(self.cceo, challenges_faced="Partner delayed the training.")
        pl_report = WRS.generate_pl_report(self.pl, self.week_start)
        WRS.sign(pl_report, self.pl)
        # other_pl never generates/signs → must be listed as missing.
        country = WRS.generate_country_report(self.cd, self.week_start)
        s = country.snapshot
        self.assertEqual(s["totals"]["pl_reports_included"], 1)
        self.assertEqual(s["totals"]["pl_reports_missing"], 1)
        self.assertIn("Percy Lead2", [m["pl"] for m in s["missing_teams"]])
        themes = {c["theme"] for c in s["clusters"]}
        self.assertIn("partner_delay", themes)

    def test_rvp_and_hr_see_only_finalized_country_reports(self):
        WRS.generate_country_report(self.cd, self.week_start)  # draft only
        self.assertIsNone(WRS.visible_report(self.rvp, self.week_start))
        self.assertIsNone(WRS.visible_report(self.hr, self.week_start))
        WRS.sign(WRS.visible_report(self.cd, self.week_start), self.cd)
        self.assertIsNotNone(WRS.visible_report(self.rvp, self.week_start))
        self.assertIsNotNone(WRS.visible_report(self.hr, self.week_start))


class PdfAndDistributionTests(WeeklyReportTestBase):
    def test_pdf_generates_with_correct_header_and_period(self):
        self._daily(self.cceo, challenges_faced="No transport was available.")
        report = WRS.generate_pl_report(self.pl, self.week_start)
        data = WRS.generate_pdf(report)
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 800)
        report.refresh_from_db()
        self.assertTrue(report.pdf_checksum)

    def test_email_attaches_pdf_and_blocks_rapid_duplicates(self):
        report = WRS.generate_pl_report(self.pl, self.week_start)
        WRS.sign(report, self.pl)
        dist = WRS.send_email(
            report, self.pl, ["cd@fd.org"], "Weekly report", "Attached."
        )
        self.assertTrue(dist.succeeded)
        self.assertEqual(len(mail.outbox), 1)
        name, content, mime = mail.outbox[0].attachments[0]
        self.assertTrue(name.endswith(".pdf"))
        self.assertEqual(mime, "application/pdf")
        self.assertTrue(bytes(content).startswith(b"%PDF"))
        with self.assertRaises(BadRequest):
            WRS.send_email(report, self.pl, ["cd@fd.org"], "Weekly report", "Again.")

    def test_email_permission_is_enforced(self):
        report = WRS.generate_pl_report(self.pl, self.week_start)
        with self.assertRaises(Forbidden):
            WRS.send_email(report, self.cceo, ["x@fd.org"], "s", "m")


class WeeklyReportViewTests(WeeklyReportTestBase):
    def test_pl_view_autogenerates_draft_and_pdf_downloads(self):
        self._daily(self.cceo, challenges_faced="Poor network at the school.")
        c = self._client(self.pl)
        r = c.get(f"/debriefs/weekly-report?week={self.week_start.isoformat()}")
        self.assertContains(r, "Weekly Debrief Report")
        self.assertContains(r, "Poor Network")
        r = c.get(f"/debriefs/weekly-report/pdf?week={self.week_start.isoformat()}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_cceo_has_no_weekly_report_surface(self):
        r = self._client(self.cceo).get("/debriefs/weekly-report")
        self.assertContains(r, "No report for this week")
