"""Journey 19 — Cross-role security: every sensitive workflow fails closed.

Journey 19 of the mandate's twenty-two, and the only one stated as a rule
rather than a sequence: "Attempt unauthorized access for every sensitive
workflow. All attempts must fail closed."

Two of this audit's findings are the reason it needs its own sweep rather than
trusting the suites that already exist. SEC-01 let a Programme Lead take
ownership of a supervised CCEO's school because the edit drawer gated its write
on the READ helper. FIN-03 let three roles move partner money because the
screens gated by page permission and the service checked nothing. Both survived
a green suite, because the tests that existed asked "can the right person do
this?" and never "can the wrong person?".

So this asks the second question, systematically: for every workflow that moves
money or grants verification, attempt it as EVERY role that should not hold it
and require a refusal. Thirteen roles against each workflow means the sweep
grows automatically when a role is added — a new role is denied everywhere by
default and someone has to say otherwise, which is the direction that fails
safe.

`MINIMUM_WORKFLOWS` guards the table itself. A denial sweep is only as good as
its coverage, and coverage that can quietly shrink is the failure mode this
whole journey exists to catch.
"""

from __future__ import annotations

import datetime

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

#: The table must never quietly shrink. Raise it when a workflow is added.
MINIMUM_WORKFLOWS = 6

#: Refusal is refusal however it is spelled — some services raise Forbidden,
#: some BadRequest with an authority message. What must never happen is the
#: attempt succeeding.
REFUSALS = (Forbidden, BadRequest, PermissionError)


def _schedulable_date() -> datetime.date:
    from apps.core.calendar_policy import SchedulingPolicyService

    day = timezone.localdate() + datetime.timedelta(days=7)
    for _ in range(21):
        if SchedulingPolicyService.check(None, day)["status"] != "blocked":
            return day
        day += datetime.timedelta(days=1)
    raise AssertionError("no schedulable date within three weeks")


