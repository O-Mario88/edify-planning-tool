"""Demo Flow 4 + 6 coverage: partner workflow + cluster training + DOCX evidence.

Like the authenticated-workflow smoke test, every record lives in the isolated
Django test database; the persistent/local DB keeps its honest empty-state
behaviour. These two flows close the demo-readiness verification:

  • Flow 4 — staff assigns a school visit to a partner → the partner sees it in
            their queue → partner schedules → partner uploads evidence → staff
            reviews (accepts) → staff enters the SV- Activity Code → the activity
            leaves the partner's queue.
  • Flow 6 — staff schedules cluster training (only through a cluster, with an
            exact date) → a cost line is created → the activity shows in My Plan
            → completion requires attendance + a TS- training code.

DOCX→PDF evidence conversion is also exercised: a DOCX upload is recorded, and
the inline-view service reports the correct preview state (ready when
LibreOffice is present, otherwise an honest `failed`/`pending` — never a silent
404). The pipeline degrades gracefully; the test asserts the contract, not the
external converter's availability.
"""

from __future__ import annotations

import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import ActivityScheduleCostLine
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner
from apps.schools.models import School


INTERVENTION_SCORES = [
    {"intervention": "teaching_environment", "score": 7},
    {"intervention": "financial_health", "score": 6},
    {"intervention": "christlike_behaviour", "score": 8},
    {"intervention": "exposure_to_word_of_god", "score": 7},
    {"intervention": "government_requirement", "score": 5},
    {"intervention": "leadership", "score": 6},
    {"intervention": "enrolment", "score": 4},
    {"intervention": "learning_environment", "score": 7},
]


