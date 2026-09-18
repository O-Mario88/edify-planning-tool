"""A course follows the same reporting line everything else already does.

Owner, 2026-09-18: "PLs, IA, Accountant Report to CD. So CD approves
everything for those roles (leaves, professional development.......literally
everything). PLs approves everything for CCEO."

That chart is written down: apps.hr.review_authority.REVIEWER_ROLE_FOR, the one
place the platform answers "who reviews whom", created after three defects that
all came from not having one. Leave reads it. Performance review reads it.
Professional Development did not — it took whoever held a
StaffSupervisorAssignment row, which differs from the chart in three ways that
each cost something:

* the model carries oversight rows beside reporting lines ("IA/RVP rows are
  overlapping management oversight"), and the earliest row won, so a Programme
  Lead's course could be decided by the assurance reviewer;
* nothing checked whether that person still worked here;
* with no row at all it recorded that nobody supervises this person and posted
  the request straight to HR, so the same employee's leave reached their
  Director and their course quietly did not.

What stays is the case the auto-skip was written for (§13): above the Director
the chart runs out, and an RVP with no configured executive supervisor still
clears stage 1 rather than stalling. That is asserted here too, because a
fallback is only correct if it knows where to stop.
"""

from __future__ import annotations

from apps.accounts.models import (
    StaffOnboardingState,
    StaffProfile,
    StaffSupervisorAssignment,
)
from apps.core.rbac import EdifyRole

from apps.professional_development.approval_service import PDApprovalRoutingService
from apps.professional_development.hr_dashboard_service import HRPDDashboardService
from apps.professional_development.models import PDStatus
from apps.professional_development.services import staff_display_info
from apps.professional_development.tests import PDTestBase, User


