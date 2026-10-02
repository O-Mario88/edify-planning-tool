"""Data collection hand-overs wait beside a school's support.

Owner, 2026-10-02: "You can allow data collection assignment on every school
irrespective of whether they have the 1 visit by staff or partner because
those visits don't count. the only visits that count are in-school visits and
Training Follow Up visits."

One open hand-over per school per partner (uniq_open_partner_school_assignment)
refused a data collection (SSA Support) hand-over at a school the same partner
already held for a follow up or an in-school training. The rule is now two:
one open hand-over of the school's support, and one of its data collection.
Both carry the key the single constraint had, so every existing row passes.
"""

import django.db.models.functions.comparison
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0064_partner_date_set_by"),
        ("activity_catalogue", "0014_mapping_review"),
        ("clusters", "0007_cluster_facilitating_partner"),
        ("partners", "0030_outside_ssa_handover"),
        ("projects", "0014_project_staff_capacity"),
        ("schools", "0023_repair_school_holder_assignments"),
        ("ssa", "0009_ssa_record_source_and_return"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="partnerassignment",
            name="uniq_open_partner_school_assignment",
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
                    models.Q(("purpose_of_visit", "ssa_support"), _negated=True),
                ),
                name="uniq_open_partner_school_assignment",
            ),
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
                    ("purpose_of_visit", "ssa_support"),
                ),
                name="uniq_open_partner_data_collection",
            ),
        ),
    ]
