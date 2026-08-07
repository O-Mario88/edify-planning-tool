"""The Partner Oversight page: what it shows, and what it refuses to show.

The rules worth a test are the ones a reader would act on wrongly if they
broke. Three of them:

* the Yet-to-Schedule list has no cost column, and no zero standing in for one;
* the page reads and never writes, so no control on it edits a partner's
  schedule or a CCEO's activity;
* a partner's delay is never turned into a TeamAction against a CCEO, because
  the accountability queue would then say a CCEO is late when they are not.
"""

from __future__ import annotations

from datetime import date, timedelta


from apps.core.rbac import EdifyRole
from apps.notifications.models import Notification
from apps.planning import partner_oversight_actions as actions
from apps.planning import partner_oversight_service as svc
from apps.planning.action_service import ActionError
from apps.planning.models import TeamAction
from apps.planning.test_partner_oversight import PartnerOversightFixture


class PageFixture(PartnerOversightFixture):
    def sign_in(self, user):
        self.client.force_login(user)
        return user


class PageRendersTest(PageFixture):
    def test_the_program_lead_sees_the_page_grouped_by_partner(self):
        self.assign()
        self.schedule(self.assign(partner=self.other_partner), cost=180_000)
        self.sign_in(self.pl_user)

        response = self.client.get("/partner-oversight/")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Partner X", body)
        self.assertIn("Partner Y", body)
        self.assertIn("Yet to Schedule", body)

    def test_a_cceo_sees_the_page_for_their_own_schools(self):
        """The CCEO helps the PL monitor. They were previously refused the
        page on the grounds that they reach the same records through the
        school; in practice that meant the person who knows the school best
        had no view of the partner working in it."""
        self.assign()
        self.sign_in(self.cceo_user)

        response = self.client.get("/partner-oversight/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Partner X", response.content.decode())

    def test_the_country_director_sees_every_partner(self):
        director = self._staff("cd@p.test", "Direktor", EdifyRole.COUNTRY_DIRECTOR)[0]
        self.assign()
        self.assign(cceo=self.rival_cceo, school=self.rival_school)
        self.sign_in(director)

        items = svc.build_items(director, fy=self.fy)

        self.assertEqual(len(items), 2)


class NoCostBeforeSchedulingOnThePageTest(PageFixture):
    def test_the_yet_to_schedule_table_has_no_cost_column(self):
        self.assign()
        self.sign_in(self.pl_user)

        body = self.client.get("/partner-oversight/").content.decode()

        table = body.split("Yet to Schedule")[1].split("Scheduled &amp; Delivering")[0]
        self.assertNotIn("UGX", table)
        self.assertNotIn("Pending Calculation", table)
        self.assertNotIn("Not Available", table)

    def test_the_drawer_says_the_cost_does_not_exist_rather_than_zero(self):
        assignment = self.assign()
        self.sign_in(self.pl_user)

        body = self.client.get(
            f"/partner-oversight/detail?assignment_id={assignment.id}"
        ).content.decode()

        self.assertIn("No cost exists for this assignment", body)
        self.assertNotIn("UGX 0", body)

    def test_the_export_leaves_the_cost_cell_empty_rather_than_zero(self):
        """A spreadsheet sums a column without asking what the zeros meant."""
        self.assign()
        self.schedule(self.assign(), cost=95_000)

        rows = list(svc.export_rows(svc.build_items(self.pl_user, fy=self.fy)))

        cost_index = svc.EXPORT_HEADER.index("Planned Cost (UGX)")
        costs = sorted(str(row[cost_index]) for row in rows[1:])
        self.assertEqual(costs, ["", "95000"])


