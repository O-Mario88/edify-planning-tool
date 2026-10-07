"""Who may appoint whom, and what happens to an appointment afterwards.

Every refusal here is made by ``apps.acting.services`` on the server. The
"attempts" are requests a person could craft by hand: another team's officer,
another country's Lead, somebody else's appointment.
"""

from __future__ import annotations

from apps.accounts.models import StaffSupervisorAssignment, User
from apps.acting import services
from apps.acting.models import ACTIVE, CANCELLED, UPCOMING, ActingAssignment
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.notifications.models import Notification

from .fixtures import (
    NOVEMBER,
    NOVEMBER_1,
    OCTOBER,
    OCTOBER_1,
    OCTOBER_15,
    SEPTEMBER_15,
    ActingFixture,
    fresh,
    on_day,
)


class AppointingTests(ActingFixture):
    def test_a_lead_appoints_one_of_their_officers_for_a_month(self):
        with self.captureOnCommitCallbacks(execute=True):
            appointment = self.appoint_sarah()
        self.assertEqual(appointment.role_key, "acting_pl")
        self.assertEqual(appointment.acting_role, "Program Lead")
        self.assertEqual(appointment.appointee_id, self.sarah.id)
        self.assertEqual(appointment.appointee_role, "CCEO")
        self.assertEqual(appointment.appointed_by_id, self.john.id)
        self.assertEqual(appointment.seat_id, self.john_sp.id)
        self.assertEqual(appointment.scope_type, "pl_team")
        self.assertEqual(appointment.effective_label, "October 1 – October 31, 2026")
        self.assertEqual(appointment.state(SEPTEMBER_15), UPCOMING)

        # Nobody's account or reporting line was touched.
        sarah = fresh(self.sarah)
        self.assertEqual(sarah.roles, ["CCEO"])
        self.assertEqual(sarah.active_role, "CCEO")
        self.assertEqual(fresh(self.john).roles, ["Program Lead"])
        self.assertTrue(
            StaffSupervisorAssignment.objects.filter(
                supervisor=self.john_sp, supervisee=self.sarah_sp
            ).exists()
        )
        self.assertFalse(
            StaffSupervisorAssignment.objects.filter(supervisor=self.sarah_sp).exists()
        )
        # One account each, as before.
        self.assertEqual(User.objects.filter(name="Sarah Officer").count(), 1)

    def test_a_director_appoints_a_lead_of_their_country(self):
        appointment = self.appoint_peter()
        self.assertEqual(appointment.role_key, "acting_cd")
        self.assertEqual(appointment.acting_role, "CountryDirector")
        self.assertEqual(appointment.appointee_role, "Program Lead")
        self.assertEqual(appointment.seat_id, self.mary_sp.id)
        self.assertEqual(appointment.scope_type, "country")
        self.assertEqual(appointment.country, "Uganda")
        self.assertEqual(fresh(self.peter).roles, ["Program Lead"])

    def test_the_list_offers_only_who_may_be_appointed(self):
        self.assertEqual(
            {p.id for p in services.eligible_appointees(self.john)},
            {self.sarah_sp.id, self.david_sp.id, self.michael_sp.id},
        )
        self.assertEqual(
            {p.id for p in services.eligible_appointees(self.mary)},
            {self.john_sp.id, self.peter_sp.id},
        )
        for nobody in (self.sarah, self.hope):
            self.assertEqual(services.eligible_appointees(nobody), [])

    def test_the_confirmation_says_what_is_given_and_what_stays(self):
        with on_day(SEPTEMBER_15):
            pl = services.preview(
                self.john, appointee_staff_id=self.sarah_sp.id, month=OCTOBER
            )
            cd = services.preview(
                self.mary, appointee_staff_id=self.peter_sp.id, month=OCTOBER
            )
        self.assertEqual(
            pl["statement"],
            "Sarah will receive Acting PL operational access for your entire PL "
            "team, including your own operational scope, from October 1 through "
            "October 31. Your permanent PL role will remain unchanged.",
        )
        self.assertEqual(
            cd["statement"],
            "Peter will receive Acting CD operational access for the country "
            "from October 1 through October 31. Your permanent Country Director "
            "role will remain unchanged.",
        )
        self.assertEqual(pl["effective"], "October 1 – October 31, 2026")
        self.assertFalse(ActingAssignment.objects.exists())

    def test_the_grant_is_kept_as_it_stood(self):
        snapshot = self.appoint_sarah().grant_snapshot
        self.assertEqual(snapshot["policy"], "acting_pl")
        self.assertEqual(snapshot["seat"]["name"], "John Lead")
        self.assertEqual(
            {m["name"] for m in snapshot["seat_members"]},
            {"Sarah Officer", "David Officer", "Michael Officer"},
        )
        self.assertIn("fund_approvals", snapshot["withheld_pages"])
        self.assertIn("planning_monitor", snapshot["delegated_write_pages"])
        self.assertIn("fund_decision", snapshot["withheld_authorities"])

    def test_the_appointee_and_the_team_are_told(self):
        with self.captureOnCommitCallbacks(execute=True):
            appointment = self.appoint_sarah()
        told = Notification.objects.get(
            recipient_id=self.sarah.id, source_event_type="acting.appointed"
        )
        self.assertEqual(
            told.title, "You have been appointed Acting PL for October 2026."
        )
        for part in (
            "John Lead",
            "October 1 – October 31, 2026",
            "John Lead's PL team",
        ):
            self.assertIn(part, told.body)
        self.assertEqual(told.target_route, "/acting-leadership")
        self.assertEqual(told.context_id, appointment.id)
        team = set(
            Notification.objects.filter(
                source_event_type="acting.team_informed"
            ).values_list("recipient_id", flat=True)
        )
        self.assertEqual(team, {self.david.id, self.michael.id})


