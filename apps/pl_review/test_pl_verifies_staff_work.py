"""Staff work is verified by the Programme Lead; only partner work by Impact
Assessment (owner, 2026-10-19).

"PLs are the ones to verify everything except their own is automatically
verified" and, asked about the rest: "Only Partner work is verified by Impact
Assessment (IA). Staff work is verified by PL."

Until now a Programme Lead verified CCEO work and their own, and any other
staff member's work (a Project Coordinator's, a Business Transformation
officer's) went to IA. Now the lead who supervises that staff member
verifies it. Someone no Programme Lead supervises has no lead to send it to,
so IA keeps their work rather than it waiting on nobody.

Pinned here:

  1. A coordinator a lead supervises: completion goes to the lead, on the
     lead's queue, off IA's.
  2. A coordinator no lead supervises: IA, as before.
  3. Partner work: IA, whoever supervises its monitor.
"""

from __future__ import annotations

from apps.accounts.models import StaffSupervisorAssignment
from apps.activities.services import complete
from apps.core.rbac import EdifyRole
from apps.pl_review import services
from apps.pl_review.test_completion_reviews import _staff
from apps.pl_review.test_pl_approves import _Fixture


class StaffWorkGoesToItsLead(_Fixture):
    def setUp(self):
        super().setUp()
        self.coord_user, self.coord = _staff(
            "pv-coord@t.test", "Pat Coordinator", EdifyRole.PROJECT_COORDINATOR
        )

    def _supervised(self):
        StaffSupervisorAssignment.objects.create(
            supervisee=self.coord, supervisor=self.pl
        )

    def test_a_supervised_coordinator_s_work_goes_to_the_lead(self):
        self._supervised()
        work = self._started(self.coord.id)
        self.assertTrue(services.lead_verifies(work))
        complete(work.id, {"salesforceId": "SVE-9301"}, self.coord_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "submitted_to_pl")
        queued = {row["id"] for row in services.queue(self.pl_user)}
        self.assertIn(work.id, queued)

    def test_it_is_off_the_ia_queue(self):
        from apps.activities.models import Activity

        self._supervised()
        work = self._started(self.coord.id, status="awaiting_ia_verification")
        lead_work = Activity.objects.filter(services.lead_verified_q())
        self.assertIn(work.id, set(lead_work.values_list("id", flat=True)))

    def test_a_coordinator_no_lead_supervises_stays_with_ia(self):
        work = self._started(self.coord.id)
        self.assertFalse(services.lead_verifies(work))
        complete(work.id, {"salesforceId": "SVE-9302"}, self.coord_user)
        work.refresh_from_db()
        self.assertEqual(work.status, "awaiting_ia_verification")

    def test_partner_work_stays_with_ia(self):
        self._supervised()
        work = self._started(
            None, delivery_type="partner", monitored_by_staff_id=self.coord.id
        )
        self.assertFalse(services.lead_verifies(work))
