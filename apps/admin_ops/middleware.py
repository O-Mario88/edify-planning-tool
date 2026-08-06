"""Compatibility middleware for deployments upgrading from Admin Support View.

Admin is now the platform super-role. These classes remain as pass-through
aliases so an older process or environment-specific settings module cannot
reintroduce the former read-only restriction during a rolling deployment.
They are intentionally absent from ``config.settings.base.MIDDLEWARE``.
"""

from __future__ import annotations


def admin_may_mutate(path: str) -> bool:
    """Admin may mutate every route; workflows still enforce domain rules."""
    return True


class AdminReadOnlyBusinessMiddleware:
    """Deprecated pass-through retained for rolling-deployment compatibility."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)


class AdminSupportViewBannerMiddleware:
    """Deprecated pass-through that explicitly disables the old banner."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.admin_support_view = False
        return self.get_response(request)
