# Data migration: rename stored SSA intervention values to the canonical set.
#
# Canonical set (apps/core/enums.py:SsaIntervention):
#   christlike_behaviour, exposure_to_word_of_god, financial_health, leadership,
#   learning_environment, government_requirement, teaching_environment, enrolment
#
# Old values being rewritten:
#   teaching_and_learning  → teaching_environment
#   education_technology   → enrolment
#   government_requirements → government_requirement
#
# Idempotent: REPLACE only matches exact old strings, which don't exist after
# the first run. Applies across every intervention-bearing string column.
from django.db import migrations


_RENAMES = [
    ("teaching_and_learning", "teaching_environment"),
    ("education_technology", "enrolment"),
    ("government_requirements", "government_requirement"),
]

# (table, column, is_array) for every intervention-bearing column found via
# model introspection. Plain CharField columns use REPLACE; the activities
# ArrayField uses array_replace per element.
_SCALAR_COLUMNS = [
    ("ssa_score", "intervention"),
    ("activity", "focus_intervention"),
    ("activity", "purpose_intervention"),
    ("project", "intervention"),
]
_ARRAY_COLUMNS = [
    ("activity", "secondary_focus_interventions"),
]


def forward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table, col in _SCALAR_COLUMNS:
            for old, new in _RENAMES:
                cursor.execute(
                    f"UPDATE {table} SET {col} = %s WHERE {col} = %s",
                    [new, old],
                )
        for table, col in _ARRAY_COLUMNS:
            for old, new in _RENAMES:
                cursor.execute(
                    f"UPDATE {table} SET {col} = array_replace({col}, %s, %s)",
                    [old, new],
                )


def reverse(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table, col in _SCALAR_COLUMNS:
            for old, new in reversed(_RENAMES):
                cursor.execute(
                    f"UPDATE {table} SET {col} = %s WHERE {col} = %s",
                    [old, new],
                )
        for table, col in _ARRAY_COLUMNS:
            for old, new in reversed(_RENAMES):
                cursor.execute(
                    f"UPDATE {table} SET {col} = array_replace({col}, %s, %s)",
                    [old, new],
                )


class Migration(migrations.Migration):

    dependencies = [
        ("ssa", "0003_alter_ssascore_intervention"),
        ("activities", "0014_alter_activity_focus_intervention_and_more"),
    ]

    operations = [
        migrations.RunPython(forward, reverse),
    ]
