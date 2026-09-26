"""The Country Director opens the same cluster directory as a CCEO or PL.

`/clusters` is the card directory — one expandable card per cluster with its
SSA, coverage and next-action metadata. The CD has always been authorized for
it (`PAGE_PERMISSIONS["clusters"]`) and `cluster_queryset` returns the whole
country for them, but the sidebar never advertised it: the Clusters link lives
in SCHOOLS & FIELD, which the CD does not receive. So the only cluster list a
CD was offered was the grouped ownership table on Team Oversight, and the page
"looked different" for them because it was a different page.

These tests pin the two halves: the CD is offered the link, and the link
renders the same directory, cards included, with the planning controls the
CD's `planning` permission entitles them to.
"""

from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.clusters.models import Cluster
from apps.geography.models import District, Region, SubCounty

User = get_user_model()


def _user(uid, role):
    return User.objects.create(
        id=uid,
        email=f"{uid}@edify.org",
        name=uid,
        roles=[role],
        active_role=role,
        is_active=True,
    )


class CountryDirectorClusterDirectoryTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="CDCD Region")
        district = District.objects.create(name="CDCD District", region=region)
        sub_county = SubCounty.objects.create(name="CDCD Sub", district=district)
        cls.cluster = Cluster.objects.create(
            name="CDCD Directory Cluster",
            region=region,
            district=district,
            sub_county=sub_county,
            status="active",
        )
        cls.cd = _user("cdcd-cd", "CountryDirector")
        cls.cceo = _user("cdcd-cceo", "CCEO")

    def test_sidebar_offers_the_cd_the_cluster_directory(self):
        self.client.force_login(self.cd)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/clusters"')

    def test_cd_gets_the_same_card_directory_as_a_cceo(self):
        self.client.force_login(self.cd)
        response = self.client.get("/clusters")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/clusters/index.html")
        self.assertTemplateUsed(response, "partials/clusters/cluster_card.html")
        self.assertContains(response, "CDCD Directory Cluster")
        # Same list, not the same authority: cluster meetings and trainings are
        # the cluster owner's programme, so the CD is offered no Schedule
        # button (it answered 403). Defining a cluster is registry work behind
        # CLUSTER_ASSIGN, which the CD holds.
        self.assertContains(response, "Create Cluster")
        self.assertNotContains(response, "Schedule training for CDCD Directory Cluster")

        self.client.force_login(self.cceo)
        cceo_response = self.client.get("/clusters")
        self.assertEqual(cceo_response.status_code, 200)
        self.assertTemplateUsed(cceo_response, "partials/clusters/cluster_list.html")

    def test_the_page_header_buttons_are_grouped(self):
        """Separate buttons, organised (owner, 2026-09-26: "keep them up as
        separate buttons but organize them in a professional way"): one
        primary action, outline buttons for the rest, and a hairline before
        Export. Each role gets the buttons its drawers would open for."""

        def header(user):
            self.client.force_login(user)
            body = self.client.get("/clusters").content.decode()
            return body.split('class="edify-page-header__controls"', 1)[1].split(
                "<!-- Messages notifications wrapper -->", 1
            )[0]

        def labels(markup):
            return [
                re.sub(r"<[^>]+>", "", label).strip()
                for label in re.findall(
                    r'class="edify-action-button [^"]*"[^>]*>(.*?)</(?:a|button)>',
                    markup,
                    re.S,
                )
            ]

        cceo = header(self.cceo)
        self.assertNotIn("data-row-actions", cceo)
        self.assertEqual(
            labels(cceo),
            [
                "Create Cluster",
                "Schedule Group Training",
                "Schedule Cluster Meeting",
                "Export",
            ],
        )
        self.assertEqual(cceo.count('class="edify-action-button primary'), 1)
        self.assertLess(
            cceo.index("Schedule Cluster Meeting"),
            cceo.index("edify-page-header__sep"),
        )
        self.assertLess(cceo.index("edify-page-header__sep"), cceo.index("Export"))
        self.assertEqual(labels(header(self.cd)), ["Create Cluster", "Export"])

    def test_cd_filter_refresh_returns_the_same_cards(self):
        self.client.force_login(self.cd)
        response = self.client.get("/clusters?q=CDCD", HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/clusters/cluster_card.html")
        self.assertContains(response, "CDCD Directory Cluster")