class ReadOnlyTest(PageFixture):
    def test_the_page_offers_no_control_that_edits_partner_or_cceo_work(self):
        self.schedule(self.assign())
        self.sign_in(self.pl_user)

        body = self.client.get(
            "/partner-oversight/", headers={"HX-Request": "true"}
        ).content.decode()

        for forbidden in ("hx-post", "hx-put", "hx-patch", "hx-delete", "<form"):
            with self.subTest(control=forbidden):
                self.assertNotIn(forbidden, body)

    def test_the_only_writes_the_drawer_offers_are_asks(self):
        """Every form posts to the send endpoint, which writes no activity."""
        assignment = self.assign(
            status="returned_to_staff", return_reason="No capacity"
        )
        self.sign_in(self.pl_user)

        body = self.client.get(
            f"/partner-oversight/detail?assignment_id={assignment.id}"
        ).content.decode()

        posts = [
            line for line in body.splitlines() if "hx-post" in line or "hx-put" in line
        ]
        self.assertTrue(posts)
        for line in posts:
            with self.subTest(line=line.strip()):
                self.assertIn('hx-post="/partner-oversight/send"', line)


class SendRoutingTest(PageFixture):
    """Who an ask reaches is decided by the risk, not by the reader."""

    def _overdue_handover(self):
        assignment = self.assign()
        assignment.created_at = assignment.created_at.replace(year=2000)
        assignment.save(update_fields=["created_at"])
        return assignment

    def test_a_partner_delay_never_becomes_a_team_action_against_the_cceo(self):
        assignment = self._overdue_handover()
        item = svc.build_item_by_assignment(assignment.id)

        with self.assertRaises(ActionError) as caught:
            actions.send_to_managing_cceo(
                sender=self.pl_user, item=item, risk_key="partner_schedule_overdue"
            )

        self.assertIn("managing CCEO can clear", str(caught.exception))
        self.assertFalse(TeamAction.objects.exists())

    def test_reminding_the_partner_notifies_their_login_account(self):
        self.partner.user = self._staff(
            "partner@p.test", "Partner X Officer", EdifyRole.PARTNER_FIELD_OFFICER
        )[0]
        self.partner.save()
        assignment = self._overdue_handover()
        item = svc.build_item_by_assignment(assignment.id)

        actions.remind_partner(
            sender=self.pl_user, item=item, risk_key="partner_schedule_overdue"
        )

        note = Notification.objects.get(
            recipient_id=self.partner.user_id,
            source_event_type="partner_reminder.partner_schedule_overdue",
        )
        self.assertIn("School A", note.title)
        self.assertEqual(note.context_type, "PartnerAssignment")
        self.assertFalse(
            TeamAction.objects.exists(),
            "a partner is not a staff accountability record",
        )

    def test_a_partner_with_no_login_account_is_refused_rather_than_guessed_at(self):
        assignment = self._overdue_handover()
        item = svc.build_item_by_assignment(assignment.id)

        with self.assertRaises(ActionError) as caught:
            actions.remind_partner(
                sender=self.pl_user, item=item, risk_key="partner_schedule_overdue"
            )

        self.assertIn("no login account", str(caught.exception))

    def test_a_returned_assignment_goes_to_the_cceo_who_handed_it_over(self):
        assignment = self.assign(
            status="returned_to_staff", return_reason="No capacity this term"
        )
        item = svc.build_item_by_assignment(assignment.id)

        action = actions.send_to_managing_cceo(
            sender=self.pl_user, item=item, risk_key="assignment_returned"
        )

        self.assertEqual(action.recipient_id, self.cceo_user.id)
        self.assertEqual(action.issue_type, "assignment_returned")

    def test_the_same_condition_cannot_be_sent_twice(self):
        assignment = self.assign(
            status="returned_to_staff", return_reason="No capacity"
        )
        item = svc.build_item_by_assignment(assignment.id)
        actions.send_to_managing_cceo(
            sender=self.pl_user, item=item, risk_key="assignment_returned"
        )

        with self.assertRaises(ActionError) as caught:
            actions.send_to_managing_cceo(
                sender=self.pl_user, item=item, risk_key="assignment_returned"
            )

        self.assertIn("Already sent", str(caught.exception))
        self.assertEqual(TeamAction.objects.count(), 1)

    def test_a_send_for_a_condition_that_no_longer_holds_is_refused(self):
        assignment = self.assign()
        self.schedule(assignment)
        item = svc.build_item_by_assignment(assignment.id)

        with self.assertRaises(ActionError) as caught:
            actions.send_to_managing_cceo(
                sender=self.pl_user, item=item, risk_key="assignment_returned"
            )

        self.assertIn("no longer true", str(caught.exception))

    def test_escalation_requires_saying_what_was_already_tried(self):
        assignment = self.assign()
        item = svc.build_item_by_assignment(assignment.id)

        with self.assertRaises(ActionError):
            actions.escalate_to_country_director(sender=self.pl_user, item=item)

    def test_escalation_reaches_the_country_director(self):
        director_user, director = self._staff(
            "cd2@p.test", "Direktor", EdifyRole.COUNTRY_DIRECTOR
        )
        assignment = self.assign()
        item = svc.build_item_by_assignment(assignment.id)

        action = actions.escalate_to_country_director(
            sender=self.pl_user, item=item, note="Called them twice, no date."
        )

        self.assertEqual(action.recipient_id, director_user.id)
        self.assertEqual(action.issue_type, "partner_delivery_escalation")


