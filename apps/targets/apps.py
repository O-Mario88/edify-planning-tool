from django.apps import AppConfig


class TargetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.targets"
    label = "targets"
    verbose_name = "Edify Targets"

    def ready(self):
        """Open and close the per-request memo store (apps.core.request_cache).

        Bound to the request signals rather than middleware so it also covers
        requests that short-circuit before the middleware chain completes; the
        store is thread-local, so concurrent requests never share one.
        """
        from django.core.signals import request_finished, request_started

        from apps.core import request_cache

        request_started.connect(
            lambda sender, **kw: request_cache.begin(),
            dispatch_uid="edify_request_cache_begin",
            weak=False,
        )
        request_finished.connect(
            lambda sender, **kw: request_cache.end(),
            dispatch_uid="edify_request_cache_end",
            weak=False,
        )