@override_settings(EVIDENCE_STORAGE_DIR=tempfile.mkdtemp(prefix="edify-evidence-flow-"))
class PartnerAndClusterFlowTest(APITestCase):
    """Proves Demo Flows 4 + 6 (and DOCX evidence) against authenticated API calls."""

    def setUp(self):
        # Partner and cluster work is costed work; establish the CD-published
        # catalogue required by the real scheduling API before testing flow.
        CostCatalogue.objects.get_or_create(
            fy=get_operational_fy(),
            version=1,
            defaults={"label": "Partner and cluster flow test catalogue"},
        )[0]
        self.region = Region.objects.create(name="Flow Region")
        self.district = District.objects.create(
            name="Flow District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Flow SubCounty", district=self.district
        )

        self.ia = self._user("ia@flow.test", EdifyRole.IMPACT_ASSESSMENT.value)
        self.cceo = self._user("cceo@flow.test", EdifyRole.CCEO.value)
        self.pl = self._user("pl@flow.test", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.cceo_staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.pl_staff = StaffProfile.objects.create(user=self.pl, title="PL")
        # The PL reviews this CCEO's completions, so the supervision link the
        # workflow depends on has to exist. Without it the fixture modelled a
        # PL reviewing a stranger's work — which the review queue now refuses.
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_staff, supervisor=self.pl_staff
        )

        # Cost catalogue (reference data) — staff visit + partner lump sum +
        # the fixed three-item cluster-training recipe.
        CostSetting.objects.get_or_create(
            key="staff_visit_transport_primary",
            defaults={"label": "Transport", "unit_cost": 10000},
        )[0]
        CostSetting.objects.get_or_create(
            key="lunch", defaults={"label": "Lunch", "unit_cost": 5000}
        )[0]
        CostSetting.objects.get_or_create(
            key="partner_visit_lump_sum",
            defaults={"label": "Partner Visit", "unit_cost": 35000},
        )[0]
        CostSetting.objects.get_or_create(
            key="group_training_facilitation_fee",
            defaults={"label": "Facilitation fee", "unit_cost": 50000},
        )[0]
        CostSetting.objects.get_or_create(
            key="group_training_venue_cost",
            defaults={"label": "Venue fee", "unit_cost": 30000},
        )[0]
        CostSetting.objects.get_or_create(
            key="group_training_participant_meal_cost_per_head",
            defaults={"label": "Participant meals", "unit_cost": 5000},
        )[0]

    # ── Demo Flow 4: partner workflow ────────────────────────────────────────
    def test_assign_to_partner_then_partner_schedules_and_uploads_evidence(self):
        school = self._school("FLOW-PARTNER-1")
        StaffSchoolAssignment.objects.create(staff=self.cceo_staff, school_id=school.id)
        self._ssa(school)

        # A partner field-officer user linked to a Partner record (created first
        # so the staff assignment can reference the real partner id).
        partner_user = self._user(
            "partner@flow.test", EdifyRole.PARTNER_FIELD_OFFICER.value
        )
        partner = Partner.objects.create(
            name="Flow Partner Org",
            user=partner_user,
            active_status=True,
            contract_status="active",
            source="local_test_upload",
        )

        self._as(self.cceo)
        # Staff assigns the visit to a partner (deliveryType=partner).
        assigned = self._post(
            "/api/planning/assign-school-visit-to-partner",
            {
                "schoolId": school.school_id,
                # 2026-07-13 is a Monday — 2026-07-12 (Sunday) previously
                # slipped through here because partner-delivered activities
                # had no responsible_staff_id and skipped the REG-02 gate
                # entirely; that gap is now closed (create() always checks),
                # so this fixture must use a schedulable date.
                "scheduledDate": "2026-07-13T09:00:00+03:00",
                "plannedMonth": 7,
                "plannedWeek": 2,
                "purposeIntervention": "enrolment",
                "assignedPartnerId": partner.id,
            },
            201,
        )
        self.assertEqual(assigned["status"], "assigned_to_partner")
        self.assertEqual(assigned["deliveryType"], "partner")
        activity_id = assigned["id"]

        # Partner sees the assigned activity in their queue.
        self._as(partner_user)
        queue = self._get("/api/partners/me/activities", 200)
        self.assertTrue(any(row["id"] == activity_id for row in queue))

        # Partner self-schedules the activity.
        scheduled = self._post(
            f"/api/partners/me/activities/{activity_id}/schedule",
            {"scheduledDate": "2026-07-14T09:00:00+03:00"},
            200,
        )
        self.assertEqual(scheduled["status"], "partner_scheduled")

        # Partner unlocks completion + uploads evidence.
        self._post(f"/api/activities/{activity_id}/start-completion", {}, 200)
        evidence = self._upload_evidence(activity_id)

        # Assigning staff reviews (accepts) the partner evidence.
        self._as(self.cceo)
        reviewed = self._post(
            f"/api/evidence/{evidence['id']}/review", {"action": "accept"}, 200
        )
        self.assertEqual(reviewed["status"], "accepted")

        # Staff (CCEO) enters the SVE- Activity Code and submits completion. A CCEO
        # completion routes to PL (CCEO→PL→IA), so the next status is submitted_to_pl.
        completed = self._post(
            f"/api/activities/{activity_id}/complete",
            {"salesforceId": "SVE-FLOW4"},
            200,
        )
        self.assertEqual(completed["status"], "submitted_to_pl")
        # Evidence had to be accepted before the partner submission was allowed.
        self.assertEqual(completed["evidenceStatus"], "accepted")

        # PL confirms → IA handoff.
        self._as(self.pl)
        confirmed = self._post(f"/api/pl/review-queue/{activity_id}/confirm", {}, 200)
        self.assertEqual(confirmed["status"], "awaiting_ia_verification")

        # Activity no longer in the partner queue (handed off past the partner).
        self._as(partner_user)
        queue_after = self._get("/api/partners/me/activities", 200)
        self.assertFalse(any(row["id"] == activity_id for row in queue_after))

    # ── Demo Flow 6: cluster training + DOCX evidence ────────────────────────
    def test_cluster_training_requires_cluster_and_attendance_and_ts_code(self):
        school = self._school("FLOW-CLUSTER-1")
        StaffSchoolAssignment.objects.create(staff=self.cceo_staff, school_id=school.id)
        self._ssa(school)

        self._as(self.cceo)
        cluster = self._post(
            "/api/clusters/from-school",
            {
                "schoolId": school.school_id,
                "name": "Flow Cluster",
                "clusterType": "mixed",
            },
            201,
        )
        # Link the school to the cluster (school.cluster_id) so the CCEO's scope
        # covers the cluster they're scheduling training through.
        self._post(
            "/api/clusters/assign",
            {"schoolId": school.school_id, "clusterId": cluster["id"]},
            200,
        )

        # Schedule through the cluster, with an exact date + participants.
        scheduled = self._post(
            "/api/planning/schedule-cluster-training",
            {
                "clusterId": cluster["id"],
                "scheduledDate": "2026-07-20T09:00:00+03:00",
                "plannedMonth": 7,
                "expectedParticipants": 12,
                "purposeIntervention": "leadership",
            },
            201,
        )
        self.assertEqual(scheduled["status"], "scheduled")
        self.assertEqual(scheduled["activityType"], "cluster_training")
        # Cost was created from the catalogue — no activity without cost.
        self.assertGreater(scheduled["estCostCents"], 0)
        self.assertFalse(scheduled["costMissing"])
        activity_id = scheduled["id"]
        self.assertGreater(
            ActivityScheduleCostLine.objects.filter(activity_id=activity_id).count(), 0
        )

        # My Plan shows the training.
        my_plan = self._get("/api/my-plan?fy=2026&period=month&month=7", 200)
        self.assertTrue(any(item["id"] == activity_id for item in my_plan["items"]))

        # Completion unlocks; upload a DOCX evidence file.
        self._post(f"/api/activities/{activity_id}/start-completion", {}, 200)
        docx = self._upload_docx(activity_id)
        record = EvidenceRecord.objects.get(id=docx["id"])
        self.assertEqual(record.file_extension, ".docx")

        # DOCX inline-view contract: ready if LibreOffice converts, else an honest
        # pending/failed — never a 500 or a silent 404.
        preview = self._post(f"/api/evidence/{docx['id']}/prepare-view", {}, 200)
        self.assertIn(preview["previewStatus"], ("ready", "pending", "failed"))
        if preview["previewStatus"] == "ready":
            self.assertEqual(preview["viewKind"], "pdf_rendition")

        # Completion requires attendance + a TS- code (training prefix).
        no_attendance = self.client.post(
            f"/api/activities/{activity_id}/complete",
            {"salesforceId": "TS-FLOW6"},
            format="json",
        )
        self.assertEqual(no_attendance.status_code, 400, no_attendance.content)
        completed = self._post(
            f"/api/activities/{activity_id}/complete",
            {"salesforceId": "TS-FLOW6", "teachersAttended": 8, "leadersAttended": 4},
            200,
        )
        self.assertEqual(completed["status"], "submitted_to_pl")
        self.assertEqual(completed["salesforceActivityType"], "training")

    # ── helpers ──────────────────────────────────────────────────────────────
    def _user(self, email: str, role: str) -> User:
        return User.objects.create_user(
            email=email,
            name=email.split("@")[0].title(),
            roles=[role],
            active_role=role,
            password="not-used",
            is_active=True,
        )

    def _school(self, school_id: str) -> School:
        self._as(self.ia)
        upload = self._post(
            "/api/schools/bulk",
            {
                "schools": [
                    {
                        "schoolId": school_id,
                        "name": f"{school_id} Primary",
                        "regionId": self.region.id,
                        "districtId": self.district.id,
                        "subCountyId": self.sub_county.id,
                        "schoolType": "client",
                        "enrollment": 250,
                    }
                ]
            },
            201,
        )
        self.assertEqual(upload["accepted"], 1)
        return School.objects.get(school_id=school_id)

    def _ssa(self, school: School) -> None:
        # IA uploads the SSA so planning unlocks.
        self._as(self.ia)
        self._post(
            "/api/ssa",
            {
                "schoolId": school.school_id,
                "dateOfSsa": "2026-07-01T09:00:00+03:00",
                "scores": INTERVENTION_SCORES,
            },
            201,
        )
        self._as(self.cceo)

    def _as(self, user: User) -> None:
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}"
        )

    def _get(self, path: str, expected: int):
        response = self.client.get(path)
        self.assertEqual(response.status_code, expected, response.content)
        return response.json()

    def _post(self, path: str, data: dict, expected: int):
        response = self.client.post(path, data, format="json")
        self.assertEqual(response.status_code, expected, response.content)
        return response.json()

    def _upload_evidence(self, activity_id: str) -> dict:
        response = self.client.post(
            "/api/evidence/upload",
            {
                "activityId": activity_id,
                "kind": "visit_form",
                "file": SimpleUploadedFile(
                    "visit-form.pdf",
                    b"%PDF-1.4\n% partner evidence\n",
                    content_type="application/pdf",
                ),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def _upload_docx(self, activity_id: str) -> dict:
        # A minimal valid .docx is a ZIP (PK signature); the upload validator
        # sniffs the magic bytes. We hand-craft a tiny ZIP container.
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/></Types>',
            )
            zf.writestr(
                "_rels/.rels",
                '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
            )
        response = self.client.post(
            "/api/evidence/upload",
            {
                "activityId": activity_id,
                "kind": "attendance_form",
                "file": SimpleUploadedFile(
                    "training-attendance.docx",
                    buf.getvalue(),
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()
