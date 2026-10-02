"""A hand-over outside the SSA-measured support waits beside the others.

Owner, 2026-10-02: "Alumni is not an intervention so it can be assigned to any
school but it should not restrict another project from being assigned to that
school ... because it is not measured via ssa." A school already waiting on a
partner could not be handed to the same partner again for Alumni
(uniq_open_partner_school_assignment). ``outside_ssa`` marks such a hand-over
and puts its project in the key, so it is held to once per project instead.
Existing rows are all SSA-measured support and keep the rule unchanged.
"""

import django.db.models.functions.comparison
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("partners", "0029_partner_assignment_status_vocabulary"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="partnerassignment",
            name="uniq_open_partner_school_assignment",
        ),
        migrations.AddField(
            model_name="partnerassignment",
            name="outside_ssa",
            field=models.BooleanField(default=False),
        ),
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
                models.Case(
                    models.When(
                        outside_ssa=True,
                        then=django.db.models.functions.comparison.Coalesce(
                            models.F("project"),
                            models.Value(""),
                            output_field=models.CharField(),
                        ),
                    ),
                    default=models.Value(""),
                    output_field=models.CharField(),
                ),
                condition=models.Q(
                    ("status__in", ["assigned", "pending_scheduling"]),
                    ("school__isnull", False),
                ),
                name="uniq_open_partner_school_assignment",
            ),
        ),
    ]
