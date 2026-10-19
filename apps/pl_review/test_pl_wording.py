"""Tables say PL where the Programme Lead verifies (owner, 2026-10-19).

"PLs are the ones to verify everything except their own is automatically
verified. So every table that says IA verify or IA verification should be
changed to PL" and "Only Partner work is verified by Impact Assessment (IA).
Staff work is verified by PL."

The statuses keep their stored names (``awaiting_ia_verification``,
``ia_verified``); what a reader sees says who verifies: the Programme Lead
for staff work, Impact Assessment for a partner's.
"""

from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase

from apps.activities.models import Activity


def _activity(status, delivery_type="staff"):
    return Activity(
        status=status, delivery_type=delivery_type, planned_date=date.today()
    )


class TheStatusSaysWhoVerifies(SimpleTestCase):
    def test_staff_work_says_pl(self):
        self.assertEqual(
            _activity("awaiting_ia_verification").get_status_display(),
            "Awaiting PL Verification",
        )
        self.assertEqual(_activity("ia_verified").get_status_display(), "PL Verified")

    def test_partner_work_says_ia(self):
        self.assertEqual(
            _activity("awaiting_ia_verification", "partner").get_status_display(),
            "Awaiting IA Verification",
        )
        self.assertEqual(
            _activity("ia_verified", "partner").get_status_display(), "IA Verified"
        )

    def test_other_statuses_are_unchanged(self):
        self.assertEqual(_activity("scheduled").get_status_display(), "Scheduled")


class ProfileRowsSayPl(SimpleTestCase):
    def test_a_staff_row_waiting_on_its_verifier_reads_pl_pending(self):
        from apps.activities.profile_activities import _status

        label, _tone = _status(_activity("awaiting_ia_verification"), date.today())
        self.assertEqual(label, "PL Pending")
        label, _tone = _status(
            _activity("awaiting_ia_verification", "partner"), date.today()
        )
        self.assertEqual(label, "IA Pending")
