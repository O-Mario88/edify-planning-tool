"""Index the column the target ledger credits SSA collection by.

`TargetAchievementService.rebuild()` filters `collected_by_user_id` once per
person. Unindexed that is a sequential scan of every assessment ever taken, per
person — on a Country Director dashboard rebuilding 48 CCEOs it read 39,000
rows 48 times to find a handful each, which was the single most expensive
query on the page.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0018_relink_school_geography"),
        ("ssa", "0006_alter_ssascore_intervention"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="ssarecord",
            index=models.Index(
                fields=["collected_by_user_id"], name="ssa_record_collect_18c247_idx"
            ),
        ),
    ]
