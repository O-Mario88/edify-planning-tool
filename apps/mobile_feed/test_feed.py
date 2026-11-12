"""The native app's screen feeds return what the web pages are rendered from."""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import StaffProfile, User
from apps.command_center.home_service import build_home, build_home_queue
from apps.core.navigation import build_mobile_nav_for_user, build_sidebar_for_user


class ScreenFeedTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="officer@example.org",
            name="Ada Lovelace",
            roles=["CCEO"],
            active_role="CCEO",
            status="active",
            is_active=True,
        )
        StaffProfile.objects.create(user=self.user)
        self.client = APIClient()

    def get(self, path, user=None):
        user = user or self.user
        token = issue_access_token(user.id, user.active_role)
        return self.client.get(path, HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_feeds_require_a_token(self):
        for path in ("home", "home/queue", "home/todo-figures", "navigation"):
            with self.subTest(path=path):
                self.assertEqual(
                    self.client.get(f"/api/mobile/v1/{path}").status_code, 401
                )

    def test_home_feed_is_the_home_page_view_model(self):
        response = self.get("/api/mobile/v1/home")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        home = build_home(self.user, "/home")
        self.assertEqual(body["greeting"], home["greeting"])
        self.assertEqual(body["firstName"], "Ada")
        self.assertEqual(body["roleTitle"], home["role_title"])
        self.assertEqual(body["today"], home["today"].isoformat())
        self.assertEqual(body["fy"], str(home["fy"]))
        self.assertEqual(body["hasPlan"], home["has_plan"])
        self.assertEqual(
            [(f["key"], f["label"], f["tone"], f["url"]) for f in body["figures"]],
            [(f["key"], f["label"], f["tone"], f["url"]) for f in home["figures"]],
        )
        self.assertEqual(
            [(s["label"], s["url"]) for s in body["shortcuts"]],
            [(s["label"], s["url"]) for s in home["shortcuts"]],
        )

    def test_figures_carry_their_icon_as_svg_and_no_value_while_loading(self):
        body = self.get("/api/mobile/v1/home").json()

        for figure in body["figures"]:
            self.assertTrue(figure["iconSvg"].startswith("<svg"), figure["key"])
            if figure["loading"]:
                self.assertEqual(figure["value"], "")
            else:
                self.assertNotEqual(figure["value"], "")

    def test_queue_feed_is_the_page_queue(self):
        response = self.get("/api/mobile/v1/home/queue")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        queue = build_home_queue(self.user)
        self.assertEqual(
            [(r["title"], r["statusLabel"], r["url"]) for r in body["priorityRows"]],
            [(r["title"], r["status_label"], r["url"]) for r in queue["priority_rows"]],
        )
        self.assertEqual(body["todoFiguresLater"], queue["todo_figures_later"])
        # Absent, not zero, when the count follows in its own request.
        self.assertEqual("priorityTotal" in body, queue["priority_total"] is not None)

    def test_todo_figures_feed(self):
        response = self.get("/api/mobile/v1/home/todo-figures")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsInstance(body["priorityTotal"], int)
        self.assertTrue(
            all(f["iconSvg"].startswith("<svg") for f in body["queueFigures"])
        )

    def test_navigation_feed_is_the_role_navigation(self):
        response = self.get("/api/mobile/v1/navigation")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        sections = build_sidebar_for_user(self.user, "/home")
        bottom = build_mobile_nav_for_user(self.user, "/home", sections)
        self.assertEqual(
            [(i["label"], i["url"]) for i in body["bottom"]],
            [(i["label"], i["url"]) for i in bottom],
        )
        self.assertEqual(
            [[i["url"] for i in s["items"]] for s in body["sections"]],
            [[i["url"] for i in s["items"]] for s in sections],
        )
        self.assertTrue(body["bottom"][0]["iconSvg"].startswith("<svg"))

    def test_navigation_differs_by_role(self):
        accountant = User.objects.create(
            email="accounts@example.org",
            name="Grace Hopper",
            roles=["Accountant"],
            active_role="Accountant",
            status="active",
            is_active=True,
        )
        StaffProfile.objects.create(user=accountant)

        cceo = self.get("/api/mobile/v1/navigation").json()
        other = self.get("/api/mobile/v1/navigation", accountant).json()

        self.assertNotEqual(
            [i["url"] for i in cceo["bottom"]], [i["url"] for i in other["bottom"]]
        )

    def test_a_token_cannot_claim_a_role_the_account_does_not_hold(self):
        token = issue_access_token(self.user.id, "Admin")

        body = self.client.get(
            "/api/mobile/v1/navigation", HTTP_AUTHORIZATION=f"Bearer {token}"
        ).json()

        cceo = build_sidebar_for_user(self.user, "/home")
        self.assertEqual(
            [[i["url"] for i in s["items"]] for s in body["sections"]],
            [[i["url"] for i in s["items"]] for s in cceo],
        )


class SchoolDirectoryFeedTest(TestCase):
    """The directory feed is the School Directory page's own view-model."""

    def setUp(self):
        from apps.accounts.models import StaffSchoolAssignment
        from apps.schools.models import School

        self.user = User.objects.create(
            email="officer@example.org",
            name="Ada Lovelace",
            roles=["CCEO"],
            active_role="CCEO",
            status="active",
            is_active=True,
        )
        profile = StaffProfile.objects.create(user=self.user)
        for number in range(3):
            school = School.objects.create(
                school_id=f"EDU-{number}", name=f"School {number}"
            )
            StaffSchoolAssignment.objects.create(staff=profile, school_id=school.id)
        School.objects.create(school_id="EDU-OTHER", name="Not mine")
        self.client = APIClient()

    def get(self, query=""):
        token = issue_access_token(self.user.id, self.user.active_role)
        return self.client.get(
            f"/api/mobile/v1/school-directory{query}",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def page_context(self, query=""):
        from django.test import RequestFactory

        from apps.frontend.views.school_views import school_directory_context

        request = RequestFactory().get(f"/schools{query}")
        request.user = self.user
        return school_directory_context(request)

    def test_rows_are_the_pages_rows_in_the_pages_order(self):
        body = self.get().json()

        context = self.page_context()
        self.assertEqual(
            [s["schoolId"] for s in body["schools"]],
            [row["school_id"] for row in context["view_models"]],
        )
        self.assertNotIn("EDU-OTHER", [s["schoolId"] for s in body["schools"]])

    def test_tabs_carry_the_pages_counts(self):
        body = self.get().json()

        context = self.page_context()
        counts = {tab["key"]: tab["count"] for tab in body["tabs"]}
        self.assertEqual(counts["all"], context["all_count"])
        self.assertEqual(counts["unclustered"], context["unclustered_count"])
        self.assertEqual(body["activeTab"], "all")

    def test_the_pages_filters_are_applied(self):
        body = self.get("?q=EDU-1").json()

        self.assertEqual([s["schoolId"] for s in body["schools"]], ["EDU-1"])

    def test_an_export_is_never_returned(self):
        response = self.get("?export=csv")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_a_role_without_the_directory_is_refused(self):
        self.user.roles = ["Accountant"]
        self.user.active_role = "Accountant"
        self.user.save()

        self.assertEqual(self.get().status_code, 403)


class SchoolActionFeedTest(TestCase):
    """The row actions run the web drawers' own flows and report their outcome."""

    def setUp(self):
        from apps.accounts.models import StaffSchoolAssignment
        from apps.clusters.models import Cluster, ClusterSubCounty
        from apps.geography.models import District, Region, SubCounty
        from apps.schools.models import School

        region = Region.objects.create(name="Feed Region")
        self.district = District.objects.create(name="Feed District", region=region)
        sub_county = SubCounty.objects.create(
            name="Feed Sub County", district=self.district
        )
        self.user = User.objects.create(
            email="officer@example.org",
            name="Ada Lovelace",
            roles=["CCEO"],
            active_role="CCEO",
            status="active",
            is_active=True,
        )
        self.profile = StaffProfile.objects.create(user=self.user)
        self.school = School.objects.create(
            school_id="FEED-1",
            name="Feed School",
            region=region,
            district=self.district,
            sub_county=sub_county,
            school_type="client",
            account_owner_id=self.profile.id,
        )
        StaffSchoolAssignment.objects.create(
            staff=self.profile, school_id=self.school.id
        )
        self.cluster = Cluster.objects.create(
            name="Feed Cluster",
            region=region,
            district=self.district,
            cluster_type="mixed",
            status="active",
            responsible_staff_id=self.profile.id,
        )
        ClusterSubCounty.objects.create(cluster=self.cluster, sub_county=sub_county)
        self.client = APIClient()
        token = issue_access_token(self.user.id, self.user.active_role)
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def url(self, action):
        return f"/api/mobile/v1/schools/{self.school.id}/{action}"

    def test_the_cluster_form_lists_the_owners_clusters(self):
        form = self.client.get(self.url("add-to-cluster"), **self.auth).json()["form"]

        self.assertEqual(form["title"], "Add Feed School to cluster")
        self.assertFalse(form["isChange"])
        self.assertEqual([c["value"] for c in form["clusters"]], [self.cluster.id])
        self.assertTrue(
            form["clusters"][0]["label"].startswith("Feed Cluster · Feed District")
        )
        self.assertEqual(form["submitLabel"], "Add to cluster")

    def test_adding_to_a_cluster_saves_through_the_web_flow(self):
        result = self.client.post(
            self.url("add-to-cluster"),
            {"actionType": "existing", "clusterId": self.cluster.id},
            format="json",
            **self.auth,
        ).json()["result"]

        self.assertTrue(result["saved"], result)
        self.assertEqual(result["message"], "Feed School added to Feed Cluster.")
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.cluster.id)

    def test_a_correction_comes_back_as_the_drawers_own_message(self):
        result = self.client.post(
            self.url("add-to-cluster"),
            {"actionType": "existing", "clusterId": "not-a-cluster"},
            format="json",
            **self.auth,
        ).json()["result"]

        self.assertFalse(result.get("saved", False))
        self.assertEqual(
            result["error"],
            "Select one of the clusters belonging to this school's owner.",
        )

    def test_a_school_outside_the_portfolio_is_refused(self):
        from apps.schools.models import School

        other = School.objects.create(
            school_id="FEED-2", name="Not mine", district=self.district
        )

        response = self.client.get(
            f"/api/mobile/v1/schools/{other.id}/add-to-cluster", **self.auth
        ).json()

        self.assertTrue(response["form"]["refused"])

    def test_the_project_form_says_when_no_project_is_open(self):
        form = self.client.get(self.url("add-to-project"), **self.auth).json()["form"]

        self.assertEqual(form["title"], "Assign Feed School to project")
        self.assertEqual(form["projects"], [])
        self.assertEqual(
            form["emptyNotice"],
            "No active projects available. Create a project before assigning schools.",
        )
        self.assertIn("Coaching", [t["value"] for t in form["supportTypes"]])

    def test_a_project_must_be_chosen(self):
        result = self.client.post(
            self.url("add-to-project"), {"projectId": ""}, format="json", **self.auth
        ).json()["result"]

        self.assertEqual(result["error"], "Please select a project.")


class BulkBarFeedTest(SchoolActionFeedTest):
    """The bulk bar runs the web's own bulk saves and reports their messages."""

    def setUp(self):
        super().setUp()
        from apps.accounts.models import StaffSchoolAssignment
        from apps.geography.models import SubCounty
        from apps.schools.models import School

        # A sub-county the cluster does not cover: a school created in a
        # covered one joins the cluster at once (the existing geography rule).
        elsewhere = SubCounty.objects.create(
            name="Feed Other Sub County", district=self.district
        )
        self.second = School.objects.create(
            school_id="FEED-3",
            name="Second School",
            region=self.school.region,
            district=self.district,
            sub_county=elsewhere,
            school_type="client",
            account_owner_id=self.profile.id,
        )
        StaffSchoolAssignment.objects.create(
            staff=self.profile, school_id=self.second.id
        )

    def bulk(self, action, body):
        return self.client.post(
            f"/api/mobile/v1/schools/{action}", body, format="json", **self.auth
        ).json()["result"]

    def test_the_directory_offers_the_bulk_choices(self):
        body = self.client.get("/api/mobile/v1/school-directory", **self.auth).json()

        self.assertIn(self.cluster.id, [c["value"] for c in body["bulkClusters"]])
        self.assertIn("projectIds", body["schools"][0])

    def test_assigning_ticked_schools_to_a_cluster(self):
        result = self.bulk(
            "bulk-assign-cluster",
            {
                "schoolIds": [self.school.id, self.second.id],
                "clusterId": self.cluster.id,
            },
        )

        self.assertTrue(result["saved"], result)
        self.assertEqual(
            result["message"],
            "Successfully assigned 2 schools to cluster 'Feed Cluster'.",
        )
        self.second.refresh_from_db()
        self.assertEqual(self.second.cluster_id, self.cluster.id)

    def test_already_clustered_schools_are_skipped_and_said_so(self):
        body = {"schoolIds": [self.school.id], "clusterId": self.cluster.id}
        self.bulk("bulk-assign-cluster", body)

        result = self.bulk("bulk-assign-cluster", body)

        self.assertFalse(result.get("saved", False))
        self.assertEqual(result["error"], "No unclustered schools were selected.")
        self.assertEqual(
            result["warnings"], ["Skipped already-clustered schools: Feed School."]
        )

    def test_a_school_outside_the_portfolio_is_never_changed(self):
        from apps.schools.models import School

        other = School.objects.create(
            school_id="FEED-X", name="Not mine", district=self.district
        )

        self.bulk(
            "bulk-assign-cluster",
            {"schoolIds": [other.id], "clusterId": self.cluster.id},
        )

        other.refresh_from_db()
        self.assertIsNone(other.cluster_id)

    def test_nothing_ticked_is_the_webs_own_error(self):
        result = self.bulk("bulk-assign-project", {"schoolIds": [], "projectId": ""})

        self.assertTrue(result["error"])


class SchoolProfileFeedTest(SchoolActionFeedTest):
    """The profile feed is the page the web renders for the same person."""

    def test_the_directory_says_whether_names_open_the_profile(self):
        from apps.core.permissions import can_open_url

        body = self.client.get("/api/mobile/v1/school-directory", **self.auth).json()

        self.assertEqual(
            body.get("mayOpenProfile", False), can_open_url(self.user, "/schools/0")
        )
        self.assertTrue(body.get("mayOpenProfile"))

    def open_profile(self, **query):
        return self.client.get(self.url("profile"), query, **self.auth)

    def test_the_profile_is_the_web_pages_header_tabs_and_blocks(self):
        response = self.open_profile()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["header"]["title"], "Feed School")
        self.assertEqual(body["header"]["description"], "School ID: FEED-1")
        self.assertEqual(body["header"]["backHref"], "/schools")
        tabs = {tab["key"]: tab for tab in body["tabs"]}
        self.assertTrue(tabs["overview"]["active"])
        self.assertIn("details", tabs)
        kinds = [next(iter(block)) for block in body["blocks"]]
        self.assertEqual(kinds[:3], ["scopeLine", "facts", "filters"])
        self.assertIn("strip", kinds)
        self.assertEqual(body["webPath"], f"/schools/{self.school.id}")

    def test_the_open_tab_comes_from_the_query(self):
        body = self.open_profile(tab="details").json()

        self.assertTrue(
            next(t for t in body["tabs"] if t["key"] == "details")["active"]
        )
        panels = [b["panel"]["title"] for b in body["blocks"] if "panel" in b]
        self.assertIn("School Demographics & Assignment", panels)

    def test_a_school_outside_the_readers_scope_is_not_found(self):
        from apps.schools.models import School

        colleague = User.objects.create(
            email="colleague@example.org",
            name="Grace Hopper",
            roles=["CCEO"],
            active_role="CCEO",
            status="active",
            is_active=True,
        )
        their_profile = StaffProfile.objects.create(user=colleague)
        other = School.objects.create(
            school_id="FEED-2",
            name="Other School",
            school_type="client",
            account_owner_id=their_profile.id,
        )

        response = self.client.get(
            f"/api/mobile/v1/schools/{other.id}/profile", **self.auth
        )

        self.assertEqual(response.status_code, 404)