class AppointmentSecurityTests(ActingFixture):
    def _refused(self, who, staff_id, month=OCTOBER, error=Forbidden):
        with on_day(SEPTEMBER_15), self.assertRaises(error):
            services.appoint(fresh(who), appointee_staff_id=staff_id, month=month)
        self.assertFalse(ActingAssignment.objects.exists())

    def test_an_officer_appoints_nobody(self):
        self._refused(self.sarah, self.david_sp.id)  # another officer
        self._refused(self.sarah, self.peter_sp.id)  # an acting director

    def test_a_lead_cannot_appoint_an_acting_director(self):
        self._refused(self.john, self.peter_sp.id)

    def test_a_lead_cannot_appoint_outside_their_own_team(self):
        self._refused(self.john, self.agnes_sp.id)  # another Lead's officer
        self._refused(self.john, self.achieng_sp.id)  # another country's
        self._refused(self.john, self.john_sp.id)  # themself
        self._refused(self.john, self.mary_sp.id)  # their director

    def test_a_director_cannot_appoint_an_officer_or_another_countrys_lead(self):
        self._refused(self.mary, self.sarah_sp.id)  # a CCEO, directly
        self._refused(self.mary, self.otieno_sp.id)  # Kenya's Lead
        self._refused(self.mary, self.hope_sp.id)  # not a Lead at all
        self._refused(self.wanjiru, self.peter_sp.id)  # Uganda's Lead, from Kenya

    def test_hr_and_admin_read_and_appoint_nobody(self):
        admin = User.objects.create(
            id="act-admin",
            email="act-admin@edify.test",
            name="Ada Admin",
            roles=["Admin"],
            active_role="Admin",
        )
        self._refused(self.hope, self.sarah_sp.id)
        self._refused(admin, self.sarah_sp.id)

    def test_an_administrator_is_never_appointed(self):
        self.sarah.roles = ["CCEO", "HumanResources"]
        self.sarah.save(update_fields=["roles"])
        self.david.roles = ["Admin"]
        self.david.active_role = "Admin"
        self.david.save(update_fields=["roles", "active_role"])
        self.assertNotIn(
            self.david_sp.id, {p.id for p in services.eligible_appointees(self.john)}
        )
        self._refused(self.john, self.david_sp.id)

    def test_a_refused_attempt_is_on_the_audit_log(self):
        self._refused(self.john, self.agnes_sp.id)
        row = AuditLog.objects.filter(action="acting_assignment.refused").latest("seq")
        self.assertFalse(row.success)
        self.assertEqual(row.actor_id, self.john.id)

    def test_an_acting_leader_appoints_nobody(self):
        """Not as the acting role, and not in their own role's name either."""
        self.appoint_sarah()
        self.appoint_peter()
        sarah = self.acting(self.sarah)
        self.assertEqual(sarah.active_role, "Program Lead")
        self.assertIsNone(services.appointing_policy(sarah))
        with on_day(OCTOBER_15), self.assertRaises(Forbidden):
            services.appoint(sarah, appointee_staff_id=self.david_sp.id, month=NOVEMBER)
        # Peter is a Lead in his own right, but as Acting CD he appoints
        # neither an acting director nor, from that capacity, an acting lead.
        peter = self.acting(self.peter)
        self.assertEqual(peter.active_role, "CountryDirector")
        self.assertIsNone(services.appointing_policy(peter))
        with on_day(OCTOBER_15), self.assertRaises(Forbidden):
            services.appoint(peter, appointee_staff_id=self.john_sp.id, month=NOVEMBER)


