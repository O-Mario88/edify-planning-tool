"""A rejected drawer save must not masquerade as a successful redirect."""

import inspect
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, SimpleTestCase

from apps.core.exceptions import BadRequest
from apps.frontend.views.partner_views import partner_member_action


class PartnerRosterDrawerResponseTest(SimpleTestCase):
    def request(self):
        request = RequestFactory().post(
            "/partners/example/members", {"name": "Grace"}, HTTP_HX_REQUEST="true"
        )
        request.user = SimpleNamespace(id="example-user")
        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    @patch(
        "apps.partners.services.add_member", side_effect=BadRequest("Name is required.")
    )
    def test_validation_stays_in_drawer(self, add_member):
        response = inspect.unwrap(partner_member_action)(self.request(), "example")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("HX-Redirect", response)
        self.assertIn(b"Name is required.", response.content)
        self.assertIn(b'role="alert"', response.content)

    @patch(
        "apps.partners.services.add_member", return_value=SimpleNamespace(name="Grace")
    )
    def test_success_keeps_existing_navigation_contract(self, add_member):
        response = inspect.unwrap(partner_member_action)(self.request(), "example")
        self.assertEqual(response.status_code, 204)
        self.assertIn("/partners/example", response["HX-Redirect"])
