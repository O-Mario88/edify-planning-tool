"""Impact Assessment exports every queue it works from (owner, 2026-10-19:
"make sure the IA can export every columns he needs").

The verification queue, the partner evidence queue, returned work and the
verification history each download their own rows — filtered as the page is
— with every column apps.activities.ia_export lays out, the School ID among
them. Each page offers the Export button.
"""

from __future__ import annotations

import io

import openpyxl
from django.utils import timezone

from apps.activities.ia_export import HEADERS
from apps.activities.models import Activity, VerificationHistory
from apps.frontend.test_ia_performance import IAPerformanceTestBase

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class IaQueuesExport(IAPerformanceTestBase):
    def _sheet(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        self.assertEqual(response["Content-Type"], XLSX, url)
        book = openpyxl.load_workbook(io.BytesIO(response.content))
        rows = list(book.worksheets[0].iter_rows(values_only=True))
        self.assertEqual(list(rows[0]), list(HEADERS), url)
        return [dict(zip(HEADERS, row)) for row in rows[1:]]

    def test_the_verification_queue(self):
        school = self._school("Q1")
        act = self._pending_activity(school)
        rows = self._sheet("/ia/verification/?export=xlsx")
        row = next(r for r in rows if r["Activity ID"] == act.id)
        self.assertEqual(row["School ID"], "IAP-Q1")
        self.assertEqual(row["Salesforce ID"], act.salesforce_activity_id)
        self.assertEqual(row["Delivered By"], "Staff")

    def test_the_partner_evidence_queue(self):
        school = self._school("P1")
        act = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="partner",
            status="awaiting_ia_verification",
            monitored_by_staff_id=self.officer_sp.id,
            fy="2026",
            planned_date=timezone.localdate(),
        )
        rows = self._sheet("/ia/partner-evidence/?export=xlsx")
        row = next(r for r in rows if r["Activity ID"] == act.id)
        self.assertEqual(row["School ID"], "IAP-P1")
        self.assertEqual(row["Delivered By"], "Partner")

    def test_returned_work(self):
        act = self._pending_activity(self._school("R1"))
        Activity.objects.filter(id=act.id).update(status="returned_by_ia")
        rows = self._sheet("/ia/returned/?export=xlsx")
        self.assertIn(act.id, {r["Activity ID"] for r in rows})

    def test_the_verification_history(self):
        act = self._pending_activity(self._school("H1"))
        VerificationHistory.objects.create(
            activity=act, verified_by=self.ia.id, verified_at=timezone.now()
        )
        rows = self._sheet("/ia/history/?export=xlsx")
        self.assertIn(act.id, {r["Activity ID"] for r in rows})

    def test_a_csv_on_request(self):
        self._pending_activity(self._school("C1"))
        response = self.client.get("/ia/verification/?export=xlsx&format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("text/csv"))
        self.assertTrue(response.content.decode().startswith("Activity ID,"))

    def test_each_page_offers_the_export(self):
        for url in (
            "/ia/verification/",
            "/ia/partner-evidence/",
            "/ia/returned/",
            "/ia/history/",
        ):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), "data-ia-export")
