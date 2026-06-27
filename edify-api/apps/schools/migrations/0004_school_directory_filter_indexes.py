"""Generated for performance: the School Directory filters heavily on these
denormalized status fields (cluster_status, current_fy_ssa_status,
planning_readiness, account_owner_status, duplicate_status) which were
previously unindexed — every directory filter + every dashboard/system-health
conditional COUNT scanned the whole school table. These indexes cover the
filter-bar + aggregate paths."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("schools", "0003_school_last_enrollment_date_uploadbatch_created_rows_and_more"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="school",
            index=models.Index(fields=["cluster_status"], name="school_cluster_st_idx"),
        ),
        migrations.AddIndex(
            model_name="school",
            index=models.Index(fields=["current_fy_ssa_status"], name="school_ssa_status_idx"),
        ),
        migrations.AddIndex(
            model_name="school",
            index=models.Index(fields=["planning_readiness"], name="school_plan_ready_idx"),
        ),
        migrations.AddIndex(
            model_name="school",
            index=models.Index(fields=["account_owner_status"], name="school_owner_st_idx"),
        ),
        migrations.AddIndex(
            model_name="school",
            index=models.Index(fields=["duplicate_status"], name="school_dup_status_idx"),
        ),
    ]
