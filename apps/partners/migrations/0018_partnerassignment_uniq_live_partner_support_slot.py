"""INT-02: one live assignment per partner per support slot.

PartnerAssignment declared no constraints at all. The rule is already written
twice in code and enforced by neither the database nor most of the creation
paths: withdrawal_service._assert_replacement_eligible checks it on the
replacement path only ("Without this a school could end up with two partners
both believing they own the same visit, and both eventually billing for it"),
and system_health.planning_oversight_health reports the rows that got in
anyway. It is the ambiguity the model's own reassignment-lineage comment
describes — "a partner with two assignments at one school made both pairings
ambiguous, and every count and every shilling downstream inherited the
ambiguity."

Scoped to (school, PARTNER, slot), narrower than the (school, slot) rule the
health check reports, and deliberately so — see the model comment. Two
different partners on one slot is a real transitional state a human resolves
from the health board; one partner holding the same slot twice has no reading
at all.

WHY THE PRE-CHECK BELOW EXISTS
The development database is empty. Production is not, and this is precisely a
state production has had no defence against — the health check exists because
rows like these were found. A partial unique index built over duplicates
surfaces as a bare `could not create unique index ... Key (...) is
duplicated`, which does not say which school, which partner or how many. The
guard runs first, in the same transaction, names them and points at the page
that lists the rest. Nothing has been altered when it raises.
"""

from __future__ import annotations

import django.db.models.functions.comparison
from django.db import migrations, models
from django.db.models import Count, Value
from django.db.models.functions import Coalesce


def check_one_live_assignment_per_slot(apps, schema_editor):
    """Refuse the index while one partner holds a school's slot twice.

    Mirrors the index predicate exactly — live rows, school present, at least
    one slot identifier named, NULL and "" folded together — so it cannot
    pass a case the index would then reject.
    """
    model = apps.get_model("partners", "PartnerAssignment")
    clashes = (
        model._base_manager.exclude(status="returned_to_staff")
        .filter(school__isnull=False)
        .annotate(
            slot_support=Coalesce("support_type", Value("")),
            slot_visit=Coalesce("visit_number", Value("")),
            slot_training=Coalesce("training_number", Value("")),
        )
        # A clash needs a slot: excludes rows where all three are blank,
        # i.e. ordinary handovers that name no Core-package slot at all.
        .exclude(slot_support="", slot_visit="", slot_training="")
        .values(
            "school_id", "partner_id", "slot_support", "slot_visit", "slot_training"
        )
        # order_by() clears PartnerAssignment.Meta.ordering — otherwise
        # created_at joins the GROUP BY and every row becomes its own group.
        .order_by()
        .annotate(rows=Count("id"))
        .filter(rows__gt=1)
    )
    count = clashes.count()
    if not count:
        return
    worst = clashes.order_by("-rows").first()
    example = (
        model._base_manager.exclude(status="returned_to_staff")
        .filter(
            school_id=worst["school_id"],
            partner_id=worst["partner_id"],
        )
        .order_by()
        .values_list("pk", flat=True)
        .first()
    )
    slot = " / ".join(
        part
        for part in (
            worst["slot_support"],
            worst["slot_visit"],
            worst["slot_training"],
        )
        if part
    )
    raise RuntimeError(
        f"\nMIGRATION ABORTED (INT-02) — cannot add "
        f"uniq_live_partner_support_slot.\n"
        f"  Table   : partner_assignment\n"
        f"  Columns : school_id, partner_id, support_type, visit_number, "
        f"training_number\n"
        f"            (live rows only — status <> 'returned_to_staff')\n"
        f"  Rule    : one partner holds a school's support slot at most once\n"
        f"  Rows    : {count} slot(s) are held more than once by one partner\n"
        f"  Example : school_id={worst['school_id']!r} "
        f"partner_id={worst['partner_id']!r} slot {slot!r} is held "
        f"{worst['rows']} times, e.g. partner_assignment.id = {example!r}\n"
        f"  List all: SELECT school_id, partner_id, "
        f"coalesce(support_type,''),\n"
        f"                   coalesce(visit_number,''), "
        f"coalesce(training_number,''),\n"
        f"                   count(*), array_agg(id)\n"
        f"            FROM partner_assignment\n"
        f"            WHERE status <> 'returned_to_staff' AND school_id IS "
        f"NOT NULL\n"
        f"              AND (coalesce(support_type,'') <> '' OR "
        f"coalesce(visit_number,'') <> ''\n"
        f"                   OR coalesce(training_number,'') <> '')\n"
        f"            GROUP BY 1,2,3,4,5 HAVING count(*) > 1;\n"
        f"The duplicates are the same organisation entered twice against one "
        f"entitlement. Release the superseded one through the withdrawal "
        f"workflow (it becomes status='returned_to_staff' and stops holding "
        f"the slot), then re-run the migration. The Partner Oversight health "
        f"board lists them under 'duplicate_support_slot_holders'. No schema "
        f"change has been applied."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0048_backfill_cluster_attendance"),
        (
            "activity_catalogue",
            "0011_remove_activityinterventionmapping_uniq_catalogue_intervention_mode_and_more",
        ),
        ("clusters", "0004_backfill_cluster_portfolio_owners"),
        ("partners", "0017_partnerhold"),
        ("projects", "0011_projectschoolassignment_baseline_band_and_more"),
        ("schools", "0021_school_uniq_school_salesforce_account_id"),
        ("ssa", "0008_ssarecommendation"),
    ]

    operations = [
        # Runs before any DDL. Reverse is a no-op: dropping an index cannot
        # fail on data, so there is nothing to verify on the way back.
        migrations.RunPython(
            check_one_live_assignment_per_slot, migrations.RunPython.noop
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
                condition=models.Q(
                    models.Q(("status", "returned_to_staff"), _negated=True),
                    ("school__isnull", False),
                    models.Q(
                        models.Q(
                            ("support_type__isnull", False),
                            models.Q(("support_type", ""), _negated=True),
                        ),
                        models.Q(
                            ("visit_number__isnull", False),
                            models.Q(("visit_number", ""), _negated=True),
                        ),
                        models.Q(
                            ("training_number__isnull", False),
                            models.Q(("training_number", ""), _negated=True),
                        ),
                        _connector="OR",
                    ),
                ),
                name="uniq_live_partner_support_slot",
            ),
        ),
    ]
