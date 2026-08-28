"""Journey 14 — Team Oversight and Send School to, walked end to end.

Journey 14 of the mandate's twenty-two: CCEO school appears under team, Not in
PL personal portfolio, Urgent school identified, PL sends school, CCEO accepts
and plans, Team Oversight updates, Ownership remains correct.

Two of its seven steps are stated as *negatives*, and they are the two this
platform has already got wrong once. SEC-01 — found and fixed earlier in this
audit — was a Programme Lead able to take ownership of a supervised CCEO's
school, because the edit drawer gated its write on the read helper. §7 draws
the distinction this journey exists to protect: a Programme Lead **sees** a
CCEO's school on oversight and **asks about it**; they do not own it and they
do not plan on it.

Delegation is exactly where that line is under most pressure. Sending an
urgent school to the CCEO who owns it is a supervisory act performed on a
record the supervisor may not write, so the interesting question is not
whether the send works — it is whether anything about the send moves the
school into the sender's own portfolio. This walks the delegation and then
asks the ownership question again on the other side of it.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School


def _person(uid, email, name, role):
    user = User.objects.create(
        id=uid,
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        is_active=True,
    )
    profile = StaffProfile.objects.create(
        user=user, staff_number=uid.upper(), country="Uganda", title=role
    )
    return user, profile


class TeamOversightJourneyTest(TestCase):
    """See it → don't own it → send it → they accept → still don't own it."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="TO Region")
        cls.district = District.objects.create(name="TO District", region=cls.region)
        cls.team_school = School.objects.create(
            school_id="TO-TEAM",
            name="TO Team School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.pl_own_school = School.objects.create(
            school_id="TO-OWN",
            name="TO PL Own School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.pl, cls.pl_sp = _person("to-pl", "to-pl@edify.org", "TO PL", "Program Lead")
        cls.cceo, cls.cceo_sp = _person(
            "to-cceo", "to-cceo@edify.org", "TO CCEO", "CCEO"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )
        # The CCEO owns the team school; the PL owns a different one of their
        # own, so "not in the PL's portfolio" cannot pass merely because the
        # PL's portfolio is empty.
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo_sp, school_id=cls.team_school.id
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.pl_sp, school_id=cls.pl_own_school.id
        )
        cls.fy = get_operational_fy()

    def _pl_scope(self):
        from apps.core.request_cache import begin, end
        from apps.core.scoping import resolve_user_scope

        begin()
        try:
            scope = resolve_user_scope(self.pl)
            return {
                "own": set(scope.own_school_ids),
                "team": set(scope.team_school_ids),
                "all": set(scope.school_ids),
            }
        finally:
            end()

    def _assert_sees_but_does_not_own(self, where: str):
        scope = self._pl_scope()
        self.assertIn(
            self.team_school.id,
            scope["team"],
            f"{where}: the supervised CCEO's school is not on the Programme "
            "Lead's team lens, so oversight cannot see it at all",
        )
        self.assertIn(
            self.team_school.id,
            scope["all"],
            f"{where}: the school is missing from the combined lens",
        )
        self.assertNotIn(
            self.team_school.id,
            scope["own"],
            f"{where}: the supervised CCEO's school is in the Programme "
            "Lead's PERSONAL portfolio. This is the SEC-01 shape — oversight "
            "became ownership.",
        )
        # The PL's genuine own school is still theirs, so the assertion above
        # is not passing because own_school_ids is simply empty.
        self.assertIn(
            self.pl_own_school.id,
            scope["own"],
            f"{where}: the Programme Lead lost their own school",
        )

    def test_delegating_an_urgent_school_never_transfers_its_ownership(self):
        from apps.planning.action_service import acknowledge, send_action
        from apps.planning.models import TeamAction
        from apps.planning.urgent_attention import resolve_urgent_issue

        # ── 1-2. Appears under team, absent from the personal portfolio ───
        self._assert_sees_but_does_not_own("before the send")

        # ── 3. Urgent school identified ───────────────────────────────────
        # Resolved by the platform's own rule, not asserted into existence:
        # the school has no confirmed SSA, so it is genuinely urgent.
        issue = resolve_urgent_issue(self.team_school, self.fy, [])
        self.assertTrue(
            issue.get("condition_key"),
            "the urgent issue carries no condition key, so it cannot be "
            "tracked and send_action would refuse it",
        )

        # ── 4. PL sends the school ────────────────────────────────────────
        action = send_action(
            sender=self.pl,
            school=self.team_school,
            issue=issue,
            fy=self.fy,
            recipient_staff=self.cceo_sp,
            note="Please complete the assessment this month.",
        )
        self.assertEqual(
            action.recipient_id,
            self.cceo.id,
            "the school was sent to somebody other than the CCEO who owns it",
        )

        # ── 5. CCEO accepts ───────────────────────────────────────────────
        acknowledge(action, self.cceo)
        action.refresh_from_db()
        self.assertEqual(action.state, "acknowledged")

        # ── 6. Team Oversight updates ─────────────────────────────────────
        self.assertTrue(
            TeamAction.objects.filter(
                school_id=self.team_school.id, condition_key=issue["condition_key"]
            ).exists(),
            "the delegation left no trace against the school, so oversight "
            "cannot show that it was actioned",
        )

        # ── 7. Ownership remains correct ──────────────────────────────────
        # The question the whole journey exists to ask, asked again on the
        # far side of the delegation.
        self._assert_sees_but_does_not_own("after the send and acceptance")
        self.assertTrue(
            StaffSchoolAssignment.objects.filter(
                staff=self.cceo_sp, school_id=self.team_school.id
            ).exists(),
            "the CCEO no longer holds the school they were asked to act on",
        )
        self.assertFalse(
            StaffSchoolAssignment.objects.filter(
                staff=self.pl_sp, school_id=self.team_school.id
            ).exists(),
            "delegating the school assigned it to the Programme Lead",
        )

        self.client.force_login(self.pl)
        response = self.client.get("/team-planning-oversight/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Team Oversight")

    def test_the_supervisor_still_cannot_write_the_school_they_delegated(self):
        """SEC-01, asked at the moment it is most tempting to allow.

        Having just sent an urgent instruction about a school, a Programme
        Lead is exactly the person a permissive rule would let 'just fix it'.
        """
        from apps.core.exceptions import Forbidden
        from apps.core.scoping import assert_may_write_school
        from apps.planning.action_service import send_action
        from apps.planning.urgent_attention import resolve_urgent_issue

        issue = resolve_urgent_issue(self.team_school, self.fy, [])
        send_action(
            sender=self.pl,
            school=self.team_school,
            issue=issue,
            fy=self.fy,
            recipient_staff=self.cceo_sp,
        )

        with self.assertRaises(Forbidden):
            assert_may_write_school(self.pl, self.team_school, action="edit")

        # The owner is unaffected — a narrowing rule that also blocks the
        # person who is supposed to act would be its own defect.
        assert_may_write_school(self.cceo, self.team_school, action="edit")
