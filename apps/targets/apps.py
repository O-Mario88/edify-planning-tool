from django.apps import AppConfig


class TargetsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.targets"
    label = "targets"
    verbose_name = "Edify Targets"

    def ready(self):
        """Register reference data, and open/close the per-request memo store.

        The memo store (apps.core.request_cache) is bound to the request
        signals rather than middleware so it also covers requests that
        short-circuit before the middleware chain completes; the store is
        thread-local, so concurrent requests never share one.
        """
        from django.core.signals import request_finished, request_started

        from apps.core import reference_data, request_cache
        from apps.targets.reference import (
            ensure_target_areas,
            target_areas_are_complete,
        )

        # The official target areas. Every personal target, the weighted
        # Overall Progress, and the targets HR writes on approval all resolve
        # through TargetArea.key — an empty table does not raise, it silently
        # produces no targets at all.
        reference_data.register(
            "targets", ensure_target_areas, target_areas_are_complete
        )

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
