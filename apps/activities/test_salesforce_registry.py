"""2026-07-15 preventive-verification mandate: Activity Salesforce IDs are
validated (TS- for training, SVE- for visits), normalized, and reserved
atomically at entry — duplicates are blocked before an activity can enter
the IA verification queue, not merely detected after the fact.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, ActivitySalesforceReference
from apps.activities.salesforce import (
    ENTRY_SOURCE_STAFF_SELF,
    DuplicateSalesforceId,
    is_valid_new_entry,
    is_valid_salesforce_id,
    normalize_salesforce_id,
    reserve_salesforce_id,
)
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


class FormatValidationTest(TestCase):
    def test_training_id_requires_ts_prefix(self):
        self.assertTrue(is_valid_new_entry("TS-123456", "training"))
        self.assertFalse(is_valid_new_entry("SVE-123456", "training"))
        self.assertFalse(is_valid_new_entry("SV-123456", "training"))

    def test_visit_id_requires_sve_prefix(self):
        self.assertTrue(is_valid_new_entry("SVE-123456", "visit"))
        self.assertFalse(is_valid_new_entry("TS-123456", "visit"))

    def test_legacy_bare_sv_prefix_rejected_for_new_entry_but_valid_for_reads(self):
        self.assertFalse(is_valid_new_entry("SV-123456", "visit"))
        self.assertTrue(is_valid_salesforce_id("SV-123456", "visit"))

    def test_id_is_normalized(self):
        self.assertEqual(normalize_salesforce_id("  sve - abc123 "), "SVE-ABC123")
        self.assertEqual(normalize_salesforce_id("ts-abc​123"), "TS-ABC123")

    def test_invalid_prefix_is_rejected(self):
        self.assertFalse(is_valid_new_entry("XX-123456", "visit"))
        self.assertFalse(is_valid_new_entry("", "visit"))


class ReservationBaseTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="SF Region")
        district = District.objects.create(name="SF District", region=region)
        self.school = School.objects.create(
            school_id="SF-SCH", name="SF School", region=region, district=district
        )
        self.cceo = User.objects.create_user(
            email="cceo@sf.org",
            name="Sf CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.cceo_staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")

    def _make_activity(self, activity_type="school_visit"):
        # _assert_in_scope's CCEO branch matches on StaffProfile.id, not
        # User.id — a known responsible_staff_id identity split in this
        # codebase (see the accountability-flow tests for the same pattern).
        return Activity.objects.create(
            school=self.school,
            activity_type=activity_type,
            delivery_type="staff",
            status="in_progress",
            responsible_staff_id=self.cceo_staff.id,
            fy="2026",
            quarter="Q3",
            planned_date=date(2026, 7, 15),
        )


class DuplicatePreventionTest(ReservationBaseTest):
    def test_duplicate_salesforce_id_blocked_at_entry(self):
        a1 = self._make_activity()
        a2 = self._make_activity()
        reserve_salesforce_id(
            activity=a1,
            raw_value="SVE-DUP-1",
            kind="visit",
            principal=self.cceo,
            entry_source=ENTRY_SOURCE_STAFF_SELF,
        )
        with self.assertRaises(DuplicateSalesforceId):
            reserve_salesforce_id(
                activity=a2,
                raw_value="SVE-DUP-1",
                kind="visit",
                principal=self.cceo,
                entry_source=ENTRY_SOURCE_STAFF_SELF,
            )
        a2.refresh_from_db()
        self.assertIsNone(a2.salesforce_activity_id)

    def test_duplicate_after_normalization_blocked(self):
        a1 = self._make_activity()
        a2 = self._make_activity()
        reserve_salesforce_id(
            activity=a1,
            raw_value="SVE-DUP-2",
            kind="visit",
            principal=self.cceo,
            entry_source=ENTRY_SOURCE_STAFF_SELF,
        )
        with self.assertRaises(DuplicateSalesforceId):
            reserve_salesforce_id(
                activity=a2,
                raw_value="  sve - dup - 2 ",
                kind="visit",
                principal=self.cceo,
                entry_source=ENTRY_SOURCE_STAFF_SELF,
            )

    def test_resubmitting_same_activitys_own_value_is_idempotent(self):
        a1 = self._make_activity()
        reserve_salesforce_id(
            activity=a1,
            raw_value="SVE-IDEMP-1",
            kind="visit",
            principal=self.cceo,
            entry_source=ENTRY_SOURCE_STAFF_SELF,
        )
        # Re-submitting the SAME activity's own value must not raise.
        reserve_salesforce_id(
            activity=a1,
            raw_value="SVE-IDEMP-1",
            kind="visit",
            principal=self.cceo,
            entry_source=ENTRY_SOURCE_STAFF_SELF,
        )
        self.assertEqual(
            ActivitySalesforceReference.objects.filter(
                normalized_value="SVE-IDEMP-1"
            ).count(),
            1,
        )

    def test_invalid_format_rejected_before_reservation(self):
        a1 = self._make_activity()
        with self.assertRaises(BadRequest):
            reserve_salesforce_id(
                activity=a1,
                raw_value="not-a-real-id",
                kind="visit",
                principal=self.cceo,
                entry_source=ENTRY_SOURCE_STAFF_SELF,
            )
        self.assertFalse(
            ActivitySalesforceReference.objects.filter(activity=a1).exists()
        )

    def test_reference_records_entry_metadata(self):
        a1 = self._make_activity()
        ref = reserve_salesforce_id(
            activity=a1,
            raw_value="sve-meta-1",
            kind="visit",
            principal=self.cceo,
            entry_source=ENTRY_SOURCE_STAFF_SELF,
        )
        self.assertEqual(ref.raw_value, "sve-meta-1")
        self.assertEqual(ref.normalized_value, "SVE-META-1")
        self.assertEqual(ref.entry_source, ENTRY_SOURCE_STAFF_SELF)
        self.assertEqual(ref.entered_by, self.cceo.user_id)
        self.assertIsNotNone(ref.entered_at)


class CompleteFlowSalesforceIdTest(ReservationBaseTest):
    """Exercises the real apps.activities.services.complete() path — the
    live entry point My Plan and the DRF API both call."""

    def _evidence(self, activity):
        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.create(
            activity=activity, kind="photo", uri="p.jpg", uploaded_by=self.cceo.id
        )

    def test_staff_activity_enters_ia_with_evidence_and_id(self):
        from apps.activities.services import complete

        a = self._make_activity()
        self._evidence(a)
        # A non-CCEO principal (e.g. IA) routes straight to IA.
        ia = User.objects.create_user(
            email="ia@sf.org",
            name="Sf IA",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="x",
            is_active=True,
        )
        a.responsible_staff_id = ia.id
        a.save(update_fields=["responsible_staff_id"])
        StaffProfile.objects.create(user=ia, title="IA")

        result = complete(a.id, {"salesforceId": "SVE-COMPLETE-1"}, ia)
        self.assertEqual(result["status"], "awaiting_ia_verification")
        a.refresh_from_db()
        self.assertEqual(a.salesforce_activity_id, "SVE-COMPLETE-1")

    def test_activity_without_salesforce_id_stays_out_of_ia(self):
        from apps.activities.services import complete

        a = self._make_activity()
        self._evidence(a)
        with self.assertRaises(BadRequest):
            complete(a.id, {"salesforceId": ""}, self.cceo)
        a.refresh_from_db()
        self.assertNotEqual(a.status, "awaiting_ia_verification")
        self.assertNotEqual(a.status, "submitted_to_pl")

    def test_duplicate_id_blocked_via_complete(self):
        from apps.activities.services import complete

        a1 = self._make_activity()
        a2 = self._make_activity()
        self._evidence(a1)
        self._evidence(a2)
        complete(a1.id, {"salesforceId": "SVE-DUP-COMPLETE"}, self.cceo)

        with self.assertRaises(DuplicateSalesforceId):
            complete(a2.id, {"salesforceId": "SVE-DUP-COMPLETE"}, self.cceo)
        a2.refresh_from_db()
        self.assertIsNone(a2.salesforce_activity_id)
        self.assertNotIn(a2.status, ("submitted_to_pl", "awaiting_ia_verification"))


class DuplicateApiConflictTest(ReservationBaseTest):
    def test_duplicate_api_returns_conflict(self):
        a1 = self._make_activity()
        a2 = self._make_activity()
        self._as = None
        self.client.force_login(self.cceo)

        from apps.evidence.models import EvidenceRecord

        for act in (a1, a2):
            EvidenceRecord.objects.create(
                activity=act, kind="photo", uri="p.jpg", uploaded_by=self.cceo.id
            )

        r1 = self.client.post(
            f"/api/activities/{a1.id}/complete",
            {"salesforceId": "SVE-CONFLICT-1"},
            content_type="application/json",
        )
        self.assertEqual(r1.status_code, 200, r1.content)

        r2 = self.client.post(
            f"/api/activities/{a2.id}/complete",
            {"salesforceId": "SVE-CONFLICT-1"},
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 409, r2.content)
