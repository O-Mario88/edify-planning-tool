"""The database holds the rule 0036 put the rows right for: an account that
holds Admin neither holds CCEO nor acts as one
(apps.core.rbac.admin_is_also_cceo)."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0036_admin_is_never_a_cceo"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("roles__contains", ["Admin"]),
                    models.Q(
                        ("roles__contains", ["CCEO"]),
                        ("active_role", "CCEO"),
                        _connector="OR",
                    ),
                    _negated=True,
                ),
                name="user_admin_is_never_cceo",
            ),
        ),
    ]
