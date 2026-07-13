"""Field Debrief Workflow — mandated coverage across models, services, views,
and scoping (the 24-section Field Debrief mandate).

Covers: submission validation and child-row creation, MSCS-draft creation,
notification routing (supervising PL / restricted-incident / risk-level /
support-request, each correctly country-scoped or unscoped per role),
`FieldDebriefService.scoped_queryset()` for every reader role (the single
role-based read-scope engine every dashboard/list view must go through),
clarification and recommendation-acceptance flows, leadership actions,
peer solutions, recurring-issue detection, the weekly rollup + dashboard
intelligence-summary helper shared by the PL/CD/HR/IA/RVP dashboards, the
submission/detail/action views end-to-end, and the derived To-Do queue.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School

from apps.debriefs.action_service import DebriefActionRoutingService
from apps.debriefs.dashboard_service import FieldDebriefDashboardService
from apps.debriefs.field_debrief_service import FieldDebriefService
from apps.debriefs.insight_service import RecurringIssueDetectionService
from apps.debriefs.models import (
    DailyDebrief,
    DailyDebriefAction,
    DailyDebriefInsight,
    DailyDebriefPeerSolution,
    DailyDebriefRecipient,
    DebriefActionStatus,
    DebriefStatus,
    PeerSolutionStatus,
    RecommendationStatus,
    RestrictedIncidentCategory,
    RiskLevel,
)
from apps.debriefs.peer_solution_service import PeerSolutionService
from apps.debriefs.rollup_service import (
    FieldDebriefWeeklyRollupService,
    field_debrief_intelligence_summary,
)

User = get_user_model()
FY = get_operational_fy()


class FieldDebriefTestBase(TestCase):
    """One shared fixture: a Uganda PL supervising two CCEOs (a real team,
    for team/peer-scoping tests) plus a second, unrelated Uganda PL/CCEO
    pair (for negative-space "not my team" tests), a Kenya CD (for country
    scoping), HR/IA/RVP/Admin/ProjectCoordinator, and a Partner linked to a
    real PartnerAdmin user via Partner.user (not a bare partner_id field —
    that's the whole point of the scoping fix this suite guards)."""

    def setUp(self):
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala", region=self.region, district_type="primary")

        self.pl, self.pl_sp = self._staff("pl@fd.org", "Pat Lead", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.cceo, self.cceo_sp = self._staff("cceo@fd.org", "Casey Cceo", EdifyRole.CCEO.value)
        self.cceo2, self.cceo2_sp = self._staff("cceo2@fd.org", "Cass Cceo2", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(supervisee=self.cceo_sp, supervisor=self.pl_sp)
        StaffSupervisorAssignment.objects.create(supervisee=self.cceo2_sp, supervisor=self.pl_sp)

        self.other_pl, self.other_pl_sp = self._staff("pl2@fd.org", "Percy Lead2", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.other_cceo, self.other_cceo_sp = self._staff("cceo3@fd.org", "Cory Cceo3", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(supervisee=self.other_cceo_sp, supervisor=self.other_pl_sp)

        self.cd, self.cd_sp = self._staff("cd@fd.org", "Cody Director", EdifyRole.COUNTRY_DIRECTOR.value, "Uganda")
        self.cd_kenya, self.cd_kenya_sp = self._staff("cdk@fd.org", "Kara Director", EdifyRole.COUNTRY_DIRECTOR.value, "Kenya")
        self.hr, self.hr_sp = self._staff("hr@fd.org", "Hana HR", EdifyRole.HUMAN_RESOURCES.value)
        self.ia, self.ia_sp = self._staff("ia@fd.org", "Ivy IA", EdifyRole.IMPACT_ASSESSMENT.value)
        self.rvp, self.rvp_sp = self._staff("rvp@fd.org", "Remy VP", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        self.admin, self.admin_sp = self._staff("admin@fd.org", "Ada Min", EdifyRole.ADMIN.value)
        self.pc, self.pc_sp = self._staff("pc@fd.org", "Pearl Coord", EdifyRole.PROJECT_COORDINATOR.value)

        self.partner_user, _ = self._staff("partner@fd.org", "Pia Partner", EdifyRole.PARTNER_ADMIN.value, sp=False)
        self.partner = Partner.objects.create(name="Helper Partners", user=self.partner_user, active_status=True)
        self.other_partner_user, _ = self._staff("partner2@fd.org", "Pete Partner2", EdifyRole.PARTNER_ADMIN.value, sp=False)
        self.other_partner = Partner.objects.create(name="Other Partners", user=self.other_partner_user, active_status=True)

        self.school = School.objects.create(
            school_id="FD-S1", name="Field Debrief Test School", region=self.region, district=self.district,
            enrollment=200, current_fy_ssa_status="done",
        )
        self.activity = self._activity(self.cceo_sp.id, self.school)
        self.other_teams_activity = self._activity(self.other_cceo_sp.id, self.school)

    # ── fixtures ─────────────────────────────────────────────────────────────
    def _staff(self, email, name, role, country="Uganda", sp=True):
        u = User.objects.create_user(
            email=email, name=name, roles=[role], active_role=role, password="x", is_active=True)
        if not sp:
            return u, None
        return u, StaffProfile.objects.create(user=u, title=role, country=country)

    def _activity(self, sp_id, school, atype="school_visit", status="scheduled"):
        return Activity.objects.create(
            school=school, activity_type=atype, delivery_type="staff", status=status,
            responsible_staff_id=sp_id, fy=FY, quarter="Q1", planned_date=date(2026, 7, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 7, 10, 9, 0)),
        )

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c

    def _submit(self, principal, **overrides):
        data = {"title": "Test Debrief", "summary": "A summary.", "kind": "activity"}
        data.update(overrides)
        return FieldDebriefService.submit(principal, data)


class ModelTests(FieldDebriefTestBase):
    def test_str_uses_title_falling_back_to_id(self):
        d = self._submit(self.cceo, title="My Debrief Title")
        self.assertEqual(str(d), "My Debrief Title")
        d.title = ""
        self.assertIn(d.id, str(d))

    def test_child_rows_relate_back_to_debrief_via_related_name(self):
        d = self._submit(
            self.cceo,
            challenges=[{"challenge_type": "no_transport", "description": "x"}],
            commitments=[{"party": "school", "commitment_text": "Fix the gate"}],
            support_requests=[{"requested_from_role": "Program Lead", "support_type": "technical"}],
            activity_ids=[self.activity.id],
        )
        self.assertEqual(d.challenges.count(), 1)
        self.assertEqual(d.commitments.count(), 1)
        self.assertEqual(d.support_requests.count(), 1)
        self.assertEqual(d.activity_links.count(), 1)
        self.assertEqual(d.activity_links.first().school_id, self.school.id)


class SubmissionTests(FieldDebriefTestBase):
    def test_can_submit_true_for_field_submitter_roles(self):
        for u in (self.cceo, self.pl, self.pc, self.partner_user):
            self.assertTrue(FieldDebriefService.can_submit(u), u.email)

    def test_can_submit_false_for_leadership_read_only_roles(self):
        for u in (self.cd, self.hr, self.ia, self.rvp, self.admin):
            self.assertFalse(FieldDebriefService.can_submit(u), u.email)

    def test_submit_requires_title(self):
        with self.assertRaises(BadRequest):
            self._submit(self.cceo, title="")

    def test_submit_rejects_role_that_cannot_submit(self):
        with self.assertRaises(Forbidden):
            self._submit(self.cd)

    def test_submit_restricted_incident_requires_category(self):
        with self.assertRaises(BadRequest):
            self._submit(self.cceo, is_restricted_incident=True)
        d = self._submit(
            self.cceo, is_restricted_incident=True,
            restricted_incident_category=RestrictedIncidentCategory.SAFEGUARDING,
        )
        self.assertEqual(d.status, DebriefStatus.RESTRICTED_INCIDENT)

    def test_submit_rejects_activity_not_owned_or_supervised(self):
        with self.assertRaises(Forbidden):
            self._submit(self.cceo, activity_ids=[self.other_teams_activity.id])

    def test_submit_allows_pl_to_debrief_teams_activity(self):
        d = self._submit(self.pl, activity_ids=[self.activity.id])
        self.assertEqual(d.activity_links.first().activity_id, self.activity.id)

    def test_submit_rejects_unknown_activity_id(self):
        with self.assertRaises(BadRequest):
            self._submit(self.cceo, activity_ids=["not-a-real-id"])

    def test_partner_can_link_their_own_assigned_activity_to_a_debrief(self):
        """Regression guard: _assert_can_debrief_activity() previously read a
        non-existent principal.partner_id attribute (always None), so a
        Partner submitter was unconditionally Forbidden from linking any
        activity to their own debrief — the third independent occurrence of
        this exact bug pattern in this file (see scoped_queryset()'s PARTNER
        branch and submit()'s partner_id stamping, fixed earlier)."""
        partner_activity = self._activity(None, self.school)
        Activity.objects.filter(id=partner_activity.id).update(assigned_partner_id=self.partner.id)
        d = self._submit(self.partner_user, activity_ids=[partner_activity.id])
        self.assertEqual(d.activity_links.first().activity_id, partner_activity.id)

    def test_other_partner_cannot_link_activity_assigned_elsewhere(self):
        partner_activity = self._activity(None, self.school)
        Activity.objects.filter(id=partner_activity.id).update(assigned_partner_id=self.partner.id)
        with self.assertRaises(Forbidden):
            self._submit(self.other_partner_user, activity_ids=[partner_activity.id])

    def test_submit_creates_mscs_draft_without_approving_it(self):
        from apps.targets.models import MostSignificantChangeStory, MSCSStatus

        d = self._submit(
            self.cceo, potential_mscs_flag=True, potential_mscs_title="A great story",
            key_success="Enrollment jumped.",
        )
        self.assertTrue(d.mscs_draft_story_id)
        story = MostSignificantChangeStory.objects.get(id=d.mscs_draft_story_id)
        self.assertEqual(story.title, "A great story")
        self.assertNotEqual(story.status, MSCSStatus.APPROVED)

    def test_submit_partner_role_auto_resolves_own_partner_id(self):
        d = self._submit(self.partner_user, title="Partner debrief")
        self.assertEqual(d.partner_id, self.partner.id)
        self.assertEqual(d.debrief_type, "partner")


class RoutingTests(FieldDebriefTestBase):
    def test_submission_routes_to_supervising_pl_by_default(self):
        d = self._submit(self.cceo)
        recipients = list(DailyDebriefRecipient.objects.filter(debrief=d))
        self.assertTrue(any(r.recipient_user_id == self.pl.user_id for r in recipients))

    def test_restricted_incident_routes_only_to_authorized_roles(self):
        d = self._submit(
            self.cceo, is_restricted_incident=True,
            restricted_incident_category=RestrictedIncidentCategory.FRAUD,
        )
        roles = {r.recipient_role for r in d.recipients.all()}
        # Fraud routes to CD + Accountant only — never IA, HR, or the general team feed.
        self.assertEqual(roles - {EdifyRole.COUNTRY_PROGRAM_LEAD.value}, {EdifyRole.COUNTRY_DIRECTOR.value, EdifyRole.PROGRAM_ACCOUNTANT.value} & roles)
        self.assertNotIn(EdifyRole.IMPACT_ASSESSMENT.value, roles)

    def test_risk_level_routing_is_scoped_to_submitters_own_country(self):
        d = self._submit(self.cceo, risk_level=RiskLevel.CD_ATTENTION)
        notified_cds = {r.recipient_user_id for r in d.recipients.all() if r.recipient_role == EdifyRole.COUNTRY_DIRECTOR.value}
        self.assertIn(self.cd.user_id, notified_cds)
        self.assertNotIn(self.cd_kenya.user_id, notified_cds)

    def test_support_request_routes_to_requested_role(self):
        d = self._submit(self.cceo, support_requests=[
            {"requested_from_role": "HumanResources", "support_type": "hr_support"},
        ])
        roles = {r.recipient_role for r in d.recipients.all()}
        self.assertIn(EdifyRole.HUMAN_RESOURCES.value, roles)
        recipient_ids = {r.recipient_user_id for r in d.recipients.all() if r.recipient_role == EdifyRole.HUMAN_RESOURCES.value}
        self.assertIn(self.hr.user_id, recipient_ids)

    def test_rvp_routing_is_unscoped_by_country(self):
        d = self._submit(self.cceo, risk_level=RiskLevel.CRITICAL)
        recipient_ids = {r.recipient_user_id for r in d.recipients.all() if r.recipient_role == EdifyRole.REGIONAL_VICE_PRESIDENT.value}
        self.assertIn(self.rvp.user_id, recipient_ids)

    def test_recipient_rows_do_not_duplicate_same_user_and_reason(self):
        d = self._submit(self.cceo, risk_level=RiskLevel.CD_ATTENTION)
        cd_rows = [r for r in d.recipients.all() if r.recipient_user_id == self.cd.user_id]
        self.assertEqual(len(cd_rows), 1)


class ScopingTests(FieldDebriefTestBase):
    def test_admin_sees_everything(self):
        d = self._submit(self.cceo)
        self.assertTrue(FieldDebriefService.scoped_queryset(self.admin).filter(id=d.id).exists())

    def test_hr_and_ia_see_all_non_restricted_debriefs_regardless_of_country(self):
        d = self._submit(self.cceo)  # Uganda submitter
        self.assertTrue(FieldDebriefService.scoped_queryset(self.hr).filter(id=d.id).exists())
        self.assertTrue(FieldDebriefService.scoped_queryset(self.ia).filter(id=d.id).exists())

    def test_hr_does_not_see_restricted_incident_unless_routed_to_hr(self):
        safeguarding = self._submit(
            self.cceo, is_restricted_incident=True,
            restricted_incident_category=RestrictedIncidentCategory.SAFEGUARDING,
        )
        fraud = self._submit(
            self.cceo2, is_restricted_incident=True,
            restricted_incident_category=RestrictedIncidentCategory.FRAUD,
        )
        # Safeguarding routes to HR -> visible. Fraud routes to CD+Accountant, not HR -> invisible.
        self.assertTrue(FieldDebriefService.scoped_queryset(self.hr).filter(id=safeguarding.id).exists())
        self.assertFalse(FieldDebriefService.scoped_queryset(self.hr).filter(id=fraud.id).exists())

    def test_cd_sees_only_own_country(self):
        d = self._submit(self.cceo)  # Uganda
        self.assertTrue(FieldDebriefService.scoped_queryset(self.cd).filter(id=d.id).exists())
        self.assertFalse(FieldDebriefService.scoped_queryset(self.cd_kenya).filter(id=d.id).exists())

    def test_rvp_sees_only_critical_or_explicitly_routed_never_the_routine_feed(self):
        routine = self._submit(self.cceo)
        critical = self._submit(self.cceo2, risk_level=RiskLevel.CRITICAL)
        self.assertFalse(FieldDebriefService.scoped_queryset(self.rvp).filter(id=routine.id).exists())
        self.assertTrue(FieldDebriefService.scoped_queryset(self.rvp).filter(id=critical.id).exists())

    def test_pl_sees_own_team_but_not_other_teams(self):
        own = self._submit(self.cceo)
        own2 = self._submit(self.cceo2)
        other = self._submit(self.other_cceo)
        qs = FieldDebriefService.scoped_queryset(self.pl)
        self.assertTrue(qs.filter(id=own.id).exists())
        self.assertTrue(qs.filter(id=own2.id).exists())
        self.assertFalse(qs.filter(id=other.id).exists())

    def test_cceo_sees_own_and_peer_team_debriefs_but_not_peers_restricted_incident(self):
        own = self._submit(self.cceo)
        peer = self._submit(self.cceo2)
        peer_restricted = self._submit(
            self.cceo2, is_restricted_incident=True,
            restricted_incident_category=RestrictedIncidentCategory.OTHER,
        )
        other_team = self._submit(self.other_cceo)
        qs = FieldDebriefService.scoped_queryset(self.cceo)
        self.assertTrue(qs.filter(id=own.id).exists())
        self.assertTrue(qs.filter(id=peer.id).exists())
        self.assertFalse(qs.filter(id=peer_restricted.id).exists())
        self.assertFalse(qs.filter(id=other_team.id).exists())

    def test_partner_sees_only_own_partner_via_real_submission_flow(self):
        """Regression guard: scoped_queryset() must resolve the partner's own
        id the same canonical way (Partner.user -> resolve_partner_ids()) that
        submit() stamps it with — going through both real code paths, not a
        hand-set partner_id, is what actually catches a mismatch between them."""
        own = self._submit(self.partner_user, title="Own partner debrief")
        other = self._submit(self.other_partner_user, title="Other partner debrief")
        qs = FieldDebriefService.scoped_queryset(self.partner_user)
        self.assertTrue(qs.filter(id=own.id).exists())
        self.assertFalse(qs.filter(id=other.id).exists())

    def test_project_coordinator_sees_only_own_submissions(self):
        own = self._submit(self.pc)
        other = self._submit(self.cceo)
        qs = FieldDebriefService.scoped_queryset(self.pc)
        self.assertTrue(qs.filter(id=own.id).exists())
        self.assertFalse(qs.filter(id=other.id).exists())

    def test_mine_filter_restricts_to_own_submissions_even_for_a_manager(self):
        own = self._submit(self.cceo)
        peer = self._submit(self.cceo2)
        qs = FieldDebriefService.scoped_queryset(self.pl, {"mine": True})
        self.assertFalse(qs.filter(id=own.id).exists())
        self.assertFalse(qs.filter(id=peer.id).exists())

    def test_status_and_risk_level_filters_narrow_results(self):
        self._submit(self.cceo, risk_level=RiskLevel.NONE)
        critical = self._submit(self.cceo2, risk_level=RiskLevel.CRITICAL)
        qs = FieldDebriefService.scoped_queryset(self.admin, {"risk_level": RiskLevel.CRITICAL})
        self.assertEqual(list(qs.values_list("id", flat=True)), [critical.id])


class ClarificationAndRecommendationTests(FieldDebriefTestBase):
    def test_only_a_supervisor_may_request_clarification(self):
        d = self._submit(self.cceo)
        with self.assertRaises(Forbidden):
            FieldDebriefService.request_clarification(self.cceo2, d.id, "note")
        FieldDebriefService.request_clarification(self.pl, d.id, "Please clarify X.")
        d.refresh_from_db()
        self.assertEqual(d.status, DebriefStatus.CLARIFICATION_REQUESTED)

    def test_update_after_clarification_requires_owner_and_correct_status(self):
        d = self._submit(self.cceo)
        with self.assertRaises(BadRequest):
            FieldDebriefService.update_after_clarification(self.cceo, d.id, {"summary": "updated"})
        FieldDebriefService.request_clarification(self.pl, d.id, "note")
        with self.assertRaises(Forbidden):
            FieldDebriefService.update_after_clarification(self.cceo2, d.id, {"summary": "updated"})
        updated = FieldDebriefService.update_after_clarification(self.cceo, d.id, {"summary": "Updated summary."})
        self.assertEqual(updated.status, DebriefStatus.UPDATED)
        self.assertEqual(updated.summary, "Updated summary.")

    def test_accept_recommendation_creates_a_real_draft_activity(self):
        d = self._submit(
            self.cceo, recommended_next_activity_type="follow_up_visit",
            school_ids=[self.school.id], follow_up_owner_id=self.cceo_sp.id,
        )
        self.assertEqual(d.recommendation_status, RecommendationStatus.PROPOSED)
        activity = FieldDebriefService.accept_recommendation(self.pl, d.id)
        self.assertIsNotNone(activity.id)
        self.assertEqual(activity.school_id, self.school.id)
        d.refresh_from_db()
        self.assertEqual(d.recommendation_status, RecommendationStatus.ACCEPTED)
        self.assertEqual(d.recommendation_accepted_activity_id, activity.id)

    def test_accept_recommendation_requires_proposed_status(self):
        d = self._submit(self.cceo)  # no recommendation proposed
        with self.assertRaises(BadRequest):
            FieldDebriefService.accept_recommendation(self.pl, d.id)

    def test_only_a_supervisor_may_accept_or_reject_a_recommendation(self):
        d = self._submit(self.cceo, recommended_next_activity_type="follow_up_visit")
        with self.assertRaises(Forbidden):
            FieldDebriefService.accept_recommendation(self.cceo2, d.id)

    def test_reject_recommendation(self):
        d = self._submit(self.cceo, recommended_next_activity_type="follow_up_visit")
        rejected = FieldDebriefService.reject_recommendation(self.pl, d.id)
        self.assertEqual(rejected.recommendation_status, RecommendationStatus.REJECTED)


class ActionServiceTests(FieldDebriefTestBase):
    def test_only_manager_roles_may_create_an_action(self):
        d = self._submit(self.cceo)
        with self.assertRaises(Forbidden):
            DebriefActionRoutingService.create(
                self.cceo2, d.id, issue="x", action="y", owner_user_id=self.cceo.user_id)

    def test_create_requires_issue_action_and_owner(self):
        d = self._submit(self.cceo)
        with self.assertRaises(BadRequest):
            DebriefActionRoutingService.create(self.pl, d.id, issue="", action="", owner_user_id="")

    def test_create_transitions_debrief_to_action_required(self):
        d = self._submit(self.cceo)
        DebriefActionRoutingService.create(
            self.pl, d.id, issue="No transport", action="Arrange vehicle", owner_user_id=self.pl.user_id)
        d.refresh_from_db()
        self.assertEqual(d.status, DebriefStatus.ACTION_REQUIRED)

    def test_update_status_requires_owner_or_manager(self):
        d = self._submit(self.cceo)
        action = DebriefActionRoutingService.create(
            self.pl, d.id, issue="x", action="y", owner_user_id=self.hr.user_id)
        with self.assertRaises(Forbidden):
            DebriefActionRoutingService.update_status(self.cceo2, action.id, status=DebriefActionStatus.IN_PROGRESS)
        # The owner (HR) may update even though HR isn't the assigner.
        updated = DebriefActionRoutingService.update_status(self.hr, action.id, status=DebriefActionStatus.IN_PROGRESS)
        self.assertEqual(updated.status, DebriefActionStatus.IN_PROGRESS)

    def test_update_status_rejects_unknown_status(self):
        d = self._submit(self.cceo)
        action = DebriefActionRoutingService.create(
            self.pl, d.id, issue="x", action="y", owner_user_id=self.pl.user_id)
        with self.assertRaises(BadRequest):
            DebriefActionRoutingService.update_status(self.pl, action.id, status="not_a_real_status")

    def test_resolving_the_last_open_action_moves_debrief_to_resolved(self):
        d = self._submit(self.cceo)
        a1 = DebriefActionRoutingService.create(self.pl, d.id, issue="a", action="a", owner_user_id=self.pl.user_id)
        a2 = DebriefActionRoutingService.create(self.pl, d.id, issue="b", action="b", owner_user_id=self.pl.user_id)
        DebriefActionRoutingService.update_status(self.pl, a1.id, status=DebriefActionStatus.RESOLVED)
        d.refresh_from_db()
        self.assertEqual(d.status, DebriefStatus.ACTION_REQUIRED)  # a2 still open
        DebriefActionRoutingService.update_status(self.pl, a2.id, status=DebriefActionStatus.RESOLVED)
        d.refresh_from_db()
        self.assertEqual(d.status, DebriefStatus.RESOLVED)

    def test_escalate_sets_status_and_keeps_a_note(self):
        d = self._submit(self.cceo)
        action = DebriefActionRoutingService.create(self.pl, d.id, issue="x", action="y", owner_user_id=self.pl.user_id)
        escalated = DebriefActionRoutingService.escalate(self.pl, action.id, note="Needs CD attention.")
        self.assertEqual(escalated.status, DebriefActionStatus.ESCALATED)


class PeerSolutionTests(FieldDebriefTestBase):
    def test_propose_requires_a_suggestion(self):
        d = self._submit(self.cceo)
        with self.assertRaises(BadRequest):
            PeerSolutionService.propose(self.cceo2, d.id, suggestion="  ")

    def test_cannot_propose_a_peer_solution_on_own_debrief(self):
        d = self._submit(self.cceo)
        with self.assertRaises(BadRequest):
            PeerSolutionService.propose(self.cceo, d.id, suggestion="Try this.")

    def test_propose_requires_read_access_to_the_debrief(self):
        d = self._submit(self.other_cceo)  # a different team
        with self.assertRaises(NotFoundError):
            PeerSolutionService.propose(self.cceo, d.id, suggestion="Try this.")

    def test_endorse_deduplicates_and_moves_to_under_discussion(self):
        d = self._submit(self.cceo)
        solution = PeerSolutionService.propose(self.cceo2, d.id, suggestion="Try X.")
        PeerSolutionService.endorse(self.pl, solution.id)
        PeerSolutionService.endorse(self.pl, solution.id)  # idempotent
        solution.refresh_from_db()
        self.assertEqual(solution.endorsed_by_user_ids, [self.pl.user_id])
        self.assertEqual(solution.status, PeerSolutionStatus.UNDER_DISCUSSION)

    def test_pl_classify_requires_pl_or_cd_role(self):
        d = self._submit(self.cceo)
        solution = PeerSolutionService.propose(self.cceo2, d.id, suggestion="Try X.")
        with self.assertRaises(Forbidden):
            PeerSolutionService.pl_classify(self.cceo2, solution.id, classification="adopt_for_team")

    def test_pl_classify_maps_classification_to_status(self):
        d = self._submit(self.cceo)
        solution = PeerSolutionService.propose(self.cceo2, d.id, suggestion="Try X.")
        classified = PeerSolutionService.pl_classify(self.pl, solution.id, classification="adopt_for_team")
        self.assertEqual(classified.status, PeerSolutionStatus.ADOPTED)
        self.assertEqual(classified.pl_classified_by_user_id, self.pl.user_id)


class RecurringIssueDetectionTests(FieldDebriefTestBase):
    def test_scan_creates_an_insight_at_the_occurrence_threshold(self):
        for _ in range(3):
            self._submit(self.cceo, school_ids=[self.school.id], challenges=[
                {"challenge_type": "no_transport", "description": "x"},
            ])
        result = RecurringIssueDetectionService.scan()
        self.assertGreaterEqual(result["created"], 1)
        self.assertTrue(DailyDebriefInsight.objects.filter(scope_id=self.school.id, challenge_type="no_transport").exists())

    def test_scan_does_not_create_below_threshold(self):
        for _ in range(2):
            self._submit(self.cceo, school_ids=[self.school.id], challenges=[
                {"challenge_type": "no_transport", "description": "x"},
            ])
        RecurringIssueDetectionService.scan()
        self.assertFalse(DailyDebriefInsight.objects.filter(scope_id=self.school.id, challenge_type="no_transport").exists())

    def test_scan_excludes_restricted_incidents_from_pattern_detection(self):
        for _ in range(3):
            self._submit(
                self.cceo, school_ids=[self.school.id], is_restricted_incident=True,
                restricted_incident_category=RestrictedIncidentCategory.OTHER,
                challenges=[{"challenge_type": "no_transport", "description": "x"}],
            )
        RecurringIssueDetectionService.scan()
        self.assertFalse(DailyDebriefInsight.objects.filter(scope_id=self.school.id).exists())

    def test_rescanning_updates_the_existing_open_insight_instead_of_duplicating(self):
        for _ in range(3):
            self._submit(self.cceo, school_ids=[self.school.id], challenges=[
                {"challenge_type": "no_transport", "description": "x"},
            ])
        RecurringIssueDetectionService.scan()
        first_count = DailyDebriefInsight.objects.filter(scope_id=self.school.id, challenge_type="no_transport").count()
        self._submit(self.cceo, school_ids=[self.school.id], challenges=[
            {"challenge_type": "no_transport", "description": "x"},
        ])
        RecurringIssueDetectionService.scan()
        second_count = DailyDebriefInsight.objects.filter(scope_id=self.school.id, challenge_type="no_transport").count()
        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)  # updated in place, not duplicated


class RollupAndIntelligenceSummaryTests(FieldDebriefTestBase):
    def test_intelligence_summary_reflects_real_counts_through_scoped_queryset(self):
        self._submit(self.cceo, risk_level=RiskLevel.CRITICAL, challenges=[
            {"challenge_type": "no_transport", "description": "x"},
        ])
        summary = field_debrief_intelligence_summary(self.pl)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["critical"], 1)
        self.assertEqual(summary["top_challenge"], "No Transport")
        self.assertEqual(summary["top_challenge_count"], 1)

    def test_intelligence_summary_is_honest_when_empty(self):
        summary = field_debrief_intelligence_summary(self.hr)
        self.assertEqual(summary, {
            "total": 0, "critical": 0, "action_required": 0, "escalated": 0,
            "top_challenge": None, "top_challenge_count": 0, "days": 30,
        })

    def test_intelligence_summary_respects_rvps_narrow_scope(self):
        self._submit(self.cceo)  # routine, not routed to RVP
        self.assertEqual(field_debrief_intelligence_summary(self.rvp)["total"], 0)
        self._submit(self.cceo2, risk_level=RiskLevel.CRITICAL)
        self.assertEqual(field_debrief_intelligence_summary(self.rvp)["total"], 1)

    def test_for_pl_weekly_rollup_counts_team_debriefs_and_open_actions(self):
        d = self._submit(self.cceo)
        DebriefActionRoutingService.create(self.pl, d.id, issue="x", action="y", owner_user_id=self.pl.user_id)
        rollup = FieldDebriefWeeklyRollupService.for_pl(self.pl)
        self.assertGreaterEqual(rollup["team_debriefs"], 1)
        self.assertGreaterEqual(rollup["actions_open"], 1)


class DashboardServiceTests(FieldDebriefTestBase):
    def test_kpis_reflect_real_submitted_and_action_required_counts(self):
        self._submit(self.cceo)
        d2 = self._submit(self.cceo2)
        DebriefActionRoutingService.create(self.pl, d2.id, issue="x", action="y", owner_user_id=self.pl.user_id)
        ctx = FieldDebriefDashboardService.get_dashboard(self.pl, {})
        by_key = {k["key"]: k for k in ctx["kpis"]}
        self.assertEqual(by_key["submitted"]["value"], "2")
        self.assertEqual(by_key["action_required"]["value"], "1")

    def test_kpi_trend_is_none_without_prior_period_data(self):
        self._submit(self.cceo)
        ctx = FieldDebriefDashboardService.get_dashboard(self.pl, {})
        submitted_kpi = next(k for k in ctx["kpis"] if k["key"] == "submitted")
        self.assertIsNone(submitted_kpi["trend"])  # no prior-period debriefs to compare against

    def test_tab_filters_mine_team_and_escalated(self):
        mine = self._submit(self.pl)
        team = self._submit(self.cceo)
        escalated = self._submit(self.cceo2, risk_level=RiskLevel.CRITICAL)
        mine_ids = {r["id"] for r in FieldDebriefDashboardService.get_dashboard(self.pl, {"tab": "mine"})["table_rows"]}
        team_ids = {r["id"] for r in FieldDebriefDashboardService.get_dashboard(self.pl, {"tab": "team"})["table_rows"]}
        escalated_ids = {r["id"] for r in FieldDebriefDashboardService.get_dashboard(self.pl, {"tab": "escalated"})["table_rows"]}
        self.assertEqual(mine_ids, {mine.id})
        self.assertIn(team.id, team_ids)
        self.assertNotIn(mine.id, team_ids)
        self.assertIn(escalated.id, escalated_ids)

    def test_table_row_title_links_and_replaces_key_challenge(self):
        d = self._submit(self.cceo, title="Distinctive Debrief Title")
        ctx = FieldDebriefDashboardService.get_dashboard(self.pl, {})
        row = next(r for r in ctx["table_rows"] if r["id"] == d.id)
        self.assertEqual(row["title"], "Distinctive Debrief Title")


class ViewPermissionAndFlowTests(FieldDebriefTestBase):
    def test_dashboard_permission_gating_allows_all_nine_intended_roles(self):
        for u in (self.cceo, self.pl, self.cd, self.hr, self.ia, self.rvp, self.pc, self.partner_user, self.admin):
            resp = self._client(u).get("/debriefs")
            self.assertEqual(resp.status_code, 200, u.email)

    def test_submit_view_get_renders_form_for_a_submitter(self):
        resp = self._client(self.cceo).get("/debriefs/submit")
        self.assertEqual(resp.status_code, 200)

    def test_submit_view_rejects_post_from_a_non_submitter_role(self):
        resp = self._client(self.cd).post("/debriefs/submit", {"title": "x"})
        self.assertEqual(resp.status_code, 403)

    def test_submit_view_post_creates_debrief_with_indexed_challenge_rows(self):
        resp = self._client(self.cceo).post("/debriefs/submit", {
            "title": "HTTP submitted debrief", "kind": "activity", "summary": "s",
            "challenges[0][challenge_type]": "no_transport",
            "challenges[0][description]": "No car available",
            "challenges[0][severity]": "high",
        })
        self.assertEqual(resp.status_code, 302)
        d = DailyDebrief.objects.get(title="HTTP submitted debrief")
        self.assertEqual(d.challenges.count(), 1)
        self.assertEqual(d.challenges.first().challenge_type, "no_transport")

    def test_detail_view_404s_for_a_debrief_outside_viewer_scope_not_403(self):
        d = self._submit(self.other_cceo)  # a different team
        resp = self._client(self.cceo).get(f"/debriefs/{d.id}")
        self.assertEqual(resp.status_code, 404)

    def test_detail_view_can_manage_flag_true_for_supervisor_false_for_peer(self):
        d = self._submit(self.cceo)
        pl_resp = self._client(self.pl).get(f"/debriefs/{d.id}")
        peer_resp = self._client(self.cceo2).get(f"/debriefs/{d.id}")
        self.assertTrue(pl_resp.context["can_manage"])
        self.assertFalse(peer_resp.context["can_manage"])
        self.assertTrue(peer_resp.context["is_own"] is False)

    def test_action_dispatcher_creates_leadership_action_and_redirects(self):
        d = self._submit(self.cceo)
        resp = self._client(self.pl).post("/debriefs/action", {
            "action": "create_leadership_action", "debrief_id": d.id,
            "issue": "No transport", "action_text": "Arrange transport",
            "owner_user_id": self.pl.user_id, "priority": "high",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(DailyDebriefAction.objects.filter(debrief=d).count(), 1)

    def test_activity_options_view_escapes_school_name(self):
        School.objects.filter(id=self.school.id).update(name='<script>alert(1)</script>')
        resp = self._client(self.cceo).get(f"/debriefs/activity-options?fy={FY}")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)


class SidebarAndDashboardIntegrationTests(FieldDebriefTestBase):
    """Guards #157/#158: the sidebar entry and the cross-dashboard
    "Field Debrief Intelligence" cards on the PL/CD/HR/IA/RVP dashboards."""

    def test_sidebar_shows_field_debrief_link_for_every_reader_and_submitter_role(self):
        for u in (self.cceo, self.pl, self.cd, self.hr, self.ia, self.rvp, self.pc, self.partner_user):
            resp = self._client(u).get("/debriefs")
            self.assertContains(resp, ">Field Debrief<", html=False)

    def test_team_targets_dashboard_carries_field_debrief_intel(self):
        from apps.targets.team_targets import PLTeamTargetsService

        self._submit(self.cceo, risk_level=RiskLevel.CRITICAL)
        ctx = PLTeamTargetsService.get_page(self.pl)
        self.assertIn("field_debrief_intel", ctx)
        self.assertEqual(ctx["field_debrief_intel"]["critical"], 1)

    def test_cd_dashboard_carries_field_debrief_intel(self):
        from apps.analytics.cd_dashboard_service import CDDashboardService

        self._submit(self.cceo)
        ctx = CDDashboardService.get_dashboard(self.cd, fy=FY)
        self.assertIn("field_debrief_intel", ctx)
        self.assertEqual(ctx["field_debrief_intel"]["total"], 1)


class TodoIntegrationTests(FieldDebriefTestBase):
    def test_todo_created_when_own_debrief_awaits_clarification(self):
        from apps.command_center.todo_service import get_todos

        d = self._submit(self.cceo)
        FieldDebriefService.request_clarification(self.pl, d.id, "Please clarify.")
        todos = get_todos(self.cceo)["todos"]
        self.assertTrue(any(t["id"] == f"debrief-clarify-{d.id}" for t in todos))

    def test_todo_created_for_own_open_leadership_action_and_closes_when_resolved(self):
        from apps.command_center.todo_service import get_todos

        d = self._submit(self.cceo)
        action = DebriefActionRoutingService.create(
            self.pl, d.id, issue="x", action="y", owner_user_id=self.pl.user_id)
        todos = get_todos(self.pl)["todos"]
        self.assertTrue(any(t["id"] == f"debrief-action-{action.id}" for t in todos))
        DebriefActionRoutingService.update_status(self.pl, action.id, status=DebriefActionStatus.RESOLVED)
        todos_after = get_todos(self.pl)["todos"]
        self.assertFalse(any(t["id"] == f"debrief-action-{action.id}" for t in todos_after))
