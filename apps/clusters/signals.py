"""Keep every cluster's PRIMARY catchment equal to its own district.

A receiver rather than a call in each creator: clusters are created by the
service, by ``create_from_school``, by seeding and by imports, and a cluster
missing its primary row would still work (``serving_match`` falls back on the
cluster's own district) but would read as serving nothing on the Catchments
page. Cluster saves are rare, so the one lookup per save costs nothing.
"""

from __future__ import annotations

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Cluster


@receiver(post_save, sender=Cluster, dispatch_uid="cluster_primary_catchment")
def keep_primary_catchment(sender, instance, raw=False, **kwargs):
    if raw or instance.deleted_at or not instance.district_id:
        return
    from .catchment import ensure_primary_catchment

    ensure_primary_catchment(instance, "system")