class SchoolDrawerFeedTest(SchoolActionFeedTest):
    """The profile's drawers are the web drawers, saved by the web's views."""

    def drawer(self, kind, school=None):
        school = school or self.school
        return self.client.get(
            f"/api/mobile/v1/schools/{school.id}/drawers/{kind}", **self.auth
        )

    def save(self, kind, values):
        return self.client.post(
            f"/api/mobile/v1/schools/{self.school.id}/drawers/{kind}",
            {"values": values},
            format="json",
            **self.auth,
        )

    def filled(self, kind):
        """The drawer's fields with the values it opens with."""
        drawer = self.drawer(kind).json()["drawer"]
        return {
            item["field"]["name"]: item["field"]["value"]
            for item in drawer["items"]
            if "field" in item
        }

    def test_the_edit_drawer_is_the_web_drawer(self):
        drawer = self.drawer("edit").json()["drawer"]

        self.assertEqual(drawer["title"], "Edit Feed School")
        fields = {
            i["field"]["name"]: i["field"] for i in drawer["items"] if "field" in i
        }
        self.assertEqual(fields["name"]["value"], "Feed School")
        self.assertEqual(fields["district_id"]["value"], self.district.id)
        self.assertTrue(drawer["canSubmit"])

    def test_edit_saves_through_the_web_view(self):
        values = {**self.filled("edit"), "name": "Feed School Renamed"}

        body = self.save("edit", values).json()

        self.assertTrue(body["saved"], body)
        self.assertIn("updated", body["message"])
        self.school.refresh_from_db()
        self.assertEqual(self.school.name, "Feed School Renamed")

    def test_an_edit_refused_comes_back_in_the_drawer(self):
        values = {**self.filled("edit"), "name": ""}

        body = self.save("edit", values).json()

        self.assertFalse(body["saved"])
        notes = [i["note"] for i in body["drawer"]["items"] if "note" in i]
        self.assertIn({"text": "School name is required.", "tone": "danger"}, notes)
        self.school.refresh_from_db()
        self.assertEqual(self.school.name, "Feed School")

    def test_close_saves_through_the_web_view(self):
        from django.utils import timezone

        drawer = self.drawer("close").json()["drawer"]
        fields = {
            i["field"]["name"]: i["field"] for i in drawer["items"] if "field" in i
        }
        reason = next(
            o["value"] for o in fields["reason_category"]["options"] if o["value"]
        )

        body = self.save(
            "close",
            {
                "closure_type": "temporary",
                "effective_date": timezone.localdate().isoformat(),
                "reason_category": reason,
                "reason": "The campus flooded in October and classes stopped.",
            },
        ).json()

        self.assertTrue(body["saved"], body)
        self.assertIn("is closed", body["message"])
        self.school.refresh_from_db()
        self.assertTrue(self.school.is_closed)

    def test_a_close_refused_says_why(self):
        body = self.save("close", {"closure_type": "temporary"}).json()

        self.assertFalse(body["saved"])
        self.assertNotEqual(body.get("error", "") or body.get("drawer"), "")

    def test_ssa_entry_saves_through_the_web_view(self):
        from apps.ssa.models import SsaRecord

        values = {**self.filled("ssa-entry")}
        for name in values:
            if name.startswith("score_"):
                values[name] = "6.5"

        body = self.save("ssa-entry", values).json()

        self.assertTrue(body["saved"], body)
        self.assertTrue(SsaRecord.objects.filter(school_id=self.school.id).exists())

    def test_an_unknown_drawer_is_not_found(self):
        self.assertEqual(self.drawer("delete").status_code, 404)

    def test_a_school_outside_the_readers_scope_is_refused(self):
        from apps.schools.models import School

        colleague = User.objects.create(
            email="colleague@example.org",
            name="Grace Hopper",
            roles=["CCEO"],
            active_role="CCEO",
            status="active",
            is_active=True,
        )
        their_profile = StaffProfile.objects.create(user=colleague)
        other = School.objects.create(
            school_id="FEED-2",
            name="Other School",
            school_type="client",
            account_owner_id=their_profile.id,
        )

        # The web refuses another officer's school; the feed passes that on.
        self.assertEqual(self.drawer("edit", other).status_code, 403)

    def test_a_reloading_field_lists_the_web_views_choices(self):
        response = self.client.get(
            "/api/mobile/v1/drawers/options",
            {"source": "/schools/sub-counties", "district_id": self.district.id},
            **self.auth,
        )

        self.assertEqual(response.status_code, 200)
        labels = [o["label"] for o in response.json()["options"]]
        self.assertIn("Feed Sub County", labels)

    def test_only_known_choice_lists_are_read(self):
        response = self.client.get(
            "/api/mobile/v1/drawers/options", {"source": "/users"}, **self.auth
        )

        self.assertEqual(response.status_code, 404)


