"""Who may say what an activity is for, and what happens to what it used to say."""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activity_catalogue import intervention_mapping as im
from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ActivityInterventionMapping,
    MappingRelationship,
    MappingStatus,
)
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole

CB = "christlike_behaviour"
LEADERSHIP = "leadership"


def _user(role, email):
    user = User.objects.create_user(
        email=email, name=email, roles=[role], active_role=role, password="x"
    )
    StaffProfile.objects.create(user=user, title=role)
    return user


class MappingFixture(TestCase):
    def setUp(self):
        self.ia = _user(EdifyRole.IMPACT_ASSESSMENT.value, "ia-map@t.org")
        self.cd = _user(EdifyRole.COUNTRY_DIRECTOR.value, "cd-map@t.org")
        self.item = ActivityCatalogueItem.objects.create(
            stable_code="CC_SEL_TEST",
            source_name="CC-SEL",
            display_name="CC-SEL",
            activity_type="training",
        )


class AuthorityTests(MappingFixture):
    def test_impact_assessment_may_set_the_mapping(self):
        mapping = im.link_intervention(self.ia, self.item, {"intervention": CB})

        self.assertEqual(mapping.intervention, CB)
        self.assertEqual(mapping.relationship, MappingRelationship.PRIMARY)
        self.assertEqual(mapping.status, MappingStatus.DRAFT)

    def test_the_country_director_may_not(self):
        # Authority over a country target is not authority over what counts
        # as that target having worked.
        with self.assertRaises(Forbidden):
            im.link_intervention(self.cd, self.item, {"intervention": CB})

    def test_an_intervention_outside_the_canonical_eight_is_refused(self):
        with self.assertRaises(BadRequest):
            im.link_intervention(self.ia, self.item, {"intervention": "vibes"})


class PrimaryTests(MappingFixture):
    def test_a_second_primary_supersedes_the_first_rather_than_joining_it(self):
        first = im.link_intervention(self.ia, self.item, {"intervention": CB})
        im.publish(self.ia, first)

        im.link_intervention(self.ia, self.item, {"intervention": LEADERSHIP})

        first.refresh_from_db()
        self.assertEqual(first.status, MappingStatus.SUPERSEDED)
        self.assertFalse(first.active)
        live = ActivityInterventionMapping.objects.filter(
            catalogue_item=self.item, active=True
        )
        self.assertEqual(live.count(), 1)
        self.assertEqual(live.first().intervention, LEADERSHIP)

    def test_a_secondary_sits_alongside_the_primary(self):
        im.link_intervention(self.ia, self.item, {"intervention": CB})
        im.link_intervention(
            self.ia,
            self.item,
            {
                "intervention": LEADERSHIP,
                "relationship": MappingRelationship.SECONDARY,
            },
        )

        resolved = im.mapping_for(self.item)

        self.assertEqual(resolved["primary"].intervention, CB)
        self.assertEqual([m.intervention for m in resolved["secondary"]], [LEADERSHIP])

    def test_republishing_a_changed_rule_keeps_the_old_version_readable(self):
        first = im.link_intervention(
            self.ia, self.item, {"intervention": CB, "follow_up_min_days": 90}
        )
        im.publish(self.ia, first)

        second = im.link_intervention(
            self.ia, self.item, {"intervention": CB, "follow_up_min_days": 180}
        )

        first.refresh_from_db()
        # The rule a finished activity was measured under still says 90.
        self.assertEqual(first.follow_up_min_days, 90)
        self.assertEqual(first.status, MappingStatus.SUPERSEDED)
        self.assertEqual(second.version, first.version + 1)


class WindowTests(MappingFixture):
    def test_a_window_that_ends_before_it_opens_is_refused(self):
        with self.assertRaises(BadRequest):
            im.link_intervention(
                self.ia,
                self.item,
                {
                    "intervention": CB,
                    "follow_up_min_days": 365,
                    "follow_up_max_days": 90,
                },
            )

    def test_no_threshold_is_stored_when_none_was_approved(self):
        mapping = im.link_intervention(self.ia, self.item, {"intervention": CB})

        # Nullable on purpose: a default would silently reclassify a real
        # half-point gain as no change.
        self.assertIsNone(mapping.min_meaningful_change)


class NotMeasuredTests(MappingFixture):
    def test_an_administrative_activity_can_say_so_with_a_reason(self):
        mapping = im.classify_not_ssa_measured(
            self.ia, self.item, "Internal planning meeting; improves no school score."
        )

        self.assertIsNone(mapping.intervention)
        self.assertTrue(im.mapping_for(self.item)["not_ssa_measured"])

    def test_an_unexplained_exemption_is_refused(self):
        # Indistinguishable from an oversight.
        with self.assertRaises(BadRequest):
            im.classify_not_ssa_measured(self.ia, self.item, "   ")

    def test_an_item_with_no_mapping_reports_that_it_needs_one(self):
        self.assertTrue(im.mapping_for(self.item)["needs_mapping"])