class SendScopeTest(PageFixture):
    def test_another_program_lead_cannot_send_about_this_assignment(self):
        assignment = self.assign(
            status="returned_to_staff", return_reason="No capacity"
        )
        self.sign_in(self.rival_pl_user)

        response = self.client.post(
            "/partner-oversight/send",
            {
                "intent": "send_to_cceo",
                "risk": "assignment_returned",
                "assignment_id": assignment.id,
            },
            headers={"HX-Request": "true"},
        )

        self.assertIn("not in your team", response.content.decode())
        self.assertFalse(TeamAction.objects.exists())

    def test_an_unknown_intent_writes_nothing(self):
        assignment = self.assign()
        self.sign_in(self.pl_user)

        self.client.post(
            "/partner-oversight/send",
            {"intent": "reschedule", "assignment_id": assignment.id},
            headers={"HX-Request": "true"},
        )

        self.assertFalse(TeamAction.objects.exists())
        self.assertFalse(Notification.objects.exists())


class ActionClosesItselfTest(PageFixture):
    def test_a_returned_action_closes_once_the_partner_schedules_it(self):
        """The condition that opened the action is the one that closes it."""
        from apps.planning.action_service import resolve_due_actions

        assignment = self.assign(
            status="returned_to_staff", return_reason="No capacity"
        )
        item = svc.build_item_by_assignment(assignment.id)
        action = actions.send_to_managing_cceo(
            sender=self.pl_user, item=item, risk_key="assignment_returned"
        )

        self.schedule(assignment, when=date.today() + timedelta(days=3))
        resolve_due_actions()

        action.refresh_from_db()
        self.assertEqual(action.state, "resolved")


