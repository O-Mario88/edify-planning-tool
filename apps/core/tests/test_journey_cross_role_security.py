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

**It asks at two layers, and the second one was added late.** The first version
of this sweep called services directly, and the traceability matrix later found
that neither this journey nor any of the other nineteen ever issued an HTTP
request — so the platform's 810 route-level authority gates were exercised by no
mandated journey at all (JRN-01). That is a strange gap for a journey whose
whole subject is unauthorized access, because the route is the layer a real
attacker actually reaches. `_route_workflows` now attempts the same acts through
the real endpoints, logged in as each role, and the two sweeps are kept separate
on purpose: the door and the act are different questions, and SEC-01 was a
defect in neither one but in the join between them.

The school edit drawer probe is that join, reproduced. A Programme Lead who
supervises the school's CCEO passes the read gate — correctly; that is what
oversight is for — and must still be refused a POST that rewrites ownership.
Delete `assert_may_write_school` from the view and this test reports the
takeover with a 200.

`MINIMUM_WORKFLOWS` and `MINIMUM_ROUTES` guard the tables themselves. A denial
sweep is only as good as its coverage, and coverage that can quietly shrink is
the failure mode this whole journey exists to catch.
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

#: The same rule for the route table. Separate because the two sweeps answer
#: two different questions and one must not be allowed to cover for the other.
MINIMUM_ROUTES = 4

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

    # ── the same acts, at the door ───────────────────────────────────────
    def _route_workflows(self):
        """(name, roles the ROUTE should admit, method, path, payload).

        JRN-01: until this existed, no mandated journey issued a single HTTP
        request, so the platform's 810 route-level authority gates were
        exercised by none of them. The table above proves the *services*
        refuse. This one proves the *routes* do — and the two are different
        questions, because SEC-01 was a defect in neither half but in the join
        between them.

        Two conventions keep these probes honest:

        * The "allowed" set is the set the ROUTE should admit, which is not
          always the set that may perform the act. Both money routes admit
          Admin and then the service refuses it — that is the separation of
          duties working, not a gap, and the two sweeps state the two layers
          separately rather than blurring them.
        * Where a probe names a record that does not exist, that is
          deliberate. ``require_page_permission`` runs before the view body,
          so an unauthorised role is refused at the door either way, and an
          authorised one reaches a harmless 404 instead of moving real money
          to prove the door opened.
        """
        return (
            (
                # THE SEC-01 endpoint, at the layer SEC-01 lived in. The
                # Programme Lead supervises this school's CCEO, passes the
                # read gate that oversight needs, and must still be refused
                # the write that rewrites ownership. The payload names the
                # Programme Lead as the new owner, so any unrefused write by
                # anyone shows up in the ownership assertion below as the
                # takeover SEC-01 actually allowed.
                "school edit drawer",
                {"CCEO", "CountryDirector", "Admin"},
                "post",
                f"/schools/{self.school.id}/edit-drawer",
                {
                    "school_id": "XR-SCH",
                    "name": "XR School",
                    "school_type": "client",
                    "account_owner_id": self.by_role["Program Lead"].staff_profile.id,
                },
            ),
            (
                # Admin is admitted to the disbursements PAGE and refused
                # this ACT, by _lacks_payment_authority inside the view — the
                # FIN-03 fix, one layer below the door. So the set a probe at
                # this route must state is the set the route as a whole
                # admits, which is the Accountant alone.
                "partner payment action",
                {"Accountant"},
                "post",
                "/accounts/partner-payments/xr-no-such-activity/pay",
                {
                    "partner_name": "XR Partner",
                    "amount_paid": "100000",
                    "payment_method": "Bank Transfer",
                    "payment_reference": "XR-REF",
                },
            ),
            (
                # Here the separation of duties sits in the service instead,
                # so the door admits Admin and the act refuses it. Both
                # shapes are correct; stating them separately is what stops
                # this table quietly agreeing with whatever the code does.
                "weekly fund disbursement action",
                {"Accountant", "Admin"},
                "post",
                "/fund-requests/weekly/xr-no-such-request/disburse",
                {},
            ),
            (
                "disbursements register",
                {"Accountant", "Admin"},
                "get",
                "/disbursements",
                {},
            ),
        )

    def _assert_refused_at_the_door(self, response, *, where, role):
        """Refusal has two spellings here, and both are the platform's own.

        ``render_access_denied`` returns 403 for an action or an HTMX request
        and, for a plain page GET, a flash message plus a redirect to the
        dashboard. A probe demanding 403 everywhere would report the page
        contract as a security hole. What must never happen is the request
        being served.
        """
        if response.status_code == 403:
            return
        location = response.headers.get("Location", "")
        if response.status_code == 302 and location.startswith("/dashboard"):
            return
        self.fail(
            f"{role} reached '{where}' with {response.status_code} "
            f"{location and f'-> {location} '}instead of a refusal. The route "
            "is the layer a real user actually touches."
        )

    # ── the sweep ────────────────────────────────────────────────────────
    def test_the_route_table_has_not_shrunk(self):
        self.assertGreaterEqual(
            len(self._route_workflows()),
            MINIMUM_ROUTES,
            "the door sweep covers fewer routes than it used to. JRN-01 was "
            "the finding that no mandated journey touched the request path at "
            "all; letting this table shrink walks back toward it.",
        )

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

        # The same question at the door. The mandate's wording for this
        # journey is "attempt unauthorized access for every sensitive
        # workflow", and until JRN-01 was found this test read that as the
        # service layer alone.
        owner_before = self.school.account_owner_id
        for name, allowed, method, path, payload in self._route_workflows():
            for role in EdifyRole.values():
                if role in allowed:
                    continue
                with self.subTest(route=name, role=role):
                    self.client.force_login(self.by_role[role])
                    try:
                        response = getattr(self.client, method)(path, payload)
                    finally:
                        self.client.logout()
                    self._assert_refused_at_the_door(
                        response,
                        where=f"{name} ({method.upper()} {path})",
                        role=role,
                    )

        self.school.refresh_from_db()
        self.assertEqual(
            self.school.account_owner_id,
            owner_before,
            "a refused request still moved the school's ownership. A 403 that "
            "does not also leave the record alone is not a refusal — this is "
            "exactly the takeover SEC-01 allowed.",
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

    def test_the_permitted_role_is_not_refused_at_the_door_either(self):
        """The same guard, for the route probes.

        A door sweep where every path 404s would refuse everyone and report
        perfect security. So each route must admit the role it is meant to
        admit: not 403, whatever else it then does. What the view does after
        the door is the service sweep's question, not this one's.
        """
        checked = 0
        for name, allowed, method, path, payload in self._route_workflows():
            for role in sorted(allowed):
                actor = self.by_role.get(role)
                if actor is None:
                    continue
                checked += 1
                with self.subTest(route=name, role=role):
                    self.client.force_login(actor)
                    try:
                        response = getattr(self.client, method)(path, payload)
                    finally:
                        self.client.logout()
                    self.assertNotEqual(
                        response.status_code,
                        403,
                        f"the permitted role {role} was refused at the door "
                        f"for '{name}'. This probe denies everyone, so its "
                        "denial sweep proves nothing.",
                    )
        self.assertGreaterEqual(
            checked, MINIMUM_ROUTES, "no route was checked positively"
        )
