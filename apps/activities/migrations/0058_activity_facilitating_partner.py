# A staff-run group training may be facilitated by a partner, who is paid its
# facilitation fee (owner, 2026-09-26). Nullable and additive: existing work
# has no facilitating partner and is untouched.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0057_backfill_cluster_session_invitations"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="facilitating_partner_id",
            field=models.CharField(blank=True, db_index=True, max_length=30, null=True),
        ),
    ]
