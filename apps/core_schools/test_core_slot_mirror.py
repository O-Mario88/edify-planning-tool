"""What the Activity → CoreActivitySlot mirror has to carry across.

`Activity.save()` (apps.activities.models) is the real, reachable completion
path for a core package slot — `resync_plan_completion`'s docstring says so,
and slot_action's own "complete" branch is DRF-only. But the mirror copied
only `status` and `scheduled_for`, while the "complete" branch it stands in
for also records the Activity SF ID and the evidence URI, and REFUSES to
complete without them.

So a slot completed the way slots are actually completed arrived done with
`salesforce_id` and `evidence_uri` still null, and the two System Health
ratchets that count exactly that — coreVerifiedSlotsMissingEvidence and
coreVerifiedSlotsMissingSfId — alarmed for ever on correctly-completed work.
Both facts already exist on the Activity being mirrored.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.activities.models import Activity
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id, cslot_id
from apps.core_schools.services import create_package_slots
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.schools.models import School


class CoreSlotMirrorTest(TestCase):
    def setUp(self):
        from apps.core.fy import get_operational_fy

        self.fy = get_operational_fy()
        self.region = Region.objects.create(name="Mirror Region")
        self.district = District.objects.create(
            name="Mirror District", region=self.region
        )
        self.school = School.objects.create(
            school_id="MIR-1",
            name="Mirror Primary",
            school_type="core",
            region=self.region,
            district=self.district,
        )
        self.plan = CorePlan.objects.create(
            id=cplan_id("MIR-1", fy=self.fy),
            school_id="MIR-1",
            fy=self.fy,
            status="Active",
        )
        create_package_slots(self.plan, "MIR-1", ["leadership"])
        self.slot = CoreActivitySlot.objects.get(
            id=cslot_id("MIR-1", "v", 1, fy=self.fy)
        )

    def _linked_activity(self, **overrides) -> Activity:
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=date.today() - timedelta(days=7),
            status="scheduled",
            **overrides,
        )
        self.slot.activity_id = activity.id
        self.slot.save(update_fields=["activity_id", "updated_at"])
        return activity

    def _close(self, activity: Activity, sf_id: str = "SF-MIRROR-1") -> None:
        activity.salesforce_activity_id = sf_id
        activity.status = "closed"
        activity.save()

    def _health(self) -> dict:
        from apps.system_health.services import _workflow_issues

        return _workflow_issues()

    def test_completion_carries_the_sf_id_and_evidence_onto_the_slot(self):
        activity = self._linked_activity()
        EvidenceRecord.objects.create(
            activity=activity,
            kind="visit_form",
            uri="core/MIR-1/visit-1.pdf",
            uploaded_by="u-mirror",
        )

        self._close(activity)

        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, "closed")
        self.assertEqual(self.slot.salesforce_id, "SF-MIRROR-1")
        self.assertEqual(self.slot.evidence_uri, "core/MIR-1/visit-1.pdf")

    def test_a_correctly_completed_slot_raises_no_health_alarm(self):
        activity = self._linked_activity()
        EvidenceRecord.objects.create(
            activity=activity,
            kind="visit_form",
            uri="core/MIR-1/visit-1.pdf",
            uploaded_by="u-mirror",
        )

        self._close(activity)

        issues = self._health()
        self.assertEqual(issues["coreVerifiedSlotsMissingSfId"], 0)
        self.assertEqual(issues["coreVerifiedSlotsMissingEvidence"], 0)

    def test_a_slot_completed_without_evidence_still_alarms(self):
        """The control: the ratchet must keep firing on work that really is
        missing its evidence, or copying the fields proves nothing."""
        activity = self._linked_activity()

        self._close(activity)

        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, "closed")
        self.assertIsNone(self.slot.evidence_uri)
        issues = self._health()
        self.assertEqual(issues["coreVerifiedSlotsMissingEvidence"], 1)

    def test_quarantined_evidence_is_not_mirrored_as_evidence(self):
        """A quarantined file is not evidence anywhere else in the app
        (see apps.activities.services._partner_evidence_exists)."""
        activity = self._linked_activity()
        EvidenceRecord.objects.create(
            activity=activity,
            kind="visit_form",
            uri="core/MIR-1/infected.pdf",
            uploaded_by="u-mirror",
            quarantined=True,
        )

        self._close(activity)

        self.slot.refresh_from_db()
        self.assertIsNone(self.slot.evidence_uri)

    def test_the_mirror_never_blanks_a_value_the_slot_already_holds(self):
        """Reschedules and re-saves run the mirror again; an Activity that has
        not been given an SF ID yet must not wipe one the slot already has."""
        self.slot.salesforce_id = "SF-EXISTING"
        self.slot.evidence_uri = "core/MIR-1/already-there.pdf"
        self.slot.save(update_fields=["salesforce_id", "evidence_uri", "updated_at"])
        activity = self._linked_activity()

        activity.status = "in_progress"
        activity.save()

        self.slot.refresh_from_db()
        self.assertEqual(self.slot.status, "in_progress")
        self.assertEqual(self.slot.salesforce_id, "SF-EXISTING")
        self.assertEqual(self.slot.evidence_uri, "core/MIR-1/already-there.pdf")
