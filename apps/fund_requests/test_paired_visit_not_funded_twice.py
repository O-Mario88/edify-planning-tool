"""The paired School Visit is not independently fundable (FUND-01).

One in-school Training decision creates two governed records: a TS- Training
and an SVE- School Visit. They describe the same delivery — the visit is the
Training's evidence and Salesforce twin, not a second piece of work. The
Training carries the visit-equivalent cost, so funding the twin as well claims
the same money twice.

`fund_requests.services.submit` enforces that with one line:

    qs = qs.exclude(paired_in_school_training__isnull=False)

Nothing tested it. `paired_in_school_training` appeared in four production
exclusions — this one, two system-health surfaces and the costing repair
command — and in no test at all; the 255-line suite that shipped with the
pairing feature never named it. Deleting the line and running
`apps.fund_requests` plus `apps.planning.test_in_school_training_pair` gave
285 tests, OK. The guard against double-funding was deletable in silence.

That is this audit's recurring defect class arriving from the other side.
Every earlier instance was a reader with no writer — a screen that could never
show anything. This is a money rule with no test: the behaviour is right and
nothing holds it there.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.fund_requests import services
from apps.fund_requests.models import FundRequestItem
from apps.geography.models import District, Region
from apps.schools.models import School

MONTH = 1
TRAINING_COST = 300_000
VISIT_COST = 120_000


class PairedVisitIsNotFundedTwiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        region = Region.objects.create(name="Pair Fund Region")
        district = District.objects.create(name="Pair Fund District", region=region)
        cls.school = School.objects.create(
            school_id="SCH-PAIR-FUND",
            name="Pair Fund Primary",
            region=region,
            district=district,
        )
        cls.owner = User.objects.create(
            id="pair-fund-owner",
            email="pair-fund-owner@edify.org",
            name="Pair Fund Owner",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        # Scope resolution reads STAFF ids, not user ids. Both the profile
        # and `responsible_staff_id` must be the staff id — set the user id
        # there and the scope filter drops the activities, leaving every
        # assertion below passing against an empty request.
        cls.staff = StaffProfile.objects.create(
            id="pair-fund-staff", user=cls.owner, title="CCEO"
        )
        planned = date.today()

        # The twin pair, as `schedule_in_school_training_pair` builds it: the
        # visit is created first, then the training points at it, so the
        # visit is the one carrying `paired_in_school_training`.
        cls.visit = cls._activity("school_visit", planned)
        cls.training = cls._activity("in_school_training", planned)
        cls.training.paired_school_visit = cls.visit
        cls.training.save(update_fields=["paired_school_visit", "updated_at"])

        # Both carry cost lines. That is the point: if the exclusion goes, the
        # visit's line is real money the request would ask for a second time.
        cls.training_line = cls._line(cls.training, "Training delivery", TRAINING_COST)
        cls.visit_line = cls._line(cls.visit, "Visit transport", VISIT_COST)

    @classmethod
    def _activity(cls, activity_type, planned):
        return Activity.objects.create(
            activity_type=activity_type,
            delivery_type="staff",
            status="scheduled",
            fy=cls.fy,
            month=MONTH,
            school=cls.school,
            responsible_staff_id=cls.staff.id,
            planned_date=planned,
            scheduled_date=planned,
        )

    @classmethod
    def _line(cls, activity, description, amount):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            responsible_user=cls.owner.id,
            planned_date=activity.planned_date,
            description=description,
            unit_cost=amount,
            quantity=1,
            amount=amount,
        )

    def test_the_fixture_really_is_a_pair(self):
        """Guard the guard: if the link is not set, the test below proves nothing."""
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.paired_in_school_training.id, self.training.id)

    def _submit(self):
        result = services.submit(
            {"period": "monthly", "fy": self.fy, "month": MONTH}, self.owner
        )
        items = FundRequestItem.objects.filter(fund_request_id=result["id"])
        return result, items

    def test_the_twin_visit_never_enters_the_request(self):
        result, items = self._submit()

        funded_activity_ids = set(items.values_list("activity_id", flat=True))
        self.assertIn(self.training.id, funded_activity_ids)
        self.assertNotIn(
            self.visit.id,
            funded_activity_ids,
            "the paired School Visit was funded as if it were separate work — "
            "its cost is already inside the Training's",
        )

    def test_the_total_is_the_training_alone(self):
        """Asserted on the money, not only on membership.

        The id check above would still pass if the visit's line were attributed
        to the training. The sum is what the accountant releases.
        """
        result, _items = self._submit()

        self.assertEqual(result["totalAmount"], TRAINING_COST)
        self.assertNotEqual(
            result["totalAmount"],
            TRAINING_COST + VISIT_COST,
            "the twin's cost was added to the request",
        )

    def test_an_unpaired_visit_is_still_funded(self):
        """The exclusion must be the pairing, not school visits in general.

        Without this, `exclude(activity_type="school_visit")` would pass every
        assertion above while defunding ordinary field support.
        """
        solo = self._activity("school_visit", date.today())
        self._line(solo, "Ordinary support transport", VISIT_COST)

        result, items = self._submit()

        self.assertIn(solo.id, set(items.values_list("activity_id", flat=True)))
        self.assertEqual(result["totalAmount"], TRAINING_COST + VISIT_COST)