class ConflictTests(ActingFixture):
    def test_one_acting_lead_per_team_and_month(self):
        self.appoint_sarah()
        with on_day(SEPTEMBER_15), self.assertRaises(ConflictError) as refused:
            services.appoint(
                self.john, appointee_staff_id=self.david_sp.id, month=OCTOBER
            )
        self.assertIn(
            "Sarah Officer is already Acting Program Lead", str(refused.exception)
        )
        # Another month is another appointment.
        with on_day(SEPTEMBER_15):
            services.appoint(
                self.john, appointee_staff_id=self.david_sp.id, month=NOVEMBER
            )

    def test_one_acting_appointment_per_person_and_month(self):
        """A Lead who is Acting CD for October is not also something else."""
        self.appoint_peter()
        self.peter.roles = ["Program Lead", "CCEO"]
        self.peter.save(update_fields=["roles"])
        StaffSupervisorAssignment.objects.create(
            supervisor=self.john_sp, supervisee=self.peter_sp
        )
        with on_day(SEPTEMBER_15), self.assertRaises((ConflictError, Forbidden)):
            services.appoint(
                self.john, appointee_staff_id=self.peter_sp.id, month=OCTOBER
            )
        self.assertEqual(ActingAssignment.objects.count(), 1)


class CancellingTests(ActingFixture):
    def test_the_appointing_lead_cancels_an_upcoming_appointment(self):
        appointment = self.appoint_sarah()
        with on_day(SEPTEMBER_15), self.captureOnCommitCallbacks(execute=True):
            services.cancel(self.john, appointment.id, reason="Plans changed")
        stored = ActingAssignment.objects.get(id=appointment.id)
        self.assertEqual(stored.state(OCTOBER_15), CANCELLED)
        self.assertEqual(stored.cancelled_by_id, self.john.id)
        self.assertEqual(stored.cancel_reason, "Plans changed")
        self.assertIsNotNone(stored.cancelled_at)
        self.assertIsNone(fresh(self.sarah).acting_until)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.sarah.id, source_event_type="acting.cancelled"
            ).exists()
        )

    def test_cancelling_an_active_appointment_stops_the_access_at_once(self):
        appointment = self.appoint_sarah()
        self.assertEqual(self.acting(self.sarah).active_role, "Program Lead")
        with on_day(OCTOBER_15):
            services.cancel(self.john, appointment.id)
        self.assertEqual(self.acting(self.sarah).active_role, "CCEO")
        # Kept, never deleted.
        self.assertTrue(ActingAssignment.objects.filter(id=appointment.id).exists())

    def test_a_director_and_an_admin_can_stop_an_acting_lead(self):
        admin = User.objects.create(
            id="act-admin2",
            email="act-admin2@edify.test",
            name="Ada Admin",
            roles=["Admin"],
            active_role="Admin",
        )
        for who in (self.mary, admin):
            appointment = self.appoint_sarah()
            with on_day(SEPTEMBER_15):
                services.cancel(fresh(who), appointment.id)

    def test_nobody_else_cancels_it(self):
        appointment = self.appoint_sarah()
        with on_day(SEPTEMBER_15):
            for stranger in (self.peter, self.wanjiru, self.otieno, self.agnes):
                with self.assertRaises(NotFoundError):
                    services.cancel(fresh(stranger), appointment.id)
            for onlooker in (self.sarah, self.hope):
                with self.assertRaises(Forbidden):
                    services.cancel(fresh(onlooker), appointment.id)
        self.assertEqual(
            ActingAssignment.objects.get(id=appointment.id).state(OCTOBER_15), ACTIVE
        )

    def test_an_acting_director_cannot_cancel_or_change_appointments(self):
        """Acting appointments are not delegated, a director's included."""
        self.appoint_peter()
        sarahs = self.appoint_sarah(month=NOVEMBER)
        peter = self.acting(self.peter)
        self.assertEqual(peter.active_role, "CountryDirector")
        # His reach is his own role's: another Lead's appointment is not
        # even his to see, and his director's is not his to cancel.
        with on_day(OCTOBER_15), self.assertRaises(NotFoundError):
            services.cancel(peter, sarahs.id)
        own = ActingAssignment.objects.get(appointee=self.peter)
        with on_day(OCTOBER_15), self.assertRaises(Forbidden):
            services.cancel(peter, own.id)
        self.assertFalse(services.may_manage(peter, sarahs))

    def test_what_has_ended_cannot_be_cancelled(self):
        appointment = self.appoint_sarah()
        with on_day(NOVEMBER_1), self.assertRaises(BadRequest):
            services.cancel(self.john, appointment.id)
        with on_day(SEPTEMBER_15):
            services.cancel(self.john, appointment.id)
            with self.assertRaises(BadRequest):
                services.cancel(self.john, appointment.id)

    def test_the_seat_and_the_person_are_free_again_after_a_cancellation(self):
        with on_day(OCTOBER_1):
            services.cancel(self.john, self.appoint_sarah().id)
            again = services.appoint(
                self.john, appointee_staff_id=self.david_sp.id, month=OCTOBER
            )
        self.assertEqual(again.state(OCTOBER_15), ACTIVE)
        self.assertEqual(ActingAssignment.objects.count(), 2)


