"""SEC-A4 — who may change a Master Priority source figure.

`_assert_master_editor` reads `milestones.define` from the permission matrix,
and its refusal text states the rule it means to enforce: "Master Priority
figures are set by the Country Director and Impact Assessment." The grant did
not match the sentence. Admin held `milestones.define` by default, so the
technical super-role could adjust the number, the Core/Client split, the
participants guidance and the allocation method on a country target — values
that flow into distribution, planning, achievement and performance.

The audit mandate says the same thing from the other side ("RVP and Admin
remain read-only for business values"), and the codebase had already applied
that doctrine to this role once, when AUD-007 took the country money chain off
Admin because approving a budget and then verifying the work it paid for is
one actor holding both ends.

The RegionalVicePresident also holds it. That one is NOT decided here:
`apps/hr/priority_cascade.py` has the RVP authoring strategy, which is a real
source pointing the other way, so it is recorded as CONFLICT-003 for the
product owner. This test pins what is settled and deliberately leaves the
RVP's grant as it is, so that resolving the conflict is a decision somebody
makes rather than a side effect of this file.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.core.rbac import EdifyRole, Permission, permissions_for_role


def _holds(role: str, permission: Permission) -> bool:
    return permission.value in set(permissions_for_role(role))


class MasterPriorityEditorAuthorityTest(SimpleTestCase):
    def test_the_country_director_and_impact_assessment_may_edit(self):
        """The two roles the guard's refusal text names."""
        for role in (
            EdifyRole.COUNTRY_DIRECTOR.value,
            EdifyRole.IMPACT_ASSESSMENT.value,
        ):
            self.assertTrue(_holds(role, Permission.MILESTONES_DEFINE), role)

    def test_admin_may_not_edit_a_master_priority_source_figure(self):
        self.assertFalse(
            _holds(EdifyRole.ADMIN.value, Permission.MILESTONES_DEFINE),
            "the technical super-role must not hold a governed business value",
        )

    def test_delivery_roles_may_not_edit(self):
        for role in (
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            EdifyRole.CCEO.value,
        ):
            self.assertFalse(_holds(role, Permission.MILESTONES_DEFINE), role)

    def test_publication_stays_with_the_country_director_alone(self):
        """Editing is separable from publishing, and must stay so."""
        for role in (
            EdifyRole.IMPACT_ASSESSMENT.value,
            EdifyRole.ADMIN.value,
        ):
            self.assertFalse(
                _holds(role, Permission.STRATEGIC_PRIORITIES_APPROVE)
                and _holds(role, Permission.MILESTONES_DEFINE),
                f"{role} would hold both authorship and approval",
            )
