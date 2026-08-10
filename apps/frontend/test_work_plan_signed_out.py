"""A signed-out visitor to a Work Plan route gets the sign-in form, not a 403.

366 guarded routes redirect anonymous visitors to /login with their
destination preserved. Six Work Plan routes answered a bare
`HttpResponseForbidden("Sign in first.")` instead, so someone following a
link after their 30-minute session expired lost where they were going and got
an error page telling them to do the thing the rest of the product does for
them automatically.

Mutations are deliberately excluded: a signed-out POST still gets 403, because
redirecting it would drop the body and imply it could be replayed.
"""

from __future__ import annotations

from django.test import TestCase


SAFE_ROUTES = (
    "/work-plan/add",
    "/work-plan/add/preview",
    "/work-plan/export.xlsx",
)
MUTATION_ROUTES = (
    "/work-plan/add/action",
    "/work-plan/submit-to-rvp",
    "/work-plan/rvp-decision",
)


class SignedOutWorkPlanRoutesTest(TestCase):
    def test_safe_routes_redirect_to_login_preserving_the_destination(self):
        for route in SAFE_ROUTES:
            with self.subTest(route=route):
                response = self.client.get(route)

                self.assertEqual(
                    response.status_code,
                    302,
                    f"{route} must send a signed-out visitor to sign in, "
                    "not answer 403 like the rest of the product does not",
                )
                self.assertIn("/login", response["Location"])
                self.assertIn(
                    route,
                    response["Location"],
                    "the destination must survive the round trip through login",
                )

    def test_mutations_still_refuse_rather_than_redirect(self):
        for route in MUTATION_ROUTES:
            with self.subTest(route=route):
                response = self.client.post(route, {})

                self.assertEqual(
                    response.status_code,
                    403,
                    f"{route} is a mutation — a signed-out POST must be refused, "
                    "not bounced to a login page that drops its body",
                )
