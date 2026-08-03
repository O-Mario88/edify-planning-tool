from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import RefreshToken, User
from apps.core.rbac import EdifyRole
from apps.core.security import generate_token, hash_token


class PasswordResetPageTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="reset@edify.test",
            name="Reset User",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="OldPassword1!",
            is_active=True,
            status="active",
        )
        self.token = generate_token()
        self.user.password_reset_token_hash = hash_token(self.token)
        self.user.password_reset_expires = timezone.now() + timezone.timedelta(
            minutes=45
        )
        self.user.save(
            update_fields=["password_reset_token_hash", "password_reset_expires"]
        )

    def test_valid_link_renders_accessible_csrf_protected_form(self):
        response = self.client.get(f"/reset-password?token={self.token}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, f'name="token" value="{self.token}"')
        self.assertContains(response, 'autocomplete="new-password"', count=2)
        self.assertContains(response, 'aria-describedby="password-requirements')

    def test_invalid_or_expired_link_does_not_render_password_fields(self):
        response = self.client.get("/reset-password?token=not-a-valid-token")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "invalid or has expired")
        self.assertNotContains(response, 'name="password"')

        self.user.password_reset_expires = timezone.now() - timezone.timedelta(
            seconds=1
        )
        self.user.save(update_fields=["password_reset_expires"])
        expired = self.client.get(f"/reset-password?token={self.token}")
        self.assertContains(expired, "invalid or has expired")
        self.assertNotContains(expired, 'name="password"')

    def test_reset_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            "/reset-password",
            {
                "token": self.token,
                "password": "NewPassword2!",
                "confirm": "NewPassword2!",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_valid_post_changes_password_consumes_token_and_shows_confirmation(self):
        refresh = RefreshToken.objects.create(
            user=self.user,
            token_hash="a" * 64,
            expires_at=timezone.now() + timezone.timedelta(days=1),
        )
        client = Client(enforce_csrf_checks=True)
        get_response = client.get(f"/reset-password?token={self.token}")
        csrf_token = get_response.cookies["csrftoken"].value

        response = client.post(
            "/reset-password",
            {
                "csrfmiddlewaretoken": csrf_token,
                "token": self.token,
                "password": "NewPassword2!",
                "confirm": "NewPassword2!",
            },
            follow=True,
        )

        self.assertRedirects(response, "/login")
        self.assertContains(response, "Your password has been reset")
        self.user.refresh_from_db()
        refresh.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPassword2!"))
        self.assertIsNone(self.user.password_reset_token_hash)
        self.assertIsNone(self.user.password_reset_expires)
        self.assertIsNotNone(refresh.revoked_at)

        reused = self.client.get(f"/reset-password?token={self.token}")
        self.assertContains(reused, "invalid or has expired")

    def test_validation_failure_keeps_token_available_for_retry(self):
        response = self.client.post(
            "/reset-password",
            {
                "token": self.token,
                "password": "NewPassword2!",
                "confirm": "DifferentPassword3!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match.")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("OldPassword1!"))
        self.assertEqual(self.user.password_reset_token_hash, hash_token(self.token))