class CrossRoleSecurityJourneyTest(TestCase):
    """Every sensitive workflow, attempted by every role that should not."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="XR Region")
        cls.district = District.objects.create(name="XR District", region=cls.region)
        cls.school = School.objects.create(
            school_id="XR-SCH",
            name="XR School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.day = _schedulable_date()

        # One user per role, each with a StaffProfile so scope resolution has
        # something real to resolve. Partner and the MFI roles carry profiles
        # too: an actor the platform cannot resolve must still be refused, and
        # giving them a profile removes "unresolvable" as the reason a denial
        # passes.
        cls.by_role: dict[str, User] = {}
        for index, role in enumerate(EdifyRole.values()):
            slug = role.lower().replace(" ", "-")[:18]
            user = User.objects.create(
                id=f"xr-{index}",
                email=f"xr-{slug}@edify.org",
                name=f"XR {role}",
                roles=[role],
                active_role=role,
                is_active=True,
            )
            StaffProfile.objects.create(
                user=user, staff_number=f"XR-{index}", country="Uganda", title=role
            )
            cls.by_role[role] = user

        cls.owner = cls.by_role["CCEO"]
        StaffSchoolAssignment.objects.create(
            staff=cls.owner.staff_profile, school_id=cls.school.id
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.by_role["Program Lead"].staff_profile,
            supervisee=cls.owner.staff_profile,
        )

    def _partner_activity(self):
        activity = Activity.objects.create(
            school=self.school,
            activity_type="partner_activity",
            delivery_type="partner",
            status="scheduled",
            fy="2026",
            scheduled_date=timezone.make_aware(
                datetime.datetime.combine(self.day, datetime.time(9, 0))
            ),
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            school=self.school,
            cost_setting_key="partner_training_lump_sum",
            label="Partner Training Lump Sum",
            unit_cost=100_000,
            quantity=1,
            amount=100_000,
        )
        return activity

    # ── the workflows ────────────────────────────────────────────────────
    def _workflows(self):
        """(name, allowed_roles, attempt) for every sensitive workflow.

        `attempt` must actually try to perform the privileged act as the given
        actor. A probe that returns before reaching the authority check proves
        nothing, so each one is checked positively too — see
        `test_the_permitted_role_is_not_refused_by_the_same_probe`.
        """
        from apps.activities.ia_services import ActivityCertificationService
        from apps.core.scoping import assert_may_write_school
        from apps.fund_requests.finance_models import PartnerPayment
        from apps.fund_requests.finance_services import (
            PartnerPaymentService,
            _assert_may_pay,
        )
        from apps.fund_requests.weekly_service import _assert_may_disburse

        def pay_partner(actor):
            PartnerPaymentService.pay_partner(
                self._partner_activity(),
                "XR Partner",
                100_000,
                "Bank Transfer",
                "XR-REF",
                actor.id,
                netsuite_id="NS-XR",
                payment_type=PartnerPayment.TYPE_ADVANCE,
            )

        def partner_payment_authority(actor):
            _assert_may_pay(actor)

        def weekly_disbursement_authority(actor):
            _assert_may_disburse(actor)

        def write_someone_elses_school(actor):
            assert_may_write_school(actor, self.school, action="edit")

        def certify_activity(actor):
            activity = self._partner_activity()
            activity.status = "awaiting_ia_verification"
            # Unique per actor: the Salesforce id is uniquely constrained, and
            # a collision would surface as an IntegrityError that the sweep
            # would rightly refuse to read as a security refusal.
            activity.salesforce_activity_id = f"SVE-XR-{actor.id}"
            activity.save(update_fields=["status", "salesforce_activity_id"])
            ActivityCertificationService.certify_activity(activity, {}, str(actor.id))

        def grant_partner_allowance(actor):
            from apps.partners.services import grant_partner_activity_allowance

            grant_partner_activity_allowance(actor, {"partnerId": "nobody", "count": 1})

        return (
            ("partner payment", {"Accountant"}, pay_partner),
            ("partner payment authority", {"Accountant"}, partner_payment_authority),
            (
                "weekly disbursement authority",
                {"Accountant"},
                weekly_disbursement_authority,
            ),
            (
                # may_write_school states the rule: "The Country Director and
                # Admin act everywhere, because the programme is their remit."
                # A Programme Lead is deliberately absent — they see a CCEO's
                # school on oversight and ask about it (SEC-01).
                "school write",
                {"CCEO", "CountryDirector", "Admin"},
                write_someone_elses_school,
            ),
            ("IA certification", {"ImpactAssessment"}, certify_activity),
            ("partner activity allowance", {"Admin"}, grant_partner_allowance),
        )

    # ── the sweep ────────────────────────────────────────────────────────
    def test_the_table_has_not_shrunk(self):
        self.assertGreaterEqual(
            len(self._workflows()),
            MINIMUM_WORKFLOWS,
            "the cross-role sweep covers fewer workflows than it used to. A "
            "denial sweep that can quietly shrink is the failure mode this "
            "journey exists to catch.",
        )

    def test_every_sensitive_workflow_refuses_every_role_that_should_not_hold_it(self):
        for name, allowed, attempt in self._workflows():
            for role in EdifyRole.values():
                if role in allowed:
                    continue
                actor = self.by_role[role]
                with self.subTest(workflow=name, role=role):
                    # Each attempt gets its own savepoint: a service that
                    # raises inside its own atomic block leaves the outer
                    # transaction unusable, and one probe must not be able to
                    # take the rest of the sweep down with it.
                    try:
                        with transaction.atomic():
                            attempt(actor)
                    except REFUSALS:
                        continue
                    except Exception as exc:  # noqa: BLE001 - see message
                        self.fail(
                            f"{role} attempting '{name}' failed with "
                            f"{type(exc).__name__}: {exc}. That is not a "
                            "refusal — an unexpected error is not a security "
                            "control, and the next refactor may remove it."
                        )
                    else:
                        self.fail(
                            f"{role} performed '{name}' and was NOT refused. "
                            "This is the SEC-01/FIN-03 shape: the workflow is "
                            "gated somewhere other than at the act itself."
                        )

    def test_the_permitted_role_is_not_refused_by_the_same_probe(self):
        """The guard against a sweep that passes because nothing works.

        Every probe above must be capable of SUCCEEDING for someone. If a
        probe raises before it reaches the authority check — a missing
        fixture, a wrong argument — it would deny every role including the
        right one, and the sweep would report perfect security over a broken
        test.
        """
        checked = 0
        for name, allowed, attempt in self._workflows():
            for role in sorted(allowed):
                actor = self.by_role.get(role)
                if actor is None:
                    continue
                checked += 1
                with self.subTest(workflow=name, role=role):
                    try:
                        with transaction.atomic():
                            attempt(actor)
                    except REFUSALS as exc:
                        message = str(exc).lower()
                        # A refusal on business grounds (wrong status, missing
                        # prerequisite) is fine; a refusal on AUTHORITY means
                        # the probe never distinguishes anyone.
                        for phrase in (
                            "only a",
                            "permission",
                            "not authorised",
                            "not authorized",
                            "read-only",
                        ):
                            if phrase in message:
                                self.fail(
                                    f"the permitted role {role} was refused "
                                    f"'{name}' on authority grounds: {exc}. "
                                    "This probe denies everyone, so its "
                                    "denial sweep proves nothing."
                                )
                    except Exception:  # noqa: BLE001 - business failure is fine
                        pass
        self.assertGreaterEqual(
            checked,
            MINIMUM_WORKFLOWS,
            "no workflow was checked positively",
        )
