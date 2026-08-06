"""Uploading the right document must actually satisfy the requirement.

A user reported: upload the visit form, enter the Salesforce ID, and still get

    Required evidence missing for this activity type: Visit Form.

They were right, and it was total. `infer_kind_from_upload` can only ever
return PDF or PHOTO — it says what shape a file is. Every requirement asks what
a document *is for*: visit form, attendance form, meeting minutes. The two
vocabularies never intersect, so for all 20 activity types carrying a
requirement the gate could not be satisfied by any upload at all.

3,224 tests were green while this shipped, because `submit_for_review` skips
the requirement check under test unless `strict_validation` is passed. These
tests pass it, which is the only way to exercise the gate people actually meet.
"""

from __future__ import annotations

from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.core.enums import EvidenceKind
from apps.evidence.requirements import REQUIRED_EVIDENCE, missing_evidence_kinds
from apps.evidence.services import infer_kind_from_upload, resolve_evidence_kind


class _Upload:
    def __init__(self, name, content_type=""):
        self.name = name
        self.content_type = content_type


class TheRequirementMustBeReachableTest(TestCase):
    """The defect, stated as a property of the two vocabularies."""

    def test_inference_alone_can_never_satisfy_any_requirement(self):
        """The bug in one assertion. Kept as a regression: if someone
        reconnects the upload straight to inference, this fails."""
        reachable = {
            infer_kind_from_upload(_Upload("f.pdf", "application/pdf")),
            infer_kind_from_upload(_Upload("f.jpg", "image/jpeg")),
        }
        unsatisfiable = [
            activity_type
            for activity_type, needed in REQUIRED_EVIDENCE.items()
            if not set(needed) & reachable
        ]
        self.assertEqual(
            len(unsatisfiable),
            len(REQUIRED_EVIDENCE),
            "inference now overlaps the requirement vocabulary; if that is "
            "deliberate, this test should be rewritten rather than deleted",
        )

    def test_the_resolver_fills_what_the_activity_is_asking_for(self):
        from apps.activities.models import Activity
        from apps.geography.models import District, Region
        from apps.schools.models import School

        region = Region.objects.create(name="Reach Region")
        district = District.objects.create(name="Reach District", region=region)
        school = School.objects.create(
            school_id="SCH-REACH-1",
            name="Reach Primary",
            region=region,
            district=district,
        )
        activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="completion_started",
            fy="2026",
            school=school,
            planned_date=date.today(),
            scheduled_date=date.today(),
        )

        resolved = resolve_evidence_kind(
            _Upload("visit_form.pdf", "application/pdf"), activity=activity
        )
        self.assertEqual(resolved, EvidenceKind.VISIT_FORM)

    def test_what_the_person_says_wins(self):
        resolved = resolve_evidence_kind(
            _Upload("scan.pdf", "application/pdf"),
            activity=None,
            asserted=EvidenceKind.ATTENDANCE_FORM,
        )
        self.assertEqual(resolved, EvidenceKind.ATTENDANCE_FORM)

    def test_an_invalid_assertion_is_ignored_rather_than_stored(self):
        resolved = resolve_evidence_kind(
            _Upload("scan.pdf", "application/pdf"),
            activity=None,
            asserted="not-a-real-kind",
        )
        self.assertEqual(resolved, EvidenceKind.PDF)

    def test_with_no_activity_and_no_assertion_it_falls_back_to_shape(self):
        self.assertEqual(
            resolve_evidence_kind(_Upload("photo.jpg", "image/jpeg")),
            EvidenceKind.PHOTO,
        )


class CompletionSucceedsEndToEndTest(TestCase):
    """The user's actual journey, with the gate switched on."""

    def setUp(self):
        from apps.accounts.models import StaffProfile, User
        from apps.activities.models import Activity
        from apps.geography.models import District, Region
        from apps.schools.models import School

        region = Region.objects.create(name="E2E Region")
        district = District.objects.create(name="E2E District", region=region)
        self.school = School.objects.create(
            school_id="SCH-E2E-1",
            name="E2E Primary",
            region=region,
            district=district,
        )
        self.user = User.objects.create(
            id="e2e-cceo",
            email="e2e@edify.org",
            name="E2E CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(
            id="e2e-sp", user=self.user, title="CCEO"
        )
        self.activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="completion_started",
            fy="2026",
            school=self.school,
            responsible_staff_id=self.staff.id,
            planned_date=date.today(),
            scheduled_date=date.today(),
        )

    def _upload(self, kind):
        from apps.evidence.services import record_upload

        return record_upload(
            principal=self.user,
            activity_id=self.activity.id,
            kind=kind,
            file_obj=SimpleUploadedFile(
                "visit_form.pdf", b"%PDF-1.4 visit", content_type="application/pdf"
            ),
        )

    def test_a_pdf_recorded_only_by_shape_leaves_the_requirement_unmet(self):
        """What the user hit."""
        self._upload(EvidenceKind.PDF)
        missing = missing_evidence_kinds(self.activity)
        self.assertEqual([m["kind"] for m in missing], [EvidenceKind.VISIT_FORM])

    def test_the_same_file_recorded_as_a_visit_form_satisfies_it(self):
        """What the fix changes: the document, not the file type."""
        self._upload(EvidenceKind.VISIT_FORM)
        self.assertEqual(missing_evidence_kinds(self.activity), [])

    def test_a_quarantined_upload_does_not_satisfy_the_requirement(self):
        from apps.evidence.models import EvidenceRecord

        self._upload(EvidenceKind.VISIT_FORM)
        EvidenceRecord.objects.filter(activity_id=self.activity.id).update(
            quarantined=True
        )
        self.assertEqual(
            [m["kind"] for m in missing_evidence_kinds(self.activity)],
            [EvidenceKind.VISIT_FORM],
        )


