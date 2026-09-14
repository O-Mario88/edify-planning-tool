"""Impact reports and their release (IA review, owner, 2026-09-13).

Pinned here:
- audience versions: donors receive aggregates only, with cells resting on
  fewer than five schools suppressed and no school, staff or id anywhere; a
  school receives its own results only; leadership receives the snapshot;
- only Impact Assessment writes a report, only its author edits the draft,
  and another country's reports are not found;
- submitting freezes the evidence with a hash, and later data never changes
  it; a correction is a new version that supersedes the old one;
- a second IA officer reviews, the Country Director only where the country
  has one officer, and the author never; returning needs a note;
- the reviewer releases to leadership and the Country Director is told and
  answers each recommendation (a rejection says why); school briefs go to
  each school's account owner as a TeamAction the owner closes by recording
  what the school said; the donor version is requested by the reviewer or
  the Country Director and approved by an RVP covering the country who did
  not request it;
- the pages refuse other roles and other countries, the RVP reads aggregates
  and never the annex; downloads are audited; the live annex applies its
  period, names who generated it and keeps numbers numeric;
- the Country Director's dashboard section and "impact" export read the
  latest released snapshot; Impact Assessment sees its own country's quality
  flags only;
- the notification routes open the report, and the To-Do builder, the
  register and the dashboard section cost a fixed number of queries.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffGeographyAssignment, StaffProfile, User
from apps.audit.models import AuditLog
from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.impact import redaction
from apps.impact import reports as rp
from apps.impact.models import (
    ImpactReport,
    ImpactReportRecommendation,
    ImpactReportRelease,
)
from apps.impact.report_todos import report_todos
from apps.notifications.models import Notification
from apps.notifications.services import NotificationLinkResolver
from apps.planning.action_models import TeamAction
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

IA = EdifyRole.IMPACT_ASSESSMENT.value
CD = EdifyRole.COUNTRY_DIRECTOR.value
RVP = EdifyRole.REGIONAL_VICE_PRESIDENT.value
CCEO = EdifyRole.CCEO.value
ADMIN = EdifyRole.ADMIN.value
LE = SsaIntervention.LEARNING_ENVIRONMENT.value

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ia-report-tests",
    }
}


def _user(email, role, country="Uganda", roles=None):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].replace("-", " ").title(),
        roles=roles or [role],
        active_role=role,
        password="x",
        is_active=True,
    )
    if country is not None:
        StaffProfile.objects.create(user=user, title=role, country=country)
    return User.objects.select_related("staff_profile").get(pk=user.pk)


def _ssa(school, days_ago, score):
    record = SsaRecord.objects.create(
        school=school,
        fy=get_operational_fy(),
        quarter="Q1",
        average_score=score,
        verification_status="confirmed",
        date_of_ssa=timezone.now() - timedelta(days=days_ago),
        uploaded_by="t",
    )
    SsaScore.objects.create(ssa_record=record, intervention=LE, score=score)
    return record


REPORT_DATA = {
    "title": "Learning environment FY review",
    "methodology": "Confirmed SSA pairs of the project cohort.",
    "findings": "School Uganda 0 improved; Ivy Owner shared the evidence.",
    "limitations": "Self-assessed scores; no comparison group.",
    "programme_areas": ["training"],
}


# ── Redaction ────────────────────────────────────────────────────────────────


def _snapshot(n_schools=3, *, measured=3):
    rows = []
    for i in range(n_schools):
        rows.append(
            {
                "school_id": f"sch-id-{i:04d}",
                "school": f"Hill School {i}",
                "owner": "Grace Owner",
                "owner_id": f"owner-id-{i:04d}",
                "project_id": "project-0001",
                "project": "CC-SEL",
                "intervention": "Learning Environment",
                "state": "improved" if i < measured else "baseline_missing",
                "status": "Improved",
                "measured": i < measured,
                "baseline": 4.0,
                "follow_up": 6.0,
                "delta": 2.0,
                "baseline_id": f"ssa-base-{i:04d}",
                "follow_up_id": f"ssa-follow-{i:04d}",
                "baseline_date": "2025-11-01",
                "follow_up_date": "2026-08-01",
                "mapping_version": 2,
            }
        )
    return {
        "report": {
            "id": "report-0001",
            "title": "Review",
            "country": "Uganda",
            "fy": "2026",
            "version": 1,
        },
        "people": ["Ida Author"],
        "cohort": rp.summarise_rows(rows),
        "domains": [
            {
                "name": "Learning Environment",
                "pairs": measured,
                "schools": measured,
                "improved_pct": 100,
                "declined_pct": 0,
                "delta": 2.0,
            }
        ],
        "rows": rows,
        "portfolio": {
            "fy": "2026",
            "prev_fy": "2025",
            "schools_in_scope": 40,
            "measured": 12,
            "improved_pct": 50,
            "declined_pct": 25,
            "rows": [
                {
                    "name": "Educational quality",
                    "is_area": True,
                    "n": 12,
                    "improved_pct": 50,
                },
                {"name": "Leadership", "is_area": False, "n": 3, "improved_pct": 67},
            ],
            "limitation": "Portfolio limitation verbatim.",
        },
        "evidence": {
            "learning": {"schools": 2, "comparisons": 3, "improved_pct": 66},
            "discipleship": {"schools": 9, "with_groups_pct": 44},
            "edtech": {"schools": 0, "deployments": 0},
        },
        "lending": {
            "verified_ids": ["loan-concl-01"],
            "by_classification": {"positive": 1},
        },
        "findings": [{"id": "finding-0001", "statement": "x"}],
        "limitation": "Cohort limitation verbatim.",
    }


class RedactionTests(SimpleTestCase):
    def test_donors_get_aggregates_with_small_cells_suppressed_and_no_names(self):
        snapshot = _snapshot()
        payload = redaction.redact(
            snapshot,
            redaction.DONOR,
            narrative={
                "findings": "Hill School 1 improved after Grace Owner's visit (ssa-base-0001).",
                "limitations": "Ida Author notes the sample is small.",
            },
        )
        text = json.dumps(payload)
        for secret in (
            "Hill School",
            "Grace Owner",
            "Ida Author",
            "sch-id-",
            "owner-id-",
            "ssa-base-",
            "project-0001",
            "loan-concl-01",
            "finding-0001",
        ):
            self.assertNotIn(secret, text)
        self.assertEqual(payload["cohort"]["measured"], redaction.SUPPRESSED)
        self.assertEqual(payload["cohort"]["improved_pct"], redaction.SUPPRESSED)
        self.assertEqual(payload["portfolio"]["measured"], 12)
        self.assertEqual(payload["portfolio"]["improved_pct"], 50)
        leadership = [
            r for r in payload["portfolio"]["rows"] if r["name"] == "Leadership"
        ][0]
        self.assertEqual(leadership["measured"], redaction.SUPPRESSED)
        self.assertEqual(leadership["improved_pct"], redaction.SUPPRESSED)
        self.assertTrue(payload["evidence"]["learning"][redaction.SUPPRESSED])
        self.assertEqual(payload["evidence"]["discipleship"]["with_groups_pct"], 44)
        self.assertEqual(
            payload["lending"]["verified_conclusions"], redaction.SUPPRESSED
        )
        self.assertIn("Cohort limitation verbatim.", payload["limitations"])
        self.assertIn("Portfolio limitation verbatim.", payload["limitations"])
        self.assertIn("[a school]", payload["narrative"]["findings"])
        self.assertIn("[a staff member]", payload["narrative"]["findings"])
        self.assertGreater(payload["suppressed_cells"], 0)

    def test_five_schools_are_not_suppressed(self):
        payload = redaction.redact(_snapshot(6, measured=5), redaction.DONOR)
        self.assertEqual(payload["cohort"]["measured"], 5)
        self.assertEqual(payload["cohort"]["improved_pct"], 100)
        self.assertEqual(payload["domains"][0]["median_change"], 2.0)

    def test_a_school_reads_only_its_own_results(self):
        snapshot = _snapshot()
        payload = redaction.redact(
            snapshot,
            redaction.SCHOOL,
            school_id="sch-id-0001",
            school_name="Hill School 1",
            narrative={
                "findings": "Hill School 0 and Hill School 1 improved; Grace Owner visited."
            },
        )
        self.assertEqual(len(payload["results"]), 1)
        text = json.dumps(payload)
        self.assertNotIn("Hill School 0", text)
        self.assertNotIn("Grace Owner", text)
        self.assertNotIn("ssa-", text)
        self.assertNotIn("sch-id", text)
        self.assertIn("Hill School 1", payload["narrative"]["findings"])

    def test_leadership_keeps_the_snapshot(self):
        snapshot = _snapshot()
        payload = redaction.redact(snapshot, redaction.LEADERSHIP)
        self.assertEqual(payload["snapshot"]["rows"], snapshot["rows"])
        with self.assertRaises(ValueError):
            redaction.redact(snapshot, "press")


# ── Fixture ──────────────────────────────────────────────────────────────────


@override_settings(CACHES=LOCMEM)
class ReportFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.ug = Region.objects.create(name="Report Central", country="Uganda")
        cls.ke = Region.objects.create(name="Report Coast", country="Kenya")
        cls.ug_district = District.objects.create(name="Report Wakiso", region=cls.ug)
        cls.ke_district = District.objects.create(name="Report Kilifi", region=cls.ke)
        cls.project = Project.objects.create(
            name="CC-SEL", code="RPT-CCSEL", intervention=LE
        )
        cls.ida = _user("ida-author@edify.test", IA)
        cls.ivan = _user("ivan-reviewer@edify.test", IA)
        cls.kofi = _user("kofi-ia@edify.test", IA, country="Kenya")
        cls.cd = _user("carol-cd@edify.test", CD)
        cls.ke_cd = _user("ken-cd@edify.test", CD, country="Kenya")
        cls.rvp = _user("ruth-rvp@edify.test", RVP, country=None)
        cls.ke_rvp = _user("kim-rvp@edify.test", RVP, country="Kenya")
        StaffGeographyAssignment.objects.create(
            staff=StaffProfile.objects.get(user=cls.ke_rvp), region_id=cls.ke.id
        )
        cls.owner = _user("ivy-owner@edify.test", CCEO)
        cls.other_cceo = _user("oscar-cceo@edify.test", CCEO)
        cls.admin = _user("adam-admin@edify.test", ADMIN, country=None)
        owner_profile = StaffProfile.objects.get(user=cls.owner)
        cls.schools = []
        for i in range(3):
            school = School.objects.create(
                name=f"School Uganda {i}",
                school_id=f"RPT-UG-{i}",
                region=cls.ug,
                district=cls.ug_district,
                account_owner_id=owner_profile.id if i < 2 else None,
                account_owner_status="matched" if i < 2 else "unmatched",
            )
            baseline = _ssa(school, 300, 4.0)
            follow_up = _ssa(school, 10, 6.0)
            ProjectSchoolAssignment.objects.create(
                project=cls.project,
                school=school,
                baseline_ssa=baseline,
                baseline_score=4.0,
                follow_up_ssa=follow_up,
                follow_up_score=6.0,
                impact_classification="improved",
                mapping_version=1,
            )
            cls.schools.append(school)
        kenya = School.objects.create(
            name="School Kenya",
            school_id="RPT-KE-0",
            region=cls.ke,
            district=cls.ke_district,
        )
        ProjectSchoolAssignment.objects.create(project=cls.project, school=kenya)
        cls.kenya_school = kenya

    def draft(self, author=None, **extra):
        return rp.create_report(
            author or self.ida, {**REPORT_DATA, "fy": self.fy, **extra}
        )

    def submitted(self, **extra):
        report = self.draft(**extra)
        rp.add_recommendation(
            self.ida,
            report.id,
            {
                "text": "Fund a second EdTech cohort",
                "owner_role": CD,
                "due_date": (timezone.localdate() + timedelta(days=30)).isoformat(),
            },
        )
        return rp.submit_report(self.ida, report.id)

    def released(self):
        report = self.submitted()
        rp.review_report(self.ivan, report.id, decision="approve")
        rp.release_to_leadership(self.ivan, report.id)
        report.refresh_from_db()
        return report


# ── Lifecycle ────────────────────────────────────────────────────────────────


class ReportLifecycleTests(ReportFixture):
    def test_only_impact_assessment_writes_and_only_the_author_edits(self):
        with self.assertRaises(Forbidden):
            rp.create_report(self.cd, {**REPORT_DATA, "fy": self.fy})
        report = self.draft()
        self.assertEqual(report.country, "Uganda")
        with self.assertRaises(Forbidden):
            rp.update_report(self.ivan, report.id, {**REPORT_DATA, "fy": self.fy})
        with self.assertRaises(NotFoundError):
            rp.update_report(self.kofi, report.id, {**REPORT_DATA, "fy": self.fy})
        with self.assertRaises(BadRequest):
            rp.create_report(self.ida, {**REPORT_DATA, "fy": "1999"})
        with self.assertRaises(BadRequest):
            rp.create_report(
                self.ida,
                {
                    **REPORT_DATA,
                    "fy": self.fy,
                    "period_start": "2026-05-01",
                    "period_end": "2026-01-01",
                },
            )
        self.assertTrue(
            AuditLog.objects.filter(
                action="ia.report.started", subject_id=report.id
            ).exists()
        )

    def test_submitting_freezes_the_evidence_and_later_data_never_changes_it(self):
        report = self.draft()
        report.findings = ""
        report.save()
        with self.assertRaises(BadRequest):
            rp.submit_report(self.ida, report.id)
        report.findings = "Findings."
        report.save()
        report = rp.submit_report(self.ida, report.id)
        snapshot = report.evidence_snapshot
        self.assertEqual(report.status, rp.SUBMITTED)
        self.assertEqual(report.snapshot_hash, rp.snapshot_hash(snapshot))
        self.assertEqual(snapshot["cohort"]["measured"], 3)
        self.assertEqual(snapshot["cohort"]["total"], 3, "Kenya's enrolment stays out")
        self.assertNotIn(self.kenya_school.id, json.dumps(snapshot))
        self.assertEqual(snapshot["mapping_versions"][0]["mapping_version"], 1)
        ProjectSchoolAssignment.objects.filter(school=self.schools[0]).update(
            follow_up_score=1.0, impact_classification="declined"
        )
        report.refresh_from_db()
        self.assertEqual(report.evidence_snapshot, snapshot)
        with self.assertRaises(BadRequest):
            rp.update_report(self.ida, report.id, {**REPORT_DATA, "fy": self.fy})
        with self.assertRaises(BadRequest):
            rp.add_recommendation(
                self.ida,
                report.id,
                {"text": "x", "owner_role": CD, "due_date": "2026-12-01"},
            )

    def test_the_period_reaches_the_frozen_cohort(self):
        start = (timezone.localdate() - timedelta(days=5)).isoformat()
        report = rp.submit_report(self.ida, self.draft(period_start=start).id)
        self.assertEqual(report.evidence_snapshot["cohort"]["total"], 0)

    def test_a_second_officer_reviews_and_the_author_never_does(self):
        report = self.submitted()
        with self.assertRaises(Forbidden):
            rp.review_report(self.ida, report.id, decision="approve")
        with self.assertRaises(Forbidden):
            rp.review_report(self.cd, report.id, decision="approve")
        with self.assertRaises(NotFoundError):
            rp.review_report(self.kofi, report.id, decision="approve")
        with self.assertRaises(BadRequest):
            rp.review_report(self.ivan, report.id, decision="return")
        report = rp.review_report(self.ivan, report.id, decision="approve")
        self.assertEqual((report.status, report.review_basis), (rp.REVIEWED, "peer_ia"))
        with self.assertRaises(Forbidden):
            rp.release_to_leadership(self.ida, report.id)

    def test_the_country_director_acknowledges_where_there_is_one_officer(self):
        User.objects.filter(pk=self.ivan.pk).update(is_active=False)
        report = self.submitted()
        report = rp.review_report(self.cd, report.id, decision="approve")
        self.assertEqual(report.review_basis, "cd_fallback")

    def test_a_correction_is_a_new_version_that_supersedes_the_old(self):
        report = self.submitted()
        rp.review_report(
            self.ivan, report.id, decision="return", note="Add the comparison."
        )
        with self.assertRaises(Forbidden):
            rp.start_correction(self.cd, report.id)
        revision = rp.start_correction(self.ida, report.id)
        self.assertEqual((revision.version, revision.supersedes_id), (2, report.id))
        self.assertEqual(revision.recommendations.count(), 1)
        with self.assertRaises(BadRequest):
            rp.start_correction(self.ida, report.id)
        rp.submit_report(self.ida, revision.id)
        report.refresh_from_db()
        self.assertEqual(report.status, rp.SUPERSEDED)

    def test_a_released_report_stands_until_its_correction_is_released(self):
        report = self.released()
        revision = rp.start_correction(self.ivan, report.id)
        rp.submit_report(self.ivan, revision.id)
        report.refresh_from_db()
        self.assertEqual(report.status, rp.RELEASED)
        rp.review_report(self.ida, revision.id, decision="approve")
        rp.release_to_leadership(self.ida, revision.id)
        report.refresh_from_db()
        self.assertEqual(report.status, rp.SUPERSEDED)

    def test_leadership_release_tells_the_director_who_answers_each_recommendation(
        self,
    ):
        report = self.released()
        notice = Notification.objects.get(
            recipient_id=self.cd.id, source_event_type=rp.EVENT_RELEASED
        )
        self.assertEqual(
            notice.target_route, f"/ia/impact-reports/{report.id}/#recommendations"
        )
        self.assertFalse(
            Notification.objects.filter(
                recipient_id=self.ke_cd.id, source_event_type=rp.EVENT_RELEASED
            ).exists()
        )
        recommendation = report.recommendations.get()
        with self.assertRaises(BadRequest):
            rp.respond_to_recommendation(self.cd, recommendation.id, status="rejected")
        with self.assertRaises(Forbidden):
            rp.respond_to_recommendation(
                self.ivan, recommendation.id, status="accepted"
            )
        with self.assertRaises(NotFoundError):
            rp.respond_to_recommendation(
                self.ke_cd, recommendation.id, status="accepted"
            )
        rp.respond_to_recommendation(
            self.cd, recommendation.id, status="deferred", response="Budget cycle."
        )
        recommendation.refresh_from_db()
        self.assertEqual(
            (recommendation.status, recommendation.responded_by_id),
            ("deferred", self.cd.id),
        )

    def test_school_briefs_go_to_each_account_owner_who_closes_them(self):
        report = self.released()
        with self.assertRaises(Forbidden):
            rp.release_school_briefs(self.ida, report.id, [self.schools[0].id])
        with self.assertRaises(BadRequest):
            rp.release_school_briefs(self.ivan, report.id, [self.kenya_school.id])
        result = rp.release_school_briefs(
            self.cd, report.id, [s.id for s in self.schools]
        )
        self.assertEqual(len(result["released"]), 2)
        self.assertEqual(result["skipped"][0][0], "School Uganda 2")
        release = ImpactReportRelease.objects.get(
            report=report, audience="school", school=self.schools[0]
        )
        payload = json.dumps(release.rendered_payload)
        self.assertNotIn("School Uganda 1", payload)
        self.assertNotIn("Ivy Owner", payload)
        action = TeamAction.objects.get(
            condition_key=rp.brief_condition_key(release.id)
        )
        self.assertEqual((action.recipient_id, action.state), (self.owner.id, "open"))
        with self.assertRaises(NotFoundError):
            rp.record_brief_shared(self.other_cceo, release.id, {})
        with self.assertRaises(Forbidden):
            rp.record_brief_shared(self.ida, release.id, {})
        with self.assertRaises(BadRequest):
            rp.record_brief_shared(
                self.owner,
                release.id,
                {
                    "shared_on": (timezone.localdate() + timedelta(days=2)).isoformat(),
                    "school_response": "x",
                },
            )
        rp.record_brief_shared(
            self.owner,
            release.id,
            {
                "shared_on": timezone.localdate().isoformat(),
                "school_response": "The board will act.",
            },
        )
        action.refresh_from_db()
        self.assertEqual(action.state, "resolved")
        self.assertIn("The board will act.", action.manual_resolution_reason)
        self.assertTrue(
            AuditLog.objects.filter(
                action="ia.report.school_brief_shared", subject_id=report.id
            ).exists()
        )

    def test_the_donor_version_needs_an_rvp_who_did_not_request_it(self):
        report = self.submitted()
        with self.assertRaises(BadRequest):
            rp.request_donor_release(self.cd, report.id)
        rp.review_report(self.ivan, report.id, decision="approve")
        rp.release_to_leadership(self.ivan, report.id)
        with self.assertRaises(Forbidden):
            rp.request_donor_release(self.ida, report.id)
        release = rp.request_donor_release(self.cd, report.id, "Annual donor round")
        self.assertEqual(release.status, "pending_approval")
        text = json.dumps(release.rendered_payload)
        self.assertNotIn("School Uganda", text)
        self.assertNotIn(self.schools[0].id, text)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.rvp.id, source_event_type=rp.EVENT_DONOR_REQUESTED
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                recipient_id=self.ke_rvp.id, source_event_type=rp.EVENT_DONOR_REQUESTED
            ).exists()
        )
        with self.assertRaises(BadRequest):
            rp.request_donor_release(self.ivan, report.id)
        with self.assertRaises(Forbidden):
            rp.decide_donor_release(self.cd, release.id, decision="approve")
        with self.assertRaises(NotFoundError):
            rp.decide_donor_release(self.ke_rvp, release.id, decision="approve")
        with self.assertRaises(BadRequest):
            rp.decide_donor_release(self.rvp, release.id, decision="decline")
        release = rp.decide_donor_release(self.rvp, release.id, decision="approve")
        self.assertEqual(
            (release.status, release.approved_by_id), ("released", self.rvp.id)
        )

    def test_the_requester_cannot_approve_under_another_role(self):
        both = _user("dual-lead@edify.test", CD, roles=[CD, RVP])
        User.objects.filter(pk=self.cd.pk).update(is_active=False)
        report = self.released()
        release = rp.request_donor_release(both, report.id)
        both.active_role = RVP
        with self.assertRaises(Forbidden):
            rp.decide_donor_release(both, release.id, decision="approve")

    def test_withdrawal_and_the_audit_trail(self):
        report = self.submitted()
        rp.withdraw_report(self.ida, report.id)
        report.refresh_from_db()
        self.assertEqual(report.status, rp.WITHDRAWN)
        actions = set(
            AuditLog.objects.filter(
                subject_kind="ImpactReport", subject_id=report.id
            ).values_list("action", flat=True)
        )
        self.assertTrue(
            {
                "ia.report.started",
                "ia.report.recommendation_added",
                "ia.report.submitted",
                "ia.report.withdrawn",
            }
            <= actions
        )
        self.assertEqual(rp.history(report)[0]["label"], "Withdrawn")


# ── Reach and pages ──────────────────────────────────────────────────────────


class ReportPageTests(ReportFixture):
    def test_the_register_renders_for_each_reader_and_refuses_others(self):
        draft = self.draft()
        released = self.released()
        for user in (self.ida, self.cd, self.admin):
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get("/ia/impact-reports/")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-ia-impact-reports")
        self.client.force_login(self.rvp)
        response = self.client.get("/ia/impact-reports/")
        self.assertContains(response, f"/ia/impact-reports/{released.id}/")
        self.assertNotContains(response, f"/ia/impact-reports/{draft.id}/")
        self.client.force_login(self.kofi)
        self.assertNotContains(self.client.get("/ia/impact-reports/"), released.id)
        self.assertEqual(
            self.client.get(f"/ia/impact-reports/{released.id}/").status_code, 404
        )
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/ia/impact-reports/").status_code, 302)

    def test_a_report_is_drafted_submitted_and_reviewed_from_its_page(self):
        self.client.force_login(self.ida)
        drawer = self.client.get("/ia/impact-reports/new")
        self.assertContains(drawer, 'name="methodology"')
        response = self.client.post(
            "/ia/impact-reports/create", {**REPORT_DATA, "fy": self.fy}
        )
        report = ImpactReport.objects.get(title=REPORT_DATA["title"])
        self.assertRedirects(
            response, f"/ia/impact-reports/{report.id}/", fetch_redirect_response=False
        )
        page = self.client.get(f"/ia/impact-reports/{report.id}/")
        self.assertContains(page, "data-ia-report-submit")
        self.client.post(
            f"/ia/impact-reports/{report.id}/recommendations/create",
            {"text": "Keep going", "owner_role": CD, "due_date": "2030-01-01"},
        )
        self.client.post(f"/ia/impact-reports/{report.id}/submit")
        report.refresh_from_db()
        self.assertEqual(report.status, rp.SUBMITTED)
        refused = self.client.get(f"/ia/impact-reports/{report.id}/review")
        self.assertContains(refused, "You wrote this")
        self.client.force_login(self.ivan)
        self.assertContains(
            self.client.get(f"/ia/impact-reports/{report.id}/review"), 'name="decision"'
        )
        response = self.client.post(
            f"/ia/impact-reports/{report.id}/review/save",
            {"decision": "return", "note": ""},
            follow=True,
        )
        self.assertContains(response, "Say what the author needs to change.")

    def test_the_rvp_reads_aggregates_never_the_annex(self):
        report = self.released()
        release = rp.request_donor_release(self.cd, report.id)
        self.client.force_login(self.rvp)
        page = self.client.get(f"/ia/impact-reports/{report.id}/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "School Uganda 0")
        self.assertNotContains(page, "data-ia-report-annex")
        self.assertEqual(
            self.client.get(f"/ia/impact-reports/{report.id}/annex.csv").status_code,
            404,
        )
        drawer = self.client.get(
            f"/ia/impact-reports/{report.id}/releases/{release.id}/"
        )
        self.assertContains(drawer, "Approve and release to donors")
        self.client.post(
            f"/ia/impact-reports/{report.id}/releases/{release.id}/decide",
            {"decision": "approve"},
        )
        download = self.client.get(
            f"/ia/impact-reports/{report.id}/releases/{release.id}/download"
        )
        self.assertEqual(download.status_code, 200)
        self.assertNotIn("School Uganda", download.content.decode())
        self.assertTrue(
            AuditLog.objects.filter(
                action="ia.report.release_downloaded", subject_id=report.id
            ).exists()
        )

    def test_the_annex_is_frozen_signed_and_audited(self):
        report = self.submitted()
        self.client.force_login(self.cd)
        response = self.client.get(f"/ia/impact-reports/{report.id}/annex.csv")
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        header = dict(r[:2] for r in rows[:12] if len(r) >= 2)
        self.assertEqual(header["Snapshot sha256"], report.snapshot_hash)
        self.assertEqual(header["Generated by role"], CD)
        self.assertIn(self.schools[0].id, response.content.decode())
        self.assertTrue(
            AuditLog.objects.filter(
                action="ia.report.annex_downloaded", subject_id=report.id
            ).exists()
        )

    def test_the_owner_opens_and_records_the_school_brief(self):
        report = self.released()
        rp.release_school_briefs(self.ivan, report.id, [self.schools[0].id])
        release = ImpactReportRelease.objects.get(report=report, audience="school")
        self.client.force_login(self.other_cceo)
        self.assertEqual(
            self.client.get(f"/impact-briefs/{release.id}/").status_code, 404
        )
        self.client.force_login(self.owner)
        page = self.client.get(f"/impact-briefs/{release.id}/")
        self.assertContains(page, "data-ia-brief-record")
        self.assertContains(page, "School Uganda 0")
        self.client.post(
            f"/impact-briefs/{release.id}/shared",
            {
                "shared_on": timezone.localdate().isoformat(),
                "school_response": "Thank you.",
            },
        )
        page = self.client.get(f"/impact-briefs/{release.id}/")
        self.assertContains(page, "data-ia-brief-shared")
        self.assertNotContains(page, "data-ia-brief-record")

    def test_the_live_annex_applies_its_period_and_names_who_generated_it(self):
        self.client.force_login(self.ida)
        response = self.client.post(
            "/ia/impact-report/download",
            {
                "fy": self.fy,
                "period_start": (timezone.localdate() - timedelta(days=5)).isoformat(),
            },
        )
        content = response.content.decode()
        self.assertNotIn(self.schools[0].id, content)
        self.assertIn("generated_by_role,ImpactAssessment", content)
        self.assertIn("rows_sha256", content)
        response = self.client.post("/ia/impact-report/download", {"fy": self.fy})
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        data = [r for r in rows if r and r[0] == "CC-SEL"]
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0][8], "2.0", "numbers stay numbers")
        self.assertEqual(
            self.client.post(
                "/ia/impact-report/download", {"period_start": "not-a-date"}
            ).status_code,
            400,
        )
        self.assertTrue(
            AuditLog.objects.filter(action="ia.evidence_annex.downloaded").exists()
        )

    def test_the_dashboard_reports_view_carries_the_lifecycle(self):
        self.released()
        self.client.force_login(self.ida)
        response = self.client.get("/ia/dashboard/", {"view": "reports"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-ia-reports-view")
        self.assertContains(response, "Latest impact reports")
        self.assertEqual(
            response.context["ia_view_template"], "partials/ia/reports_view.html"
        )


class NotificationAndTodoTests(ReportFixture):
    def test_the_notification_routes_open_the_report(self):
        resolve = NotificationLinkResolver.resolve
        self.assertEqual(
            resolve(rp.EVENT_REVIEW_REQUESTED, "ImpactReport", "r1", IA),
            ("/ia/impact-reports/r1/", "Review Report"),
        )
        self.assertEqual(
            resolve(rp.EVENT_DONOR_REQUESTED, "ImpactReport", "r1", RVP)[0],
            "/ia/impact-reports/r1/#releases",
        )
        self.assertEqual(
            resolve(rp.EVENT_SCHOOL_BRIEF, "ImpactReportRelease", "rel1", CCEO)[0],
            "/impact-briefs/rel1/",
        )
        self.assertEqual(
            resolve(rp.EVENT_RELEASED, "ImpactReport", "r1", CCEO)[0], "/dashboard"
        )

    def test_each_person_gets_their_step(self):
        today = timezone.localdate()
        report = self.submitted()
        self.assertEqual(
            [r["id"] for r in report_todos(self.ivan, IA, today)], ["ia-reports-review"]
        )
        self.assertEqual(report_todos(self.ida, IA, today), [])
        self.assertEqual(
            report_todos(self.cd, CD, today), [], "a second officer exists"
        )
        rp.review_report(self.ivan, report.id, decision="approve")
        self.assertEqual(
            [r["id"] for r in report_todos(self.ivan, IA, today)],
            ["ia-reports-release"],
        )
        rp.release_to_leadership(self.ivan, report.id)
        self.assertEqual(
            [r["id"] for r in report_todos(self.cd, CD, today)],
            ["ia-report-recommendations-respond"],
        )
        rp.request_donor_release(self.cd, report.id)
        self.assertEqual(
            [r["id"] for r in report_todos(self.rvp, RVP, today)],
            ["ia-report-donor-approve"],
        )
        self.assertEqual(report_todos(self.ke_rvp, RVP, today), [])

    def test_the_todo_builder_costs_a_fixed_number_of_queries(self):
        today = timezone.localdate()
        self.released()

        def measure(user, role):
            with CaptureQueriesContext(connection) as ctx:
                report_todos(user, role, today)
            return len(ctx.captured_queries)

        small = {
            r: measure(u, r)
            for u, r in ((self.cd, CD), (self.ivan, IA), (self.rvp, RVP))
        }
        for _ in range(4):
            self.released()
        large = {
            r: measure(u, r)
            for u, r in ((self.cd, CD), (self.ivan, IA), (self.rvp, RVP))
        }
        for role in small:
            with self.subTest(role=role):
                self.assertLessEqual(large[role], small[role])
                self.assertLessEqual(large[role], 12)


class CountryDirectorAndQueryBudgetTests(ReportFixture):
    def test_the_directors_section_and_export_read_the_released_snapshot(self):
        from apps.analytics.cd_export_service import country_export

        slug, header, rows = country_export(self.cd, "impact")
        self.assertEqual(slug, "impact-findings")
        self.assertIn("None released", rows[0][2])
        report = self.released()
        section = rp.cd_impact_findings(self.cd)
        self.assertEqual(section["latest"]["report_id"], report.id)
        self.assertEqual(section["awaiting_response"], 1)
        self.assertEqual(len(section["tiles"]), 4)
        ProjectSchoolAssignment.objects.update(impact_classification="declined")
        _slug, _header, rows = country_export(self.cd, "impact")
        values = {r[1]: r[2] for r in rows if r[0] == "Project cohort"}
        self.assertEqual(values["improved"], 3)
        self.assertEqual(rp.cd_impact_findings(self.ke_cd)["latest"], None)

    def test_the_operations_view_shows_impact_findings_and_the_fixed_link(self):
        self.released()
        self.client.force_login(self.cd)
        response = self.client.get("/dashboard?view=operations")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-cd-impact-findings")
        self.assertContains(response, 'href="/ia/analytics/"')
        self.assertContains(response, "Recommendations Awaiting Your Response")

    def test_the_register_and_the_section_cost_a_fixed_number_of_queries(self):
        self.released()
        self.client.force_login(self.ida)
        self.client.get("/ia/impact-reports/")

        def page():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(
                    self.client.get("/ia/impact-reports/").status_code, 200
                )
            return len(ctx.captured_queries)

        def section():
            with CaptureQueriesContext(connection) as ctx:
                rp.cd_impact_findings(self.cd)
            return len(ctx.captured_queries)

        small_page, small_section = page(), section()
        for _ in range(5):
            self.released()
        large_page, large_section = page(), section()
        self.assertLessEqual(large_page, small_page + 1, (small_page, large_page))
        self.assertLessEqual(large_section, small_section)
        self.assertLessEqual(large_section, 8)

    def test_impact_assessment_sees_its_own_countrys_flags_only(self):
        from apps.flags.models import CdFlag

        pl = _user("pat-pl@edify.test", "Program Lead")
        CdFlag.objects.create(
            raised_by_user_id=self.cd.id,
            raised_by_name="Carol",
            assigned_to_user_id=pl.id,
            category="general",
            note="Uganda flag note",
        )
        CdFlag.objects.create(
            raised_by_user_id=self.ke_cd.id,
            raised_by_name="Ken",
            assigned_to_user_id=pl.id,
            category="general",
            note="Kenya flag note",
        )
        self.client.force_login(self.ida)
        response = self.client.get("/quality-checks")
        self.assertContains(response, "Uganda flag note")
        self.assertNotContains(response, "Kenya flag note")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/quality-checks"), "Kenya flag note")

    def test_recommendations_count_for_the_register_tiles(self):
        report = self.released()
        counts = rp.counts(self.ida, self.fy)
        self.assertEqual(
            (counts["released_this_year"], counts["awaiting_response"]), (1, 1)
        )
        ImpactReportRecommendation.objects.filter(report=report).update(
            due_date=timezone.localdate() - timedelta(days=1)
        )
        self.assertEqual(rp.counts(self.ida, self.fy)["overdue"], 1)
