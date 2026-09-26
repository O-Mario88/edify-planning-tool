"""Remove duplicate client school visits: one school, one day, one kind of visit.

Owner, 2026-09-26: "I noticed a lot of users created duplicate client school
visits ... make sure all the duplicate visits on the same day same month all
deleted from the database just like you did with duplicate assignment to
partner."

The rule, which copy stays and how the others are removed live in
``apps.activities.duplicate_visits`` (the ``remove_duplicate_client_visits``
command runs the same code). In short: copies of the same visit at the same
client school on the same day are reduced to one; a copy with delivery history
(evidence, a Salesforce ID, money moved, any progress past scheduling) is
never removed; the rest are cancelled with their draft money withdrawn, then
tombstoned. Every kept and removed id is printed to the deploy log.

As in 0057, the historical models only decide whether there is anything to
do, so on a database with no duplicates (a fresh install, the test database)
the live code is never reached and a migration further down the history can
never meet a model newer than its schema.

Reverse is a no-op: the removed copies stay removed. Each carries the id of
the copy that stayed in ``last_reason``.
"""

from django.db import migrations


def remove_duplicates(apps, schema_editor):
    from apps.activities.duplicate_visits import (
        find_duplicate_client_visits,
        remove_duplicate_client_visits,
    )

    if not find_duplicate_client_visits(apps):
        return
    remove_duplicate_client_visits()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0031_staffprofile_google_drive_folder_url"),
        ("activities", "0057_backfill_cluster_session_invitations"),
        ("activity_catalogue", "0014_mapping_review"),
        ("audit", "0008_domain_event_aggregate_id_width"),
        ("budget", "0022_group_training_meals_rate"),
        ("clusters", "0006_backfill_catchments_and_membership_history"),
        ("core_schools", "0004_fy_aware_core_plan"),
        (
            "daily_visit_batches",
            "0002_dailyvisitbatch_actual_field_cost_per_school_and_more",
        ),
        ("evidence", "0001_initial"),
        ("fund_requests", "0018_weekly_funding_source"),
        ("notifications", "0005_repoint_dead_workflow_links"),
        ("partners", "0028_partnerassignment_uniq_open_partner_school_assignment"),
        ("schools", "0022_school_ownership_transfers"),
    ]

    operations = [migrations.RunPython(remove_duplicates, migrations.RunPython.noop)]