class ReportingLineTest(PDTestBase):
    def setUp(self):
        super().setUp()
        self.ia, self.ia_sp = self._staff(
            "ia@pd.org", "Ivy Assessment", EdifyRole.IMPACT_ASSESSMENT.value
        )

    def _submitted(self, user):
        req = self._draft(user)
        PDApprovalRoutingService.submit(req, user)
        req.refresh_from_db()
        return req

    # ── The three roles the owner named ──────────────────────────────────
    def test_a_programme_lead_reaches_the_country_director(self):
        req = self._submitted(self.pl)

        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_SUPERVISOR)
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.cd))

    def test_impact_assessment_reaches_the_country_director(self):
        req = self._submitted(self.ia)

        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_SUPERVISOR)
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.cd))

    def test_the_accountant_reaches_the_country_director(self):
        """The stage this fixture's comment used to call unreachable."""
        req = self._submitted(self.accountant)

        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_SUPERVISOR)
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.cd))
        PDApprovalRoutingService.supervisor_approve(req.id, self.cd)
        req.refresh_from_db()
        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_HR)

    def test_a_cceo_goes_to_their_own_programme_lead(self):
        """The other half of the sentence, and the half already configured:
        a CCEO belongs to one Lead's roster, so the row decides it."""
        req = self._submitted(self.cceo)

        self.assertEqual(req.status, PDStatus.SUBMITTED_TO_SUPERVISOR)
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.pl))
        self.assertFalse(PDApprovalRoutingService.can_review(req, self.cd))

    # ── The chart, not merely a row ──────────────────────────────────────
    def test_an_oversight_row_does_not_become_the_reviewer(self):
        """StaffSupervisorAssignment carries both kinds of link — its own
        docstring says so — and the earliest row used to win, so a Lead's
        course could land with assurance rather than with their Director."""
        StaffSupervisorAssignment.objects.create(
            supervisee=self.pl_sp, supervisor=self.ia_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.pl_sp, supervisor=self.cd_sp
        )

        self.assertEqual(
            PDApprovalRoutingService.supervisor_for(self.pl_sp), self.cd_sp
        )
        req = self._submitted(self.pl)
        self.assertTrue(PDApprovalRoutingService.can_review(req, self.cd))
        self.assertFalse(PDApprovalRoutingService.can_review(req, self.ia))

    def test_a_configured_row_still_decides_which_director(self):
        """The chart names the role; the row names the person. A second
        Director in the country does not take over a Lead already reporting
        to one."""
        other, other_sp = self._staff(
            "cd2@pd.org", "Ada Director", EdifyRole.COUNTRY_DIRECTOR.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.pl_sp, supervisor=other_sp
        )

        self.assertEqual(PDApprovalRoutingService.supervisor_for(self.pl_sp), other_sp)
        req = self._submitted(self.pl)
        self.assertTrue(PDApprovalRoutingService.can_review(req, other))
        self.assertFalse(PDApprovalRoutingService.can_review(req, self.cd))

    def test_a_manager_who_has_left_does_not_hold_the_queue(self):
        """An exited manager keeping an approval is how a request stops moving
        without anybody being told it has stopped."""
        gone, gone_sp = self._staff(
            "cd-gone@pd.org", "Gus Gone", EdifyRole.COUNTRY_DIRECTOR.value
        )
        gone_sp.onboarding_state = StaffOnboardingState.EXITED
        gone_sp.save(update_fields=["onboarding_state"])
        StaffSupervisorAssignment.objects.create(
            supervisee=self.ia_sp, supervisor=gone_sp
        )

        # Falls through to the serving Director rather than stalling on Gus.
        self.assertEqual(
            PDApprovalRoutingService.supervisor_for(self.ia_sp), self.cd_sp
        )
        self.assertFalse(
            PDApprovalRoutingService.can_review(self._submitted(self.ia), gone)
        )

    # ── Where the chart stops ────────────────────────────────────────────
    def test_a_cceo_without_a_lead_still_waits_for_the_roster(self):
        """Below the Director the line is a team, not a role: resolving it by
        country would hand the approval to whichever Lead sorted first."""
        _, orphan_sp = self._staff(
            "orphan-cceo@pd.org", "Ora Cceo", EdifyRole.CCEO.value
        )

        self.assertIsNone(PDApprovalRoutingService.supervisor_for(orphan_sp))
        self.assertEqual(
            self._submitted(orphan_sp.user).status, PDStatus.SUBMITTED_TO_HR
        )

    def test_an_rvp_still_clears_stage_one(self):
        """§13's auto-skip, which this change must not swallow."""
        self.assertIsNone(PDApprovalRoutingService.supervisor_for(self.rvp_sp))
        self.assertEqual(self._submitted(self.rvp).status, PDStatus.SUBMITTED_TO_HR)

    def test_a_director_is_not_their_own_supervisor(self):
        self.assertIsNone(PDApprovalRoutingService.supervisor_for(self.cd_sp))

    def test_a_director_in_another_country_is_not_the_supervisor(self):
        """The country guard leave applies: a CD never acquires authority over
        a country they do not run."""
        abroad = User.objects.create_user(
            email="pl-ke@pd.org",
            name="Kip Lead",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            password="x",
            is_active=True,
        )
        abroad_sp = StaffProfile.objects.create(
            user=abroad, title="Program Lead", country="Kenya"
        )

        self.assertIsNone(PDApprovalRoutingService.supervisor_for(abroad_sp))

    # ── The list you see is the list you may decide ──────────────────────
    def test_the_director_sees_the_requests_the_chart_routed_to_them(self):
        """The hole this change would otherwise have opened.

        The supervisor's queue was built from configured rows alone, so a
        request the chart routes to the Director would have waited at the
        supervisor stage in a list nobody renders — worse than the auto-skip
        it replaces, which at least reached HR.
        """
        mine = self._submitted(self.accountant)
        theirs = self._submitted(self.cceo)  # CCEO → PL, by a configured row

        directors = [
            row["request_id"] for row in HRPDDashboardService.supervisor_queue(self.cd)
        ]
        leads = [
            row["request_id"] for row in HRPDDashboardService.supervisor_queue(self.pl)
        ]

        self.assertIn(mine.id, directors)
        self.assertNotIn(theirs.id, directors)
        self.assertIn(theirs.id, leads)
        self.assertNotIn(mine.id, leads)

    def test_the_form_names_the_reviewer_the_request_will_go_to(self):
        """These were two separate queries. Once routing read the chart and
        the header did not, the form would have named nobody while the request
        went to the Director."""
        info = staff_display_info(self.pl)

        self.assertEqual(info["supervisor_staff_id"], self.cd_sp.id)
        self.assertEqual(info["supervisor_name"], self.cd.name)