class PlanningDrawerFeedTest(SchoolActionFeedTest):
    """Schedule visit and Assign to Partner are the web drawers, saved by the
    web views their forms post to."""

    def drawer(self, kind, school=None):
        school = school or self.school
        return self.client.get(
            f"/api/mobile/v1/schools/{school.id}/planning/{kind}", **self.auth
        )

    def save(self, kind, values):
        return self.client.post(
            f"/api/mobile/v1/schools/{self.school.id}/planning/{kind}",
            {"values": values},
            format="json",
            **self.auth,
        )

    def test_the_schedule_drawer_is_the_web_drawer(self):
        body = self.drawer("schedule").json()

        drawer = body["drawer"]
        self.assertEqual(drawer["title"], "Schedule visit for Feed School")
        self.assertEqual(drawer["submitLabel"], "Schedule visit")
        self.assertIn("donor_visit", [p["value"] for p in drawer["purposes"]])
        self.assertEqual(drawer["hidden"]["school_id"], "FEED-1")

    def test_the_assign_drawer_is_the_web_drawer(self):
        drawer = self.drawer("assign").json()["drawer"]

        self.assertEqual(drawer["title"], "Assign Feed School to a partner")
        self.assertEqual(drawer["labels"]["partner_id"], "Partner")

    def test_a_schedule_refused_says_why_and_saves_nothing(self):
        from apps.activities.models import Activity

        body = self.save("schedule", {"purpose_of_visit": "donor_visit"}).json()

        self.assertFalse(body["saved"])
        self.assertTrue(body["error"])
        self.assertFalse(Activity.objects.filter(school_id=self.school.id).exists())

    def form_only(self, kind, values, school=None):
        school = school or self.school
        return self.client.post(
            f"/api/mobile/v1/schools/{school.id}/planning/{kind}?form_only=1",
            {"values": values},
            format="json",
            **self.auth,
        )

    def test_the_schedule_form_is_what_the_save_would_post_and_nothing_is_saved(
        self,
    ):
        from apps.activities.models import Activity
        from apps.mobile_feed import planning_drawers

        values = {
            "purpose_of_visit": "donor_visit",
            "scheduled_date": "2099-01-05",
            "executor_type": "staff",
            "expected_outcome": "not a field the app saves",
        }
        from apps.mobile_feed.views import _planning_html

        body = self.form_only("schedule", values).json()

        _status, html = _planning_html(self.user, "schedule", self.school.id)
        expected = planning_drawers.form_data("schedule", html, values)
        # Each drawer render carries its own CSRF token; the rest is the same.
        body["form"].pop("csrfmiddlewaretoken", None)
        expected.pop("csrfmiddlewaretoken", None)
        self.assertEqual(body["form"], expected)
        self.assertEqual(body["form"]["school_id"], "FEED-1")
        self.assertNotIn("expected_outcome", body["form"])
        self.assertEqual(
            set(body["origin"]), {"ip", "agent", "correlation"}, body["origin"]
        )
        self.assertTrue(body["origin"]["correlation"])
        self.assertFalse(Activity.objects.filter(school_id=self.school.id).exists())

    def test_the_schedule_form_keeps_the_drawers_refusals(self):
        self.assertEqual(
            self.client.post(
                f"/api/mobile/v1/schools/{self.school.id}/planning/schedule"
                "?form_only=1",
                {"values": "not a dict"},
                format="json",
                **self.auth,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/api/mobile/v1/schools/NO-SUCH-SCHOOL/planning/schedule"
                "?form_only=1",
                {"values": {}},
                format="json",
                **self.auth,
            ).status_code,
            404,
        )

    def test_only_the_schedule_drawer_answers_its_form(self):
        body = self.form_only("assign", {"purpose_of_visit": "training_follow_up"})

        self.assertNotIn("form", body.json())
        self.assertFalse(body.json()["saved"])

    def test_an_assignment_without_a_partner_is_refused(self):
        body = self.save("assign", {"purpose_of_visit": "training_follow_up"}).json()

        self.assertFalse(body["saved"])
        self.assertTrue(body["error"])

    def test_an_unknown_planning_drawer_is_not_found(self):
        self.assertEqual(self.drawer("delete").status_code, 404)

    def test_the_training_ceiling_reads_the_web_view(self):
        response = self.client.get(
            "/api/mobile/v1/planning/training-capacity",
            {"training": "", "date": "", "school": "FEED-1"},
            **self.auth,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("managed", response.json())

    def test_a_visit_schedules_through_the_web_view(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.activities.models import Activity

        day = timezone.localdate() + timedelta(days=14)
        while day.weekday() >= 5:
            day += timedelta(days=1)

        body = self.save(
            "schedule",
            {
                "purpose_of_visit": "donor_visit",
                "activity_type": "school_visit",
                "scheduled_date": day.isoformat(),
                "executor_type": "staff",
                "delivery_type": "staff",
            },
        ).json()

        self.assertTrue(body["saved"], body)
        self.assertNotIn("Undo", body["message"])
        self.assertTrue(
            Activity.objects.filter(
                school_id=self.school.id, deleted_at__isnull=True
            ).exists()
        )


class MyPlanFeedTest(SchoolActionFeedTest):
    """My Plan is the page the web renders for the reader, read as blocks."""

    def plan(self, **params):
        return self.client.get("/api/mobile/v1/my-plan", params, **self.auth)

    def tables(self, body):
        return {b["table"]["title"]: b["table"] for b in body["blocks"] if "table" in b}

    def test_the_page_is_the_web_page(self):
        body = self.plan().json()

        self.assertEqual(body["header"]["title"], "My Plan")
        self.assertIn("Export", [a["label"] for a in body["header"]["actions"]])
        tabs = next(b["linkTabs"] for b in body["blocks"] if "linkTabs" in b)
        self.assertEqual(
            [t["label"] for t in tabs["tabs"]],
            ["This Week", "This Month", "This Quarter", "This FY"],
        )
        self.assertEqual(tabs["beside"]["href"], "/calendar")
        visits = self.tables(body)["School Visits Planned for This FY"]
        self.assertEqual(visits["count"], "0")
        self.assertEqual(visits["emptyAction"]["href"], "/planning")

    def test_a_planned_visit_is_a_row_with_its_menu(self):
        from django.utils import timezone

        from apps.activities.models import Activity
        from apps.core.fy import get_operational_fy, get_quarter_for_date

        today = timezone.localdate()
        visit = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            school=self.school,
            responsible_staff_id=self.profile.id,
            delivery_type="staff",
            planned_date=today,
            fy=get_operational_fy(today),
            quarter=get_quarter_for_date(today),
        )

        visits = self.tables(self.plan().json())["School Visits Planned for This FY"]

        self.assertEqual(visits["count"], "1")
        row = visits["rows"][0]
        self.assertEqual(row["cells"][1]["text"], "Feed School")
        self.assertEqual(row["pickId"], visit.id)
        menu = row["cells"][-1]["actions"]
        self.assertIn(f"/my-plan/{visit.id}", [a["href"] for a in menu])
        self.assertIn("Cancel Activity", [a["label"] for a in menu])
        self.assertEqual(menu[-1]["key"], "danger")

    def test_the_readiness_part_is_read_in_its_place(self):
        titles = list(self.tables(self.plan().json()))

        self.assertTrue(
            any(t.startswith("Planned and remaining") for t in titles), titles
        )

    def test_only_the_pages_own_parameters_are_passed_on(self):
        response = self.plan(export="xlsx", fy="2026", school_visits_page="2")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        filters = next(
            b["filters"] for b in response.json()["blocks"] if "filters" in b
        )
        fy = next(f for f in filters["filters"] if f["name"] == "fy")
        self.assertEqual(fy["value"], "2026")


class PageFeedTest(SchoolActionFeedTest):
    """Any page the app draws is the web page for the reader, and only the
    pages the feed names are reachable."""

    def page(self, path, **params):
        return self.client.get(
            "/api/mobile/v1/page", {"path": path, **params}, **self.auth
        )

    def test_a_named_page_is_read_as_blocks(self):
        body = self.page("/todos").json()

        self.assertTrue(body["header"]["title"])
        self.assertEqual(body["webPath"], "/todos")

    def test_a_page_not_named_is_not_reachable(self):
        # The Users page exists, but the app does not read it.
        self.assertEqual(self.page("/users").status_code, 404)
        self.assertEqual(self.page("/no-such-page").status_code, 404)

    def test_a_cluster_card_opens_onto_its_schools(self):
        from apps.schools.models import School

        School.objects.filter(pk=self.school.pk).update(cluster_id=self.cluster.id)
        clusters = self.page("/clusters").json()
        card = next(
            b["record"]
            for b in clusters["blocks"]
            if "record" in b and b["record"]["title"] == "Feed Cluster"
        )

        schools = self.page(card["detailsPath"])

        self.assertEqual(
            card["detailsPath"], f"/partials/clusters/{self.cluster.id}/schools"
        )
        self.assertEqual(schools.status_code, 200)
        self.assertIn("Feed School", repr(schools.json()["blocks"]))

    def test_a_form_says_whether_the_app_saves_it(self):
        body = self.page("/escalations").json()

        form = next(b["form"] for b in body["blocks"] if "form" in b)
        self.assertTrue(form["canSave"])
        # Where a form posts stays in the feed.
        self.assertNotIn("_action", repr(body))

    def test_the_menu_marks_the_pages_the_app_draws(self):
        body = self.client.get("/api/mobile/v1/navigation", **self.auth).json()

        items = {i["url"]: i for s in body["sections"] for i in s["items"]}
        self.assertTrue(items["/todos"]["native"])
        # The directory has its own screen, not the page screen.
        self.assertFalse(items["/schools"]["native"])

    def test_a_page_the_readers_role_cannot_open_is_refused(self):
        from apps.mobile_feed.views import NATIVE_PAGES

        self.assertIn("weekly_fund_requests", NATIVE_PAGES)
        self.user.roles = ["Partner"]
        self.user.active_role = "Partner"
        self.user.save(update_fields=["roles", "active_role"])
        token = issue_access_token(self.user.id, self.user.active_role)
        response = self.client.get(
            "/api/mobile/v1/page",
            {"path": "/fund-requests/weekly"},
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertIn(response.status_code, (403, 404))


class PageDrawerFeedTest(SchoolActionFeedTest):
    """A drawer a page opens is the web drawer, saved by the view its form
    posts to; only the drawers and saves the feed names are reachable."""

    def setUp(self):
        super().setUp()
        from django.utils import timezone

        from apps.activities.models import Activity
        from apps.core.fy import get_operational_fy, get_quarter_for_date

        day = timezone.localdate() + timezone.timedelta(days=10)
        self.visit = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            school=self.school,
            responsible_staff_id=self.profile.id,
            delivery_type="staff",
            planned_date=day,
            fy=get_operational_fy(day),
            quarter=get_quarter_for_date(day),
        )

    def drawer(self, path):
        return self.client.get("/api/mobile/v1/drawer", {"path": path}, **self.auth)

    def save(self, path, values):
        return self.client.post(
            "/api/mobile/v1/drawer",
            {"path": path, "values": values},
            format="json",
            **self.auth,
        )

    def test_the_rows_menu_marks_its_drawers(self):
        body = self.client.get(
            "/api/mobile/v1/page", {"path": "/my-plan"}, **self.auth
        ).json()
        visits = next(
            b["table"]
            for b in body["blocks"]
            if "table" in b and b["table"]["title"].startswith("School Visits")
        )
        menu = visits["rows"][0]["cells"][-1]["actions"]

        cancel = next(a for a in menu if a["label"] == "Cancel Activity")
        self.assertTrue(cancel["drawer"])
        self.assertEqual(cancel["href"], f"/my-plan/{self.visit.id}/cancel-drawer")

    def test_details_is_the_web_drawer(self):
        body = self.drawer(f"/my-plan/{self.visit.id}").json()

        self.assertIn("drawer", body)
        self.assertTrue(body["drawer"]["title"])

    def test_cancel_saves_through_the_web_view(self):
        path = f"/my-plan/{self.visit.id}/cancel-drawer"
        drawer = self.drawer(path).json()["drawer"]
        fields = [i["field"] for i in drawer["items"] if "field" in i]
        values = {f["name"]: f["value"] for f in fields}
        for field in fields:
            if field["kind"] == "select" and not values[field["name"]]:
                values[field["name"]] = next(
                    o["value"] for o in field["options"] if o["value"]
                )
            elif field["kind"] in ("text", "textarea") and not values[field["name"]]:
                values[field["name"]] = "The school is closed for exams this week."

        body = self.save(path, values).json()

        self.assertTrue(body["saved"], body)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, "cancelled")

    def test_create_cluster_saves_each_ticked_sub_county(self):
        from apps.clusters.models import Cluster, ClusterSubCounty
        from apps.geography.models import SubCounty

        second = SubCounty.objects.create(name="Feed Hill", district=self.district)
        path = "/clusters/create-drawer"
        drawer = self.drawer(path).json()["drawer"]
        fields = {
            i["field"]["name"]: i["field"] for i in drawer["items"] if "field" in i
        }
        checklist = fields["sub_county_ids"]
        mine = [
            o["value"] for o in checklist["options"] if o["group"] == self.district.id
        ]

        body = self.save(
            path,
            {
                "district_id": self.district.id,
                "sub_county_ids": ",".join(mine),
                "name": "Feed Hill Cluster",
            },
        ).json()

        self.assertEqual(checklist["kind"], "checklist")
        self.assertEqual(checklist["groupBy"], "district_id")
        self.assertIn(second.id, mine)
        self.assertTrue(body["saved"], body)
        cluster = Cluster.objects.get(name="Feed Hill Cluster")
        self.assertEqual(
            set(
                ClusterSubCounty.objects.filter(cluster=cluster).values_list(
                    "sub_county_id", flat=True
                )
            ),
            set(mine),
        )
        self.assertEqual(len(mine), 2)

    def test_a_form_the_page_shows_itself_saves_through_the_page(self):
        from apps.flags.models import LeadershipEscalation

        page = self.client.get(
            "/api/mobile/v1/page", {"path": "/escalations"}, **self.auth
        ).json()
        form = next(b["form"] for b in page["blocks"] if "form" in b)
        fields = {i["field"]["name"]: i["field"] for i in form["items"] if "field" in i}

        body = self.client.post(
            "/api/mobile/v1/drawer",
            {
                "path": "/escalations",
                "form": form["key"],
                "values": {
                    "category": fields["category"]["options"][0]["value"],
                    "subject": "Partner not delivering in Feed District",
                    "detail": "Three visits missed this term.",
                    # A field the form does not have never reaches the view.
                    "decision": "approved",
                },
            },
            format="json",
            **self.auth,
        ).json()

        self.assertEqual(form["key"], "raise")
        self.assertTrue(body["saved"], body)
        escalation = LeadershipEscalation.objects.get(
            subject="Partner not delivering in Feed District"
        )
        self.assertEqual(escalation.detail, "Three visits missed this term.")

    def test_a_form_the_page_does_not_have_is_refused(self):
        body = self.client.post(
            "/api/mobile/v1/drawer",
            {"path": "/escalations", "form": "nonsense", "values": {}},
            format="json",
            **self.auth,
        ).json()

        self.assertFalse(body["saved"])
        self.assertEqual(body["error"], "This form is not available.")

    def test_ticked_activities_are_cancelled_together(self):
        from apps.activities.models import Activity

        second = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            school=self.school,
            responsible_staff_id=self.profile.id,
            delivery_type="staff",
            planned_date=self.visit.planned_date,
            fy=self.visit.fy,
            quarter=self.visit.quarter,
        )
        path = f"/activity-selection/cancel?ids={self.visit.id},{second.id}"
        drawer = self.drawer(path).json()["drawer"]
        fields = {
            i["field"]["name"]: i["field"] for i in drawer["items"] if "field" in i
        }
        values = {name: field["value"] for name, field in fields.items()}
        for name, field in fields.items():
            if field["kind"] == "select" and not values[name]:
                values[name] = next(o["value"] for o in field["options"] if o["value"])
            elif field["kind"] in ("text", "textarea") and not values[name]:
                values[name] = "The school is closed for exams this week."

        body = self.save(path, values).json()

        self.assertTrue(body["saved"], body)
        statuses = set(
            Activity.objects.filter(id__in=[self.visit.id, second.id]).values_list(
                "status", flat=True
            )
        )
        self.assertEqual(statuses, {"cancelled"})

    def test_a_drawer_opens_with_every_ticked_school(self):
        from apps.mobile_feed.views import _page_params

        many = ",".join(f"school{n:03d}" for n in range(150))

        self.assertEqual(_page_params({"school_ids": many})["school_ids"], many)
        self.assertEqual(_page_params({"school_ids": "a,<b>"}), {})
        self.assertEqual(_page_params({"note": "x" * 200}), {})

    def _export(self):
        path = "/my-plan/export-drawer"
        drawer = self.drawer(path).json()["drawer"]
        fields = [i["field"] for i in drawer["items"] if "field" in i]
        return self.save(path, {f["name"]: f["value"] for f in fields}).json()

    def test_an_export_is_prepared_and_downloaded_by_a_signed_link(self):
        saved = self._export()

        self.assertTrue(saved["saved"], saved)
        status = self.client.get(
            f"/api/mobile/v1/exports/{saved['exportJob']}", **self.auth
        ).json()
        self.assertEqual(status["status"], "ready")
        self.assertTrue(status["filename"].endswith(".xlsx"), status)
        # The phone's browser downloads it: no bearer token, the link is signed.
        anonymous = APIClient()
        file = anonymous.get(status["downloadUrl"])
        self.assertEqual(file.status_code, 200)
        self.assertIn("attachment", file["Content-Disposition"])

    def test_a_download_link_is_refused_when_changed_or_not_the_readers(self):
        from apps.mobile_feed.exports import export_download_url

        saved = self._export()
        url = self.client.get(
            f"/api/mobile/v1/exports/{saved['exportJob']}", **self.auth
        ).json()["downloadUrl"]

        self.assertEqual(APIClient().get(url + "x").status_code, 404)
        other = User.objects.create(
            email="other@example.org", name="Other", status="active"
        )
        self.assertEqual(
            APIClient()
            .get(export_download_url(other.id, saved["exportJob"]))
            .status_code,
            404,
        )

    def test_a_drawer_not_named_is_not_reachable(self):
        # The evidence upload drawer exists but the app does not draw it yet.
        self.assertEqual(
            self.drawer(f"/activities/{self.visit.id}/evidence").status_code, 404
        )
        self.assertEqual(self.drawer("/users").status_code, 404)
