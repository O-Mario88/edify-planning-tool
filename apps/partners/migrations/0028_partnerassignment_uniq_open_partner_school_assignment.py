"""uniq_open_partner_school_assignment: one open handover of a school per partner.

The duplicates it would reject are removed by 0027; see there, and the model
comment, for the rule.
"""

import django.db.models.functions.comparison
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("partners", "0027_remove_duplicate_open_partner_assignments"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="partnerassignment",
            constraint=models.UniqueConstraint(
                models.F("school"),
                models.F("partner"),
                django.db.models.functions.comparison.Coalesce(
                    "support_type", models.Value("")
                ),
                django.db.models.functions.comparison.Coalesce(
                    "visit_number", models.Value("")
                ),
                django.db.models.functions.comparison.Coalesce(
                    "training_number", models.Value("")
                ),
                condition=models.Q(
                    ("status__in", ["assigned", "pending_scheduling"]),
                    ("school__isnull", False),
                ),
                name="uniq_open_partner_school_assignment",
            ),
        ),
    ]