class ReschedulingTests(ActingFixture):
    def test_an_upcoming_appointment_moves_and_keeps_where_it_was(self):
        appointment = self.appoint_sarah()
        with on_day(SEPTEMBER_15):
            changed = services.reschedule(self.john, appointment.id, month=NOVEMBER)
        self.assertEqual(changed.effective_label, "November 1 – November 30, 2026")
        self.assertEqual(
            (changed.revisions[0]["start_date"], changed.revisions[0]["end_date"]),
            ("2026-10-01", "2026-10-31"),
        )
        self.assertEqual(changed.revisions[0]["changed_by"], self.john.id)
        self.assertEqual(self.acting(self.sarah, OCTOBER_15).active_role, "CCEO")
        self.assertEqual(
            self.acting(self.sarah, NOVEMBER_1).active_role, "Program Lead"
        )
        updated = AuditLog.objects.filter(action="acting_assignment.updated").latest(
            "seq"
        )
        self.assertEqual(updated.payload["before"]["start_date"], "2026-10-01")
        self.assertEqual(updated.payload["after"]["start_date"], "2026-11-01")

    def test_an_active_appointment_is_never_edited(self):
        appointment = self.appoint_sarah()
        with on_day(OCTOBER_15), self.assertRaises(BadRequest):
            services.reschedule(self.john, appointment.id, month=NOVEMBER)
        stored = ActingAssignment.objects.get(id=appointment.id)
        self.assertEqual(stored.start_date.month, 10)
        self.assertEqual(stored.revisions, [])

    def test_only_the_appointing_leader_changes_it(self):
        appointment = self.appoint_sarah()
        with on_day(SEPTEMBER_15):
            with self.assertRaises(Forbidden):
                services.reschedule(self.mary, appointment.id, month=NOVEMBER)
            with self.assertRaises(NotFoundError):
                services.reschedule(self.peter, appointment.id, month=NOVEMBER)

    def test_it_cannot_move_onto_a_month_that_is_taken(self):
        self.appoint_sarah(month=OCTOBER)
        with on_day(SEPTEMBER_15):
            davids = services.appoint(
                self.john, appointee_staff_id=self.david_sp.id, month=NOVEMBER
            )
            with self.assertRaises(ConflictError):
                services.reschedule(self.john, davids.id, month=OCTOBER)


class AuditTrailTests(ActingFixture):
    def test_an_appointment_answers_every_question_an_auditor_asks(self):
        appointment = self.appoint_peter()
        row = AuditLog.objects.filter(
            action="acting_assignment.created", subject_id=appointment.id
        ).get()
        self.assertEqual(row.actor_id, self.mary.id)
        self.assertEqual(row.actor_role, "CountryDirector")
        payload = row.payload
        self.assertEqual(payload["appointed_by"]["name"], "Mary Director")
        self.assertEqual(payload["appointee"]["name"], "Peter Lead")
        self.assertEqual(payload["appointee"]["permanent_role"], "Program Lead")
        self.assertEqual(payload["acting_role"], "CountryDirector")
        self.assertEqual(payload["scope"], "Uganda")
        self.assertEqual(payload["month"], "October 2026")
        self.assertEqual(
            (payload["start_date"], payload["end_date"]), ("2026-10-01", "2026-10-31")
        )

    def test_the_record_is_sealed_into_the_hash_chain_when_it_commits(self):
        with self.captureOnCommitCallbacks(execute=True):
            appointment = self.appoint_peter()
        row = AuditLog.objects.filter(
            action="acting_assignment.created", subject_id=appointment.id
        ).get()
        self.assertIsNotNone(row.seq)
        self.assertIsNotNone(row.hash)

    def test_a_cancellation_is_recorded_with_who_when_and_why(self):
        appointment = self.appoint_sarah()
        with on_day(OCTOBER_15):
            services.cancel(self.john, appointment.id, reason="Returned early")
        row = AuditLog.objects.filter(
            action="acting_assignment.cancelled", subject_id=appointment.id
        ).get()
        self.assertEqual(row.actor_id, self.john.id)
        self.assertEqual(row.payload["reason"], "Returned early")
        self.assertEqual(row.payload["state_when_cancelled"], "active")
