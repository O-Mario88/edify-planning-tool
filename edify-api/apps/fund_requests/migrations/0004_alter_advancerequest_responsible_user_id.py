# Convergence migration: ensure advance_request.responsible_user_id is nullable.
#
# A prior version of migration 0003 created AdvanceRequest with a non-null
# responsible_user_id; the field was later made nullable (pure-partner activities
# have no staff responsible at creation time). Databases that applied the OLD
# 0003 still carry the NOT NULL constraint. RunSQL is used (not AlterField)
# because Django's migration state already records the field as nullable, so an
# AlterField would be a no-op — but the live column may still be NOT NULL. The
# raw ALTER is idempotent (a no-op if the column is already nullable).
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("fund_requests", "0003_advancerequest"),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE advance_request ALTER COLUMN responsible_user_id DROP NOT NULL;",
            reverse_sql=migrations.RunSQL.noop,
            # No-op on backends that don't have the table (e.g. fresh test DB).
        ),
    ]