class SchoolProfilePartnerSupportTest(PageFixture):
    """The CCEO keeps school-context visibility of work they handed over."""

    def test_the_managing_cceo_sees_the_handover_on_their_school(self):
        self.assign()
        self.sign_in(self.cceo_user)

        from apps.planning import partner_oversight_service as service

        items = service.build_items_for_school(self.school.id)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].partner_name, "Partner X")

    def test_the_school_lens_is_scoped_by_school_not_by_reader(self):
        """A CCEO's own handover must not vanish from their own school page.

        Scoping this by the reader would do exactly that for any handover
        recorded against a colleague, which is the loss of context the section
        exists to prevent.
        """
        self.assign(cceo=self.rival_cceo, school=self.school)

        items = svc.build_items_for_school(self.school.id)

        self.assertEqual(len(items), 1)

    def test_an_unscheduled_handover_shows_no_cost_on_the_school_page(self):
        self.assign()

        item = svc.build_items_for_school(self.school.id)[0]

        self.assertFalse(item.has_cost)
        self.assertIsNone(item.planned_cost)

    def test_a_school_with_no_partner_work_returns_nothing_in_one_query(self):
        """The section costs a hot page one query when there is nothing to show."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            items = svc.build_items_for_school(self.rival_school.id)

        self.assertEqual(items, [])
        self.assertEqual(len(captured), 1)


class OperatingQueueTest(PageFixture):
    """An ask has to land somewhere the recipient actually looks."""

    def test_a_send_to_the_cceo_appears_on_their_to_do_queue(self):
        from apps.command_center.todo_service import get_todos

        assignment = self.assign(
            status="returned_to_staff", return_reason="No capacity"
        )
        item = svc.build_item_by_assignment(assignment.id)
        actions.send_to_managing_cceo(
            sender=self.pl_user, item=item, risk_key="assignment_returned"
        )

        queue = get_todos(self.cceo_user)
        rows = queue["todos"] if isinstance(queue, dict) else queue

        titles = " | ".join(str(t.get("title", "")) for t in rows)
        self.assertIn("returned assignment", titles.lower())

    def test_the_partner_reminder_reaches_the_partner_and_nobody_else(self):
        self.partner.user = self._staff(
            "officer@p.test", "Partner Officer", EdifyRole.PARTNER_FIELD_OFFICER
        )[0]
        self.partner.save()
        assignment = self.assign()
        assignment.created_at = assignment.created_at.replace(year=2000)
        assignment.save(update_fields=["created_at"])
        item = svc.build_item_by_assignment(assignment.id)

        actions.remind_partner(
            sender=self.pl_user, item=item, risk_key="partner_schedule_overdue"
        )

        reminders = Notification.objects.filter(
            source_event_type__startswith="partner_reminder."
        )
        self.assertEqual(
            list(reminders.values_list("recipient_id", flat=True)),
            [self.partner.user_id],
        )

    def test_reminding_twice_refreshes_one_notification_rather_than_stacking(self):
        """Three nudges about one unscheduled visit is noise, and noise is how
        the next real reminder gets ignored."""
        self.partner.user = self._staff(
            "officer2@p.test", "Partner Officer", EdifyRole.PARTNER_FIELD_OFFICER
        )[0]
        self.partner.save()
        assignment = self.assign()
        assignment.created_at = assignment.created_at.replace(year=2000)
        assignment.save(update_fields=["created_at"])
        item = svc.build_item_by_assignment(assignment.id)

        actions.remind_partner(
            sender=self.pl_user, item=item, risk_key="partner_schedule_overdue"
        )
        actions.remind_partner(
            sender=self.pl_user,
            item=item,
            risk_key="partner_schedule_overdue",
            note="Second ask",
        )

        reminders = Notification.objects.filter(
            source_event_type="partner_reminder.partner_schedule_overdue"
        )
        self.assertEqual(reminders.count(), 1)
        self.assertIn("Second ask", reminders.first().body)


class PartnerFilterTest(PageFixture):
    def test_choosing_a_partner_keeps_every_partner_in_the_dropdown(self):
        """Derived from the filtered set, the control would erase its own options."""
        self.assign(partner=self.partner)
        self.assign(partner=self.other_partner)
        self.sign_in(self.pl_user)

        body = self.client.get(
            f"/partner-oversight/?partner={self.partner.id}"
        ).content.decode()

        self.assertIn("Partner Y", body, "the other partner left the dropdown")
        self.assertIn(f'value="{self.other_partner.id}"', body)

    def test_choosing_a_partner_narrows_the_rows_to_that_partner(self):
        self.assign(partner=self.partner)
        self.assign(partner=self.other_partner)
        self.sign_in(self.pl_user)

        body = self.client.get(
            f"/partner-oversight/?partner={self.partner.id}",
            headers={"HX-Request": "true"},
        ).content.decode()

        self.assertIn("Partner X", body)
        self.assertNotIn("Partner Y", body)


class RoleQueueTest(PageFixture):
    """Impact Assessment and the Accountant are in the chain, so they must be
    reachable from it — and reachable as queues, not as named individuals."""

    def _ia(self, email="ia@p.test"):
        return self._staff(email, "IA Officer", EdifyRole.IMPACT_ASSESSMENT)[0]

    def _accountant(self):
        return self._staff("acc@p.test", "Book Keeper", EdifyRole.PROGRAM_ACCOUNTANT)[0]

    def _stuck_in_ia(self):
        """A partner completion sitting unverified past the SLA."""
        from django.utils import timezone

        assignment = self.assign()
        activity = self.schedule(assignment, when=date.today() - timedelta(days=30))
        activity.status = "awaiting_ia_verification"
        activity.evidence_status = "uploaded"
        activity.ia_verification_status = "pending"
        activity.submitted_to_ia_at = timezone.now() - timedelta(days=21)
        activity.save()
        return assignment

    def test_an_unverified_completion_names_impact_assessment(self):
        assignment = self._stuck_in_ia()

        item = svc.build_item_by_assignment(assignment.id)

        risk = next(r for r in item.risks if r["key"] == "ia_verification_overdue")
        self.assertEqual(risk["responsible_role"], "ImpactAssessment")
        self.assertEqual(risk["responsible"], "Impact Assessment")

    def test_the_nudge_reaches_every_active_ia_and_creates_no_team_action(self):
        first, second = self._ia(), self._ia("ia2@p.test")
        assignment = self._stuck_in_ia()
        item = svc.build_item_by_assignment(assignment.id)

        notified = actions.nudge_role_queue(
            sender=self.pl_user, item=item, risk_key="ia_verification_overdue"
        )

        self.assertEqual(set(notified), {first.id, second.id})
        self.assertFalse(
            TeamAction.objects.exists(),
            "a queue function must not be handed an individual's obligation",
        )

    def test_a_queue_with_no_active_holder_is_refused_not_silently_dropped(self):
        """'Sent' with nobody listening is worse than a refusal."""
        assignment = self._stuck_in_ia()
        item = svc.build_item_by_assignment(assignment.id)

        with self.assertRaises(ActionError) as caught:
            actions.nudge_role_queue(
                sender=self.pl_user, item=item, risk_key="ia_verification_overdue"
            )

        self.assertIn("no active Impact Assessment", str(caught.exception))

    def test_an_unpaid_verified_partner_activity_names_the_accountant(self):
        accountant = self._accountant()
        assignment = self.assign()
        activity = self.schedule(assignment, when=date.today() - timedelta(days=40))
        activity.status = "ia_verified"
        activity.salesforce_activity_id = "SF-9"
        activity.payment_status = "pending"
        activity.save()
        item = svc.build_item_by_assignment(assignment.id)

        risk = next(r for r in item.risks if r["key"] == "partner_payment_overdue")
        self.assertEqual(risk["responsible_role"], "Accountant")

        notified = actions.nudge_role_queue(
            sender=self.pl_user, item=item, risk_key="partner_payment_overdue"
        )
        self.assertEqual(notified, [accountant.id])

    def test_impact_assessment_can_open_the_partner_page_country_wide(self):
        ia = self._ia()
        self.assign()
        self.assign(cceo=self.rival_cceo, school=self.rival_school)
        self.sign_in(ia)

        response = self.client.get("/partner-oversight/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(svc.build_items(ia, fy=self.fy)), 2)

    def test_the_accountant_can_open_the_partner_page_country_wide(self):
        accountant = self._accountant()
        self.assign()
        self.sign_in(accountant)

        self.assertEqual(self.client.get("/partner-oversight/").status_code, 200)
        self.assertEqual(len(svc.build_items(accountant, fy=self.fy)), 1)

    def test_the_drawer_offers_the_queue_send_rather_than_a_cceo_send(self):
        self._ia()
        assignment = self._stuck_in_ia()
        self.sign_in(self.pl_user)

        body = self.client.get(
            f"/partner-oversight/detail?assignment_id={assignment.id}"
        ).content.decode()

        self.assertIn("Ask Impact Assessment", body)
        self.assertIn('value="nudge_queue"', body)

    def test_a_second_nudge_refreshes_rather_than_stacking(self):
        officer = self._ia()
        assignment = self._stuck_in_ia()
        item = svc.build_item_by_assignment(assignment.id)

        actions.nudge_role_queue(
            sender=self.pl_user, item=item, risk_key="ia_verification_overdue"
        )
        actions.nudge_role_queue(
            sender=self.pl_user,
            item=item,
            risk_key="ia_verification_overdue",
            note="Still waiting",
        )

        notes = Notification.objects.filter(
            recipient_id=officer.id,
            source_event_type="partner_oversight_nudge.ia_verification_overdue",
        )
        self.assertEqual(notes.count(), 1)
        self.assertIn("Still waiting", notes.first().body)


class WithdrawalActionIsStateAwareTest(PageFixture):
    """The row's action must name the decision the service will actually make.

    A row offering "Withdraw" over work that is going to be suspended is a
    promise the service breaks, so the label is derived from the same resolver
    the service uses rather than computed a second time in the template.
    """

    def _labelled(self, assignment):
        return svc.build_item_by_assignment(assignment.id).withdrawal_label

    def test_an_unscheduled_handover_offers_a_plain_withdrawal(self):
        self.assertEqual(self._labelled(self.assign()), "Withdraw assignment")

    def test_scheduled_work_offers_a_recall(self):
        a = self.assign()
        self.schedule(a)
        self.assertEqual(self._labelled(a), "Recall scheduled activity")

    def test_work_under_way_offers_a_suspension(self):
        a = self.assign()
        activity = self.schedule(a)
        activity.status = "in_progress"
        activity.save()
        self.assertEqual(self._labelled(a), "Suspend delivery and review")

    def test_submitted_evidence_offers_a_quality_review(self):
        a = self.assign()
        activity = self.schedule(a)
        activity.status = "evidence_uploaded"
        activity.evidence_status = "uploaded"
        activity.save()
        self.assertEqual(self._labelled(a), "Withdraw for quality review")

    def test_paid_work_offers_nothing(self):
        """Rewriting a settled activity is not a supervision decision."""
        a = self.assign()
        activity = self.schedule(a)
        activity.status = "ia_verified"
        activity.payment_status = "paid"
        activity.save()
        self.assertEqual(self._labelled(a), "")

    def test_the_row_and_the_service_agree_on_every_state(self):
        """The property that matters, asserted directly rather than inferred."""
        from apps.partners.withdrawal_service import resolve_kind
        from apps.partners.models import PartnerAssignment

        for status in (
            "partner_scheduled",
            "in_progress",
            "evidence_uploaded",
            "ia_verified",
        ):
            with self.subTest(status=status):
                a = self.assign()
                activity = self.schedule(a)
                activity.status = status
                activity.save()
                item = svc.build_item_by_assignment(a.id)
                fresh = PartnerAssignment.objects.select_related(
                    "scheduled_activity"
                ).get(id=a.id)
                self.assertEqual(item.withdrawal_kind, resolve_kind(fresh))


class CceoSeesTheirOwnPartnerWorkTest(PageFixture):
    """Shared visibility, unchanged authority.

    The CCEO joins this page to help the PL watch partner delivery. Two things
    have to hold at once: they see the partner work at their own schools, and
    they see nothing of anyone else's.
    """

    def test_they_see_partner_work_at_their_schools(self):
        self.assign()

        items = svc.build_items(self.cceo_user, fy=self.fy)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].school_name, "School A")

    def test_they_do_not_see_another_cceos_schools(self):
        self.assign()
        self.assign(cceo=self.rival_cceo, school=self.rival_school)

        items = svc.build_items(self.cceo_user, fy=self.fy)

        self.assertEqual([i.school_name for i in items], ["School A"])

    def test_a_handoff_with_no_monitor_recorded_still_reaches_the_owner(self):
        """The gap that made this more than a permission change.

        `monitoring_staff_id` is nullable, and every assignment written before
        that column existed falls back to the *assigner*. A partner handed off
        by the PL to this CCEO's school therefore resolves to the PL on those
        rows — and the CCEO who owns the school would open the page to nothing.
        Owning the school is the claim that does not depend on who clicked
        Handoff.
        """
        from apps.schools.models import School

        School.objects.filter(id=self.school.id).update(account_owner_id=self.cceo.id)
        assignment = self.assign()
        # Exactly the legacy shape: no monitor, assigned by the PL.
        type(assignment).objects.filter(id=assignment.id).update(
            monitoring_staff_id=None, assigning_staff_id=self.pl.id
        )

        items = svc.build_items(self.cceo_user, fy=self.fy)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].school_name, "School A")

    def test_ownership_does_not_widen_them_past_their_own_portfolio(self):
        """The new arm must not become a back door to the whole country."""
        from apps.schools.models import School

        School.objects.filter(id=self.rival_school.id).update(
            account_owner_id=self.rival_cceo.id
        )
        self.assign(cceo=self.rival_cceo, school=self.rival_school)

        self.assertEqual(svc.build_items(self.cceo_user, fy=self.fy), [])

    def test_they_get_none_of_the_pls_decision_queue(self):
        """Visibility is not authority. Requests are addressed to the
        supervising PL and stay there."""
        self.assign()

        self.assertEqual(svc.withdrawal_requests(self.cceo_user), [])

    def test_the_page_shows_them_no_requests_block(self):
        self.assign()
        self.sign_in(self.cceo_user)

        body = self.client.get("/partner-oversight/").content.decode()

        self.assertNotIn("Withdrawal requests", body)

    def test_the_pl_still_sees_their_whole_team(self):
        """Adding the CCEO must not narrow the supervisor who was already here."""
        self.assign()
        self.assign(partner=self.other_partner)

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertEqual(len(items), 2)

    def test_the_pl_also_gains_the_ownership_arm_for_their_team(self):
        """Same legacy gap, same fix, one level up."""
        from apps.schools.models import School

        School.objects.filter(id=self.school.id).update(account_owner_id=self.cceo.id)
        assignment = self.assign()
        type(assignment).objects.filter(id=assignment.id).update(
            monitoring_staff_id=None, assigning_staff_id=self.rival_pl.id
        )

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertEqual(len(items), 1)


class CceoVisibilityIsNotAuthorityTest(PageFixture):
    """Opening the page must not have opened the decisions on it.

    Adding the CCEO to `partner_oversight` widened seven routes at once,
    including the endpoint where a Program Lead answers a withdrawal request.
    Page permission is the outer door; the service is the lock.
    """

    def test_a_cceo_cannot_decide_a_withdrawal_request(self):
        from apps.core.exceptions import Forbidden
        from apps.partners import withdrawal_service

        with self.assertRaises(Forbidden) as caught:
            withdrawal_service.review_request(
                "any-id", {"decision": "approve"}, self.cceo_user
            )

        self.assertIn("Program Lead", str(caught.exception))

    def test_the_review_endpoint_refuses_them_over_http(self):
        self.sign_in(self.cceo_user)

        response = self.client.post(
            "/partner-oversight/withdraw/review",
            {"withdrawal_id": "any-id", "decision": "approve"},
        )

        self.assertNotIn(response.status_code, (500,))
        self.assertNotIn(
            "approved", response.content.decode().lower(), "no decision may land"
        )

    def test_the_supervising_pl_still_can(self):
        """The guard must refuse the CCEO without also refusing the PL."""
        from apps.core.permissions import has_permission
        from apps.core.rbac import Permission

        self.assertTrue(
            has_permission(self.pl_user, Permission.PARTNER_WITHDRAWAL_REVIEW.value)
        )
        self.assertFalse(
            has_permission(self.cceo_user, Permission.PARTNER_WITHDRAWAL_REVIEW.value)
        )
