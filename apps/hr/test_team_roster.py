"""My Team — the Programme Lead's roster (Programme Lead alignment, 2026-09-13).

`apps.hr.team_roster` is the one definition of a Programme Lead's team and the
builder behind /my-team. These tests hold the definition (who is on the team),
each roster signal against the surface whose rule it reuses, the manager-owned
exceptions and their PL-reachable links, and the query shape: the roster reads
each source once for the whole team, so five officers cost what two do.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    TemporaryCoverageAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.hr import team_roster
from apps.hr.models import ExtraAssignment, PerformanceReview
from apps.schools.models import School

FY = get_operational_fy()
LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pl-team-roster",
    }
}


def _person(key, role, *, name=None, country="Uganda", state="active"):
    user = User.objects.create(
        id=f"tr-{key}"[:30],
        email=f"tr-{key}@edify.test",
        name=name or f"Roster {key}",
        roles=[role],
        active_role=role,
        is_active=True,
    )
    profile = StaffProfile.objects.create(
        id=f"trsp-{key}"[:30],
        user=user,
        title=role,
        country=country,
        onboarding_state=state,
    )
    return user, profile


class RosterFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Roster Region")
        cls.district = District.objects.create(
            name="Roster District", region=cls.region
        )
        cls.pl, cls.pl_sp = _person("pl", "Program Lead", name="Pat Lead")
        cls.officers = []
        for i in range(5):
            user, sp = _person(f"cceo{i}", "CCEO", name=f"Officer {i}")
            StaffSupervisorAssignment.objects.create(
                supervisor=cls.pl_sp, supervisee=sp
            )
            school = School.objects.create(
                school_id=f"TR-{i}",
                name=f"Roster School {i}",
                region=cls.region,
                district=cls.district,
            )
            StaffSchoolAssignment.objects.create(staff=sp, school_id=school.id)
            cls.officers.append((user, sp, school))

    def _officer(self, i):
        return self.officers[i]


class TeamDefinitionTests(RosterFixture):
    def test_team_is_the_leads_active_cceo_supervisees(self):
        # A departed officer and a supervised non-CCEO are not the team.
        gone_user, gone = _person("gone", "CCEO")
        StaffSupervisorAssignment.objects.create(supervisor=self.pl_sp, supervisee=gone)
        gone_user.is_active = False
        gone_user.save(update_fields=["is_active"])
        _, coordinator = _person("pc", "ProjectCoordinator")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=coordinator
        )
        ids = team_roster.team_member_ids(self.pl)
        self.assertEqual(set(ids), {sp.id for _, sp, _ in self.officers})
        self.assertNotIn(gone.id, ids)
        self.assertNotIn(coordinator.id, ids)
        self.assertNotIn(self.pl_sp.id, ids)

    def test_cover_brings_the_absent_leads_officers(self):
        away, away_sp = _person("away", "Program Lead")
        _, theirs = _person("theirs", "CCEO")
        StaffSupervisorAssignment.objects.create(supervisor=away_sp, supervisee=theirs)
        now = timezone.now()
        leave = Leave.objects.create(
            staff=away_sp,
            type="personal_time_off",
            start_date=(now.date() - timedelta(days=1)).isoformat(),
            end_date=(now.date() + timedelta(days=3)).isoformat(),
            days=4,
            days_charged=4,
            status="approved",
        )
        TemporaryCoverageAssignment.objects.create(
            leave_request=leave,
            original_staff=away_sp,
            covering_staff=self.pl_sp,
            start_datetime=now - timedelta(days=1),
            end_datetime=now + timedelta(days=3),
            status="active",
        )
        self.assertTrue(team_roster.is_team_member(self.pl, theirs.id))
        other, _ = _person("otherpl", "Program Lead")
        self.assertFalse(team_roster.is_team_member(other, theirs.id))


class RosterSignalTests(RosterFixture):
    def _roster(self, **kwargs):
        return team_roster.build_team_roster(self.pl, FY, **kwargs)

    def _row(self, roster, staff_id):
        return next(r for r in roster["rows"] if r["staff_id"] == staff_id)

    def test_one_row_per_officer_with_a_profile_link_back_to_my_team(self):
        roster = self._roster()
        self.assertEqual(len(roster["rows"]), 5)
        user, sp, _ = self._officer(0)
        row = self._row(roster, sp.id)
        self.assertEqual(row["profile_url"], f"/staff/{user.id}?from=/my-team")
        self.assertEqual(row["district"], "Roster District")
        self.assertEqual(roster["summary"]["team_size"], 5)

    def test_delivery_counts_both_id_forms_and_waiting_completions(self):
        user, sp, school = self._officer(0)
        for status, owner in (
            ("ia_verified", sp.id),
            ("closed", user.id),  # the older User id form
            ("scheduled", sp.id),
            ("submitted_to_pl", sp.id),
        ):
            Activity.objects.create(
                school=school,
                activity_type="school_visit",
                delivery_type="staff",
                status=status,
                responsible_staff_id=owner,
                fy=FY,
                planned_date=date.today(),
            )
        # Partner work the officer monitors waits on the lead too.
        Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="partner",
            status="submitted_to_pl",
            responsible_staff_id=None,
            monitored_by_staff_id=sp.id,
            fy=FY,
            planned_date=date.today(),
        )
        row = self._row(self._roster(), sp.id)
        self.assertEqual(row["delivery"]["planned"], 5)
        self.assertEqual(row["delivery"]["verified"], 2)
        self.assertEqual(row["waiting"]["completions"], 2)
        roster = self._roster()
        waiting = [
            i for i in roster["needs_action"] if i["kind"] == "completions_waiting"
        ]
        self.assertEqual([i["url"] for i in waiting], ["/pl/review-queue"])

    def test_ssa_coverage_counts_confirmed_records_this_year(self):
        from apps.ssa.models import SsaRecord

        _, sp, school = self._officer(1)
        SsaRecord.objects.create(
            school=school,
            date_of_ssa=timezone.now(),
            fy=FY,
            quarter="Q1",
            average_score=6,
            verification_status="confirmed",
        )
        row = self._row(self._roster(), sp.id)
        self.assertEqual((row["ssa"]["assessed"], row["ssa"]["portfolio"]), (1, 1))
        other = self._row(self._roster(), self._officer(2)[1].id)
        self.assertEqual(other["ssa"]["assessed"], 0)

    def test_leave_now_next_and_pending(self):
        today = date.today()
        _, away, _ = self._officer(0)
        _, later, _ = self._officer(1)
        Leave.objects.create(
            staff=away,
            type="personal_time_off",
            start_date=(today - timedelta(days=1)).isoformat(),
            end_date=(today + timedelta(days=2)).isoformat(),
            days=3,
            days_charged=3,
            status="approved",
        )
        Leave.objects.create(
            staff=later,
            type="personal_time_off",
            start_date=(today + timedelta(days=9)).isoformat(),
            end_date=(today + timedelta(days=10)).isoformat(),
            days=2,
            days_charged=2,
            status="approved",
        )
        Leave.objects.create(
            staff=later,
            type="personal_time_off",
            start_date=(today + timedelta(days=30)).isoformat(),
            end_date=(today + timedelta(days=31)).isoformat(),
            days=2,
            days_charged=2,
            status="pending",
        )
        roster = self._roster()
        self.assertTrue(self._row(roster, away.id)["leave"]["away_now"])
        self.assertIn("Away from", self._row(roster, later.id)["leave"]["text"])
        self.assertEqual(self._row(roster, later.id)["waiting"]["leave"], 1)
        self.assertEqual(roster["summary"]["on_leave_now"], 1)
        # Approved leave starting within a fortnight with nobody covering.
        uncovered = [
            i for i in roster["needs_action"] if i["kind"] == "leave_without_coverage"
        ]
        self.assertEqual({i["url"] for i in uncovered}, {"/leave/coverage"})

    def test_overdue_leave_decision_links_to_the_request(self):
        _, sp, _ = self._officer(3)
        leave = Leave.objects.create(
            staff=sp,
            type="personal_time_off",
            start_date="2027-01-10",
            end_date="2027-01-12",
            days=3,
            days_charged=3,
            status="pending",
        )
        Leave.objects.filter(id=leave.id).update(
            created_at=timezone.now() - timedelta(days=5)
        )
        items = self._roster()["needs_action"]
        overdue = next(i for i in items if i["kind"] == "leave_decision_overdue")
        self.assertEqual(overdue["url"], f"/leave/approvals?id={leave.id}")
        self.assertEqual(overdue["person"], "Officer 3")

    def test_review_stage_missing_agreement_and_overdue_review(self):
        _, drafting, _ = self._officer(0)
        _, waiting, _ = self._officer(1)
        PerformanceReview.objects.create(
            staff=drafting,
            period=f"FY{FY}",
            fy=FY,
            review_type="annual_priorities",
            stage="priorities_draft",
            due_date=date.today() + timedelta(days=30),
        )
        PerformanceReview.objects.create(
            staff=waiting,
            period=f"FY{FY}",
            fy=FY,
            review_type="annual_priorities",
            stage="priorities_manager_review",
            due_date=date.today() - timedelta(days=3),
        )
        roster = self._roster()
        self.assertEqual(
            self._row(roster, drafting.id)["review"]["stage"], "priorities_draft"
        )
        self.assertIn("waiting on you", self._row(roster, waiting.id)["review"]["text"])
        missing = {
            i["url"] for i in roster["needs_action"] if i["kind"] == "no_agreement"
        }
        self.assertEqual(
            missing,
            {
                f"/performance-conversation?staff={sp.id}"
                for _, sp, _ in self.officers[2:]
            },
        )
        overdue = next(
            i for i in roster["needs_action"] if i["kind"] == "review_overdue"
        )
        self.assertEqual(
            overdue["url"], f"/performance-conversation?staff={waiting.id}"
        )

    def test_pd_escalations_extra_work_and_policies(self):
        from apps.documents.models import (
            AcknowledgementState,
            DocumentAcknowledgement,
            DocumentAsset,
            DocumentStatus,
            DocumentType,
            DocumentVersion,
        )
        from apps.flags import escalation_service
        from apps.professional_development.models import (
            PDStatus,
            ProfessionalDevelopmentRequest,
        )

        user, sp, _ = self._officer(0)
        ProfessionalDevelopmentRequest.objects.create(
            fy=FY,
            staff_id=sp.id,
            staff_name=user.name,
            country="Uganda",
            course_name="Coaching Skills",
            course_category="Leadership Development",
            course_type="online",
            institution="Coursera",
            start_date=date.today() + timedelta(days=30),
            end_date=date.today() + timedelta(days=60),
            funding_type="self_funded",
            created_by=user.id,
            status=PDStatus.SUBMITTED_TO_SUPERVISOR,
        )
        escalation_service.raise_escalation(
            {"subject": "Transport for cluster day", "detail": "No vehicle."}, user
        )
        ExtraAssignment.objects.create(
            fy=FY,
            title="District pack",
            instruction="Compile it.",
            category="operational_support",
            assigner_id=self.pl.id,
            assigner_role="Program Lead",
            assignee_id=user.id,
            assignee_role="CCEO",
            reviewer_id=self.pl.id,
            due_date=date.today(),
            status="submitted",
        )
        document = DocumentAsset.objects.create(
            title="Safeguarding Policy",
            slug="safeguarding-policy",
            document_type=DocumentType.POLICY,
            status=DocumentStatus.PUBLISHED,
            acknowledgement_required=True,
        )
        version = DocumentVersion.objects.create(
            document=document,
            version_number=1,
            uri="documents/safe.pdf",
            original_filename="safe.pdf",
        )
        DocumentAcknowledgement.objects.create(
            document=document,
            version=version,
            user_id=user.id,
            state=AcknowledgementState.PENDING,
            due_date=date.today() - timedelta(days=2),
        )
        roster = self._roster()
        row = self._row(roster, sp.id)
        self.assertEqual(row["waiting"]["development"], 1)
        self.assertEqual(row["waiting"]["escalations"], 1)
        self.assertEqual(row["waiting"]["extra_work"], 1)
        self.assertEqual(row["waiting"]["total"], 3)
        self.assertEqual(row["policies_overdue"], 1)
        kinds = {i["kind"]: i for i in roster["needs_action"]}
        self.assertEqual(kinds["escalation_to_decide"]["url"], "/escalations")
        self.assertIn(user.name, kinds["escalation_to_decide"]["title"])
        self.assertEqual(kinds["extra_work_to_verify"]["url"], "/extra-work")
        self.assertTrue(
            kinds["pd_supervisor_review"]["url"].startswith(
                "/my-professional-development/request?id="
            )
        )
        # Another lead's inbox never counts this officer's escalation.
        other, _ = _person("rival", "Program Lead")
        self.assertEqual(team_roster.build_team_roster(other, FY)["rows"], [])

    def test_targets_and_risk_follow_team_targets_bands(self):
        _, sp, _ = self._officer(0)
        # With no agreement nothing is assigned: no target, no risk.
        row = self._row(self._roster(), sp.id)
        self.assertEqual(row["target"]["status"], "Not Assigned")
        self.assertEqual(row["risk"]["text"], "—")
        bands = {
            s.id: {
                "fy_status": "On Track",
                "fy_tone": "success",
                "fy_text": "61% · On Track",
                "month_status": "Critical" if s.id == sp.id else "On Track",
            }
            for _, s, _ in self.officers
        }
        with patch.object(team_roster, "_target_bands", return_value=bands):
            roster = self._roster()
        self.assertEqual(self._row(roster, sp.id)["risk"]["text"], "Critical")
        self.assertEqual(roster["summary"]["at_risk"], 1)
        self.assertEqual(roster["summary"]["on_track"], 5)

    def test_a_lead_with_no_team_gets_an_empty_roster(self):
        loner, _ = _person("loner", "Program Lead")
        roster = team_roster.build_team_roster(loner, FY)
        self.assertEqual(roster["rows"], [])
        self.assertEqual(roster["needs_action"], [])
        self.assertEqual(roster["summary"]["team_size"], 0)


@override_settings(CACHES=LOCMEM)
class RosterQueryBudgetTests(RosterFixture):
    """The roster reads each source once for the team, never once per officer."""

    def _seed(self):
        today = date.today()
        for user, sp, school in self.officers:
            Activity.objects.create(
                school=school,
                activity_type="school_visit",
                delivery_type="staff",
                status="completed",
                responsible_staff_id=sp.id,
                fy=FY,
                planned_date=today,
            )
            Leave.objects.create(
                staff=sp,
                type="personal_time_off",
                start_date=(today + timedelta(days=40)).isoformat(),
                end_date=(today + timedelta(days=41)).isoformat(),
                days=2,
                days_charged=2,
                status="approved",
            )
            PerformanceReview.objects.create(
                staff=sp,
                period=f"FY{FY}",
                fy=FY,
                review_type="annual_priorities",
                stage="priorities_draft",
                due_date=today + timedelta(days=30),
            )

    def _cost(self, team_size):
        keep = {sp.id for _, sp, _ in self.officers[:team_size]}
        StaffSupervisorAssignment.objects.filter(supervisor=self.pl_sp).exclude(
            supervisee_id__in=keep
        ).delete()
        team_roster.build_team_roster(self.pl, FY)  # settle the ledger rebuild
        with CaptureQueriesContext(connection) as ctx:
            roster = team_roster.build_team_roster(self.pl, FY)
        self.assertEqual(len(roster["rows"]), team_size)
        return len(ctx)

    def test_five_officers_cost_what_two_do(self):
        self._seed()
        five = self._cost(5)
        two = self._cost(2)
        self.assertEqual(
            five,
            two,
            f"the roster grew from {two} to {five} queries between two and five "
            "officers: a source is being read per officer",
        )

    def test_the_guard_is_real_without_the_leave_priming(self):
        """Guards the guard: Team Targets' pace arithmetic reads each officer's
        approved leave. Without the roster priming that memo the query count
        grows with the team, so the equality above would catch a drifted
        memo key rather than pass by accident."""
        self._seed()
        with patch.object(team_roster, "_prime_leave_days", lambda rows: None):
            five = self._cost(5)
            two = self._cost(2)
        self.assertGreater(five, two)

    def test_the_team_targets_path_runs_for_every_officer(self):
        # _target_bands logs and returns {} on failure; an empty result would
        # read as "no targets" and hide a broken path.
        members = team_roster.team_members(self.pl)
        bands = team_roster._target_bands(members, FY, date.today(), {})
        self.assertEqual(set(bands), {sp.id for _, sp, _ in self.officers})
        self.assertTrue(
            all(b["fy_text"] == "No targets agreed" for b in bands.values())
        )

    def test_the_roster_stays_under_its_ceiling(self):
        self._seed()
        # Measured at 30 against this fixture (2026-09-13); a ceiling, never a
        # target.
        self.assertLessEqual(self._cost(5), 40)
