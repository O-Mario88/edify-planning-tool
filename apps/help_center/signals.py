from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def seed_canonical_help_content(sender, app_config, **kwargs):
    if app_config.name != "apps.help_center":
        return
    from .services import ensure_canonical_content

    ensure_canonical_content()