class EveryActivityTypeCanBeCompletedTest(TestCase):
    """The question this file exists to keep answering.

    The original report was about a school visit, but the cause was structural:
    the uploader spoke in file shapes and the requirement spoke in document
    purposes. That mismatch applied to every activity type at once — trainings
    could not record an attendance form, cluster meetings could not record
    minutes, core assessments could not record an assessment form.

    So this is data-driven over REQUIRED_EVIDENCE rather than a handful of
    hand-picked cases. A new activity type added to that map with a kind the
    upload path cannot produce fails here, on the day it is added, rather than
    when somebody in the field cannot close their work.
    """

    def _activity(self, activity_type, owner_staff_id=None):
        from apps.activities.models import Activity
        from apps.geography.models import District, Region
        from apps.schools.models import School

        region, _ = Region.objects.get_or_create(name="AllTypes Region")
        district, _ = District.objects.get_or_create(
            name="AllTypes District", region=region
        )
        school, _ = School.objects.get_or_create(
            school_id="SCH-ALLTYPES-1",
            defaults={
                "name": "AllTypes Primary",
                "region": region,
                "district": district,
            },
        )
        return Activity.objects.create(
            activity_type=activity_type,
            delivery_type="staff",
            status="completion_started",
            fy="2026",
            school=school,
            responsible_staff_id=owner_staff_id,
            planned_date=date.today(),
            scheduled_date=date.today(),
        )

    def test_a_document_upload_satisfies_every_declared_requirement(self):
        for activity_type, needed in REQUIRED_EVIDENCE.items():
            with self.subTest(activity_type):
                activity = self._activity(activity_type)
                resolved = resolve_evidence_kind(
                    _Upload("evidence.pdf", "application/pdf"), activity=activity
                )
                self.assertIn(
                    resolved,
                    needed,
                    f"a document uploaded to a {activity_type} records as "
                    f"{resolved!r}, which does not satisfy {needed}",
                )

    def test_the_requirement_clears_once_the_document_is_recorded(self):
        """Resolving the kind is only half of it — the gate must then pass."""
        from apps.evidence.services import record_upload
        from apps.accounts.models import StaffProfile, User

        user, _ = User.objects.get_or_create(
            id="alltypes-cceo",
            defaults={
                "email": "alltypes@edify.org",
                "name": "AllTypes CCEO",
                "roles": ["CCEO"],
                "active_role": "CCEO",
                "is_active": True,
            },
        )
        staff, _ = StaffProfile.objects.get_or_create(
            id="alltypes-sp", defaults={"user": user, "title": "CCEO"}
        )

        for activity_type in REQUIRED_EVIDENCE:
            with self.subTest(activity_type):
                activity = self._activity(activity_type, owner_staff_id=staff.id)
                record_upload(
                    principal=user,
                    activity_id=activity.id,
                    kind=resolve_evidence_kind(
                        _Upload("evidence.pdf", "application/pdf"), activity=activity
                    ),
                    file_obj=SimpleUploadedFile(
                        "evidence.pdf", b"%PDF-1.4", content_type="application/pdf"
                    ),
                )
                self.assertEqual(
                    missing_evidence_kinds(activity),
                    [],
                    f"{activity_type} still reports missing evidence after the "
                    "right document was uploaded",
                )

    def test_every_required_kind_is_a_real_evidence_kind(self):
        """A requirement naming a kind that does not exist could never be met,
        and would read as a typo nobody notices until completion fails."""
        valid = {choice for choice, _label in EvidenceKind.choices}
        for activity_type, needed in REQUIRED_EVIDENCE.items():
            with self.subTest(activity_type):
                self.assertEqual(set(needed) - valid, set())
