from django.db import migrations

REPOINTED = {
    # A withdrawn school action: the recipient's own action queue.
    "/planning/my-actions": "/actions/mine",
    # A school closure with committed funds: the accountability queue.
    "/finance/accountability": "/accounts/accountability",
    "/ia/verification-queue": "/ia/verification/",
    "/budget/amendments": "/accounts/budget-amendments",
}


def repoint(apps, schema_editor):
    """Delivered notices keep the link they were sent with; these four routes
    never existed, so repair the notices in place (2026-09-13 audit)."""
    Notification = apps.get_model("notifications", "Notification")
    for dead, live in REPOINTED.items():
        Notification.objects.filter(target_route=dead).update(target_route=live)


class Migration(migrations.Migration):
    dependencies = [("notifications", "0004_repoint_priority_cycle_notices")]

    operations = [migrations.RunPython(repoint, migrations.RunPython.noop)]
