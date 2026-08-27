"""The demo partner role-bridge must fail closed when its setting is absent.

`resolve_partner_ids` has a fallback for the seeded demo: a partner user with no
canonical `Partner.userId` link is pinned to the first active partner. That
fallback is a cross-tenant grant — it hands an unlinked user an organisation
they have no link to — so it is gated on PARTNER_ROLE_BRIDGE, which prod.py
refuses to let be true.

Every shipped settings module defines the flag, so the `getattr` default is only
ever reached by a settings module that forgot it. The default therefore decides
what happens in exactly the case nobody thought about, and it used to be `True`:
a missing flag granted the bridge rather than withholding it. These tests pin
the direction — absent means off — and keep the demo behaviour honest when the
flag is deliberately on.
"""

from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase

from apps.core.scoping import resolve_partner_ids

_ABSENT = object()


def _partner_model_with_an_active_partner():
    """A partner model where nobody is linked but one active partner exists.

    Both lookups in `resolve_partner_ids` share the same
    `.filter(...).order_by(...).first()` shape, so the branch is selected by
    which kwargs arrive: `user_id` is the canonical link, its absence is the
    bridge's "any active partner" sweep.
    """

    def _filter(**kwargs):
        queryset = mock.Mock()
        linked_lookup = "user_id" in kwargs
        queryset.order_by.return_value.first.return_value = (
            None if linked_lookup else mock.Mock(id="first-active-partner")
        )
        return queryset

    model = mock.Mock()
    model.objects.filter.side_effect = _filter
    return model


class PartnerRoleBridgeDefaultTest(SimpleTestCase):
    def setUp(self):
        self.user = mock.Mock(user_id="unlinked-partner-user")
        self.patcher = mock.patch(
            "apps.core.scoping._get_partner_model",
            return_value=_partner_model_with_an_active_partner(),
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _with_flag(self, value):
        """Set, or genuinely remove, PARTNER_ROLE_BRIDGE for one test.

        `override_settings` can only set a value; the case that matters here is
        the attribute being missing altogether, which is what exercises the
        `getattr` default.
        """
        original = getattr(settings, "PARTNER_ROLE_BRIDGE", _ABSENT)

        def restore():
            if original is _ABSENT:
                if hasattr(settings, "PARTNER_ROLE_BRIDGE"):
                    delattr(settings, "PARTNER_ROLE_BRIDGE")
            else:
                settings.PARTNER_ROLE_BRIDGE = original

        self.addCleanup(restore)
        if value is _ABSENT:
            if hasattr(settings, "PARTNER_ROLE_BRIDGE"):
                delattr(settings, "PARTNER_ROLE_BRIDGE")
        else:
            settings.PARTNER_ROLE_BRIDGE = value

    def test_an_absent_flag_withholds_the_bridge(self):
        """A settings module that forgot the flag must not grant a partner."""
        self._with_flag(_ABSENT)
        self.assertEqual(
            resolve_partner_ids(self.user),
            [],
            "an unlinked partner user was pinned to an organisation because "
            "PARTNER_ROLE_BRIDGE was missing rather than false",
        )

    def test_the_flag_off_withholds_the_bridge(self):
        self._with_flag(False)
        self.assertEqual(resolve_partner_ids(self.user), [])

    def test_the_flag_on_still_pins_to_the_first_active_partner(self):
        """The demo convenience still works when it is asked for.

        Without this the test above would pass just as well against a bridge
        that had been deleted, which is a different change from the one made.
        """
        self._with_flag(True)
        self.assertEqual(resolve_partner_ids(self.user), ["first-active-partner"])
