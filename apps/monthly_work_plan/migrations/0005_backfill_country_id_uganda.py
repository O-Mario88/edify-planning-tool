"""Backfill legacy "UG" country_id rows to the canonical "Uganda".

Two incompatible conventions coexisted for the operating-country identifier:
every real write path tagged rows "Uganda" (country_budget_service,
apps/realtime/jobs.py, command_center To-Do filters), while the RVP scope
guard and the RVP dashboard's budget lists compared against a "UG" default —
so any row that DID carry "UG" was invisible to the write-path consumers and
vice versa. The code now standardises on "Uganda"; this migration brings any
existing "UG" rows along.

Safety: country_id participates in unique constraints
(uniq_country_month on MonthlyWorkPlanBudget, (country_id, fy) on
CountryAnnualBudget), so a blind UPDATE could collide where both a "UG" and
an "Uganda" row exist for the same month/FY. Collisions are skipped and left
for manual review rather than merged or deleted — no data is destroyed.
Idempotent: a re-run finds no remaining "UG" rows. Reverse is a no-op:
mapping "Uganda" back to "UG" would clobber rows that were legitimately
"Uganda" before this migration ever ran.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    MonthlyWorkPlanBudget = apps.get_model("monthly_work_plan", "MonthlyWorkPlanBudget")
    CountryAnnualBudget = apps.get_model("monthly_work_plan", "CountryAnnualBudget")

    for row in MonthlyWorkPlanBudget.objects.filter(country_id="UG"):
        twin_exists = (
            MonthlyWorkPlanBudget.objects.filter(
                country_id="Uganda", month_key=row.month_key
            )
            .exclude(pk=row.pk)
            .exists()
        )
        if not twin_exists:
            row.country_id = "Uganda"
            row.save(update_fields=["country_id"])

    for row in CountryAnnualBudget.objects.filter(country_id="UG"):
        twin_exists = (
            CountryAnnualBudget.objects.filter(country_id="Uganda", fy=row.fy)
            .exclude(pk=row.pk)
            .exists()
        )
        if not twin_exists:
            row.country_id = "Uganda"
            row.save(update_fields=["country_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("monthly_work_plan", "0004_alter_countryannualbudget_country_id"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
