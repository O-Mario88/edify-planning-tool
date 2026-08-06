"""
Middleware to enforce password change for users with must_change_password=True.

When this flag is set (e.g. after an admin sets/resets a password), the user
is redirected to /change-password on every request until they comply. Only
/change-password, /logout, /login, and static file requests are exempted.
"""

from django.shortcuts import redirect


# Paths that are always allowed, even when must_change_password is True.
_EXEMPT_PATHS = (
    "/change-password",
    "/logout",
    "/login",
    "/static/",
    "/favicon.ico",
)


class ForcePasswordChangeMiddleware:
    """Intercept all requests for authenticated users who must change their password."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and getattr(request.user, "must_change_password", False)
            and not any(request.path.startswith(p) for p in _EXEMPT_PATHS)
        ):
            return redirect("/change-password")

        return self.get_response(request)
