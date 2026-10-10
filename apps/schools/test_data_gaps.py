"""A school that lacks a detail is listed, not hidden.

Owner, 2026-10-10: "can we make sure that all the school hidden because it
lacks certain data all unhidden so that the staff can update their data.
other dont have owners, other dont have ssa, others don't have district", and
"all the schools that were assessed but the record had issues can be fixed
and showed in the right place".
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_tz

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.clusters.models import Cluster
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty
from apps.schools import data_gaps
from apps.schools.models import School
from apps.ssa.models import SsaRecord

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"


class GapFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = str(get_operational_fy())
        cls.last = str(int(cls.fy) - 1)
        cls.region = Region.objects.create(name="Gap Region", country="Uganda")
        cls.district = District.objects.create(name="Gap", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="Gap SC", district=cls.district)
        cls.cluster = Cluster.objects.create(
            name="Gap Cluster",
            region=cls.region,
            district=cls.district,
            status="active",
        )

        def person(email, role):
            user = User.objects.create_user(
                email=email,
                name=email.split("@")[0].title(),
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            return StaffProfile.objects.create(user=user, country="Uganda")

        cls.officer = person("gap-cceo@edify.org", "CCEO")
        cls.other = person("gap-other@edify.org", "CCEO")
        cls.lead = person("gap-pl@edify.org", "Program Lead")
        cls.admin = person("gap-admin@edify.org", "Admin")
        cls.count = 0

    @classmethod
    def school(cls, name, *, held_by="officer", **over):
        cls.count += 1
        values = {
            "school_id": f"GAP-{cls.count}",
            "name": name,
            "region": cls.region,
            "district": cls.district,
            "sub_county": cls.sub_county,
            "school_type": "client",
            "cluster_id": cls.cluster.id,
            "cluster_status": "clustered",
            "enrollment": 120,
        }
        holder = getattr(cls, held_by) if held_by else None
        if holder is not None:
            values.update(account_owner_id=holder.id, account_owner_status="matched")
        values.update(over)
        school = School.objects.create(**values)
        if holder is not None:
            StaffSchoolAssignment.objects.create(staff=holder, school_id=school.id)
        return school

    def client_for(self, staff):
        client = Client()
        client.force_login(staff.user, backend=BACKEND)
        return client


class GapDefinitionTest(GapFixture):
    def test_each_gap_is_the_schools_whose_record_lacks_it(self):
        complete = self.school("Complete Primary")
        gaps = {
            "no_district": self.school("No District Primary", district=None),
            "no_sub_county": self.school("No Sub-county Primary", sub_county=None),
            # A school placed in a sub-county joins that sub-county's cluster
            # when it is saved, so the one with no cluster has no sub-county.
            "no_cluster": self.school(
                "No Cluster Primary",
                sub_county=None,
                cluster_id=None,
                cluster_status="unclustered",
            ),
            "no_type": self.school("No Type Primary", school_type=""),
            "no_enrolment": self.school("No Enrolment Primary", enrollment=None),
            "no_owner": self.school("No Owner Primary", held_by=None),
        }
        schools = School.objects.filter(name__endswith="Primary")

        figures = data_gaps.counts(schools, self.fy)

        for key, school in gaps.items():
            with self.subTest(gap=key):
                listed = set(
                    schools.filter(data_gaps.gap_q(key)).values_list("id", flat=True)
                )
                self.assertIn(school.id, listed)
                self.assertNotIn(complete.id, listed)
                # A count is the length of its list.
                self.assertEqual(figures[key], len(listed))
                school.refresh_from_db()
                self.assertIn(data_gaps.GAPS[key][0], data_gaps.missing(school))
        # Any gap: the six, never the complete one.
        any_gap = set(
            schools.filter(data_gaps.gap_q("any")).values_list("id", flat=True)
        )
        self.assertEqual(any_gap, {school.id for school in gaps.values()})
        self.assertEqual(figures["any"], 6)
        self.assertEqual(data_gaps.missing(complete), [])

    def test_no_ssa_is_read_for_the_year_asked_about(self):
        """The directory said "No SSA" for every school of a year in which
        most were assessed: it read a flag that is reset when the year turns."""
        assessed = self.school("Assessed Primary", current_fy_ssa_status="not_done")
        never = self.school("Never Primary", current_fy_ssa_status="not_done")
        SsaRecord.objects.create(
            school=assessed,
            fy=self.last,
            date_of_ssa=datetime(int(self.last) - 1, 11, 5, tzinfo=dt_tz.utc),
            average_score=6,
            verification_status="confirmed",
        )
        schools = School.objects.filter(id__in=[assessed.id, never.id])

        last_year = set(
            schools.filter(data_gaps.no_ssa_q(self.last)).values_list("id", flat=True)
        )
        this_year = set(
            schools.filter(data_gaps.no_ssa_q(self.fy)).values_list("id", flat=True)
        )

        self.assertEqual(last_year, {never.id})
        self.assertEqual(this_year, {assessed.id, never.id})
        self.assertEqual(data_gaps.counts(schools, self.last)["no_ssa"], 1)

    def test_an_unconfirmed_record_is_not_an_ssa(self):
        school = self.school("Pending Primary")
        SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            date_of_ssa=datetime(int(self.fy) - 1, 11, 5, tzinfo=dt_tz.utc),
            average_score=6,
            verification_status="pending",
        )

        self.assertTrue(
            School.objects.filter(id=school.id)
            .filter(data_gaps.no_ssa_q(self.fy))
            .exists()
        )


class DirectoryTest(GapFixture):
    def test_a_school_missing_a_detail_is_in_its_holder_s_directory(self):
        names = {
            "No District Primary": {"district": None},
            "No Sub-county Primary": {"sub_county": None},
            "No Enrolment Primary": {"enrollment": None},
            "No SSA Primary": {"current_fy_ssa_status": "not_done"},
        }
        for name, over in names.items():
            self.school(name, **over)

        body = self.client_for(self.officer).get("/schools").content.decode()

        for name in names:
            self.assertIn(name, body)

    def test_the_missing_detail_filter_lists_what_its_count_says(self):
        self.school("Complete Primary")
        self.school("No Sub-county One", sub_county=None)
        self.school("No Sub-county Two", sub_county=None)
        client = self.client_for(self.officer)

        page = client.get("/schools").content.decode()
        listed = client.get("/schools", {"gap": "no_sub_county"}).content.decode()

        self.assertIn('<option value="no_sub_county" >No Sub-county (2)</option>', page)
        self.assertIn("No Sub-county One", listed)
        self.assertIn("No Sub-county Two", listed)
        self.assertNotIn("Complete Primary", listed)

    def test_no_ssa_counts_the_year_on_the_page(self):
        school = self.school("Assessed Primary", current_fy_ssa_status="not_done")
        self.school("Never Primary", current_fy_ssa_status="not_done")
        SsaRecord.objects.create(
            school=school,
            fy=self.last,
            date_of_ssa=datetime(int(self.last) - 1, 11, 5, tzinfo=dt_tz.utc),
            average_score=6,
            verification_status="confirmed",
        )
        client = self.client_for(self.officer)

        last_year = client.get("/schools", {"fy": self.last}).context["no_ssa_schools"]
        this_year = client.get("/schools", {"fy": self.fy}).context["no_ssa_schools"]

        self.assertEqual((last_year, this_year), (1, 2))


class UnheldTest(GapFixture):
    def test_a_school_nobody_holds_is_shown_to_the_country_s_field_staff(self):
        """Owner, 2026-10-10: "All field staff, whole country"."""
        orphan = self.school("Orphan Primary", held_by=None)
        named = self.school(
            "Named Only Primary",
            held_by=None,
            account_owner_name_raw="Somebody Unknown",
            account_owner_status="pending",
        )
        held = self.school("Held Primary", held_by="other")

        for staff in (self.officer, self.lead):
            with self.subTest(role=staff.user.active_role):
                client = self.client_for(staff)
                own = client.get("/schools").content.decode()
                unheld = client.get("/schools", {"gap": "unheld"}).content.decode()

                # Not in anybody's own list, and said so on it.
                self.assertNotIn("Orphan Primary", own.split("data-unheld-schools")[0])
                self.assertIn("data-unheld-schools", own)
                for school in (orphan, named):
                    self.assertIn(school.name, unheld)
                # Somebody else's school is still somebody else's.
                self.assertNotIn(held.name, unheld)
                self.assertIn("Take This School", unheld)
                # Its profile opens, and so does its edit form.
                self.assertEqual(client.get(f"/schools/{orphan.id}").status_code, 200)
                self.assertEqual(
                    client.get(f"/schools/{orphan.id}/edit-drawer").status_code, 200
                )
                self.assertNotEqual(client.get(f"/schools/{held.id}").status_code, 200)

    def test_another_country_s_unheld_school_is_not_shown(self):
        abroad = Region.objects.create(name="Abroad", country="Kenya")
        far = District.objects.create(name="Far", region=abroad)
        self.school("Abroad Primary", held_by=None, region=abroad, district=far)

        unheld = self.client_for(self.officer).get("/schools", {"gap": "unheld"})

        self.assertNotIn("Abroad Primary", unheld.content.decode())

    def test_taking_a_school_makes_it_the_taker_s(self):
        orphan = self.school("Orphan Primary", held_by=None)
        client = self.client_for(self.officer)

        response = client.post(f"/schools/{orphan.id}/take")

        self.assertRedirects(
            response, f"/schools/{orphan.id}?tab=details", fetch_redirect_response=False
        )
        orphan.refresh_from_db()
        self.assertEqual(orphan.account_owner_id, self.officer.id)
        self.assertEqual(orphan.account_owner_status, "matched")
        self.assertTrue(
            StaffSchoolAssignment.objects.filter(
                staff=self.officer, school_id=orphan.id
            ).exists()
        )
        # It is in their directory now, and no longer on the unheld list.
        self.assertIn("Orphan Primary", client.get("/schools").content.decode())
        self.assertFalse(data_gaps.unheld("Uganda").filter(id=orphan.id).exists())

    def test_a_held_school_cannot_be_taken(self):
        held = self.school("Held Primary", held_by="other")

        self.client_for(self.officer).post(f"/schools/{held.id}/take")

        held.refresh_from_db()
        self.assertEqual(held.account_owner_id, self.other.id)
        self.assertFalse(
            StaffSchoolAssignment.objects.filter(
                staff=self.officer, school_id=held.id
            ).exists()
        )

    def test_a_role_that_holds_no_schools_takes_none(self):
        orphan = self.school("Orphan Primary", held_by=None)

        self.client_for(self.admin).post(f"/schools/{orphan.id}/take")

        orphan.refresh_from_db()
        self.assertFalse(orphan.account_owner_id)


class PlanningTest(GapFixture):
    def test_data_cleanup_required_lists_the_schools_it_counts(self):
        """On production the figure said 15,167 and its list was empty."""
        from apps.planning.planning_service import PlanningDashboardService

        self.school("Complete Primary")
        self.school("No Sub-county Primary", sub_county=None)
        self.school("No District Primary", district=None)

        data = PlanningDashboardService.get_dashboard_data(
            self.officer.user,
            {
                "planning_readiness": "data_cleanup_required",
                "tab": "client",
                "per_page": 50,
            },
        )

        names = {row["name"] for row in data["schools"]}
        self.assertEqual(names, {"No Sub-county Primary", "No District Primary"})

    def test_ssa_done_reads_the_year_s_records_not_a_flag(self):
        from apps.planning.planning_service import PlanningDashboardService

        assessed = self.school("Assessed Primary", current_fy_ssa_status="not_done")
        self.school("Never Primary", current_fy_ssa_status="not_done")
        SsaRecord.objects.create(
            school=assessed,
            fy=self.last,
            date_of_ssa=datetime(int(self.last) - 1, 11, 5, tzinfo=dt_tz.utc),
            average_score=6,
            verification_status="confirmed",
        )

        def names(status):
            data = PlanningDashboardService.get_dashboard_data(
                self.officer.user,
                {
                    "fy": self.last,
                    "ssa_status": status,
                    "tab": "client",
                    "per_page": 50,
                },
            )
            return {row["name"] for row in data["schools"]}

        self.assertEqual(names("done"), {"Assessed Primary"})
        self.assertEqual(names("not_done"), {"Never Primary"})


class RefileTest(GapFixture):
    """An SSA uploaded before its school was in the directory."""

    def park(self, school_id, uploader=None):
        from apps.schools.models import SSAImportBatch, UnmatchedSSARecord

        batch = SSAImportBatch.objects.create(
            uploaded_by=(uploader or self.admin).user_id, file_name="2026.xlsx"
        )
        return UnmatchedSSARecord.objects.create(
            batch=batch,
            school_id=school_id,
            date_of_ssa=f"{int(self.fy) - 1}-11-20",
            scores={key: 6 for key, _label in SsaIntervention.choices},
            reason="School ID does not exist in School Directory",
        )

    def test_a_parked_row_is_filed_once_its_school_exists(self):
        from apps.ssa.unmatched_service import refile_known

        row = self.park("GAP-LATE")

        self.assertEqual(refile_known(), {"filed": [], "skipped": []})
        school = self.school("Late Primary", school_id="GAP-LATE")
        dry = refile_known(apply=False)
        self.assertEqual(dry, {"filed": ["GAP-LATE"], "skipped": []})
        self.assertFalse(SsaRecord.objects.filter(school=school).exists())

        result = refile_known()

        self.assertEqual(result, {"filed": ["GAP-LATE"], "skipped": []})
        row.refresh_from_db()
        self.assertEqual(row.status, "matched")
        record = SsaRecord.objects.get(school=school)
        self.assertEqual(record.fy, self.fy)
        # Filing it twice files nothing more.
        self.assertEqual(refile_known()["filed"], [])
        self.assertEqual(SsaRecord.objects.filter(school=school).count(), 1)

    def test_only_an_exact_school_id_is_filed(self):
        from apps.ssa.unmatched_service import refile_known

        self.park("GAP-88")
        self.school("Lookalike Primary", school_id="GAP-880")

        self.assertEqual(refile_known()["filed"], [])
