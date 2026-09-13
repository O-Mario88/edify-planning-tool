from django.db import migrations


def repoint(apps, schema_editor):
    """FY priority-setting notices sent HR and Admin to /hr/performance, a
    route that never existed; the priority cycle lives on the HR performance
    console. Delivered notices keep their link, so repair them in place."""
    Notification = apps.get_model("notifications", "Notification")
    Notification.objects.filter(target_route="/hr/performance").update(
        target_route="/hr/performance-cycle"
    )


class Migration(migrations.Migration):
    dependencies = [("notifications", "0003_notification_resolution")]

    operations = [migrations.RunPython(repoint, migrations.RunPython.noop)]
