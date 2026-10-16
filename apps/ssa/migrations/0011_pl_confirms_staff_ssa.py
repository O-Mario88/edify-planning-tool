"""Staff SSA the Programme Lead has approved counts; Core reads the record.

Owner, 2026-10-16: "I am a PL so mine should show already only those of
CCEOs should awaits approval ... when PL approves they will reflect", and of
the Core Schools page: "Core package only track visits and trainings. Once
assessment is done and entered, it should be recorded and reflect
everywhere."

From this release a Programme Lead's own SSA is confirmed as it is keyed and
a CCEO's when the lead approves the visit it was keyed on
(``apps.ssa.pl_confirmation``). Records written before it are pending under
the old rule (every SSA waited for Impact Assessment): this confirms a lead's
own, and a CCEO's whose visit the lead has approved, as the
``confirm_pl_ssa`` command does, printing every record to the deploy log.

Then every Core package reads its assessment from the school's confirmed SSA
of the package's year. The slot recount had set it from an assessment slot
nothing could schedule, so it read 0 everywhere.

As in activities 0057, 0058, 0066 and 0067, the historical models decide
whether there is anything to confirm, so on a database with none of these
records (a fresh install, the test database) the live code is never reached.
The Core step uses historical models only.

Reverse is a no-op: confirmed scores stay confirmed.
"""

from django.db import migrations


def confirm_pending(apps, schema_editor):
    SsaRecord = apps.get_model("ssa", "SsaRecord")
    User = apps.get_model("accounts", "User")
    Activity = apps.get_model("activities", "Activity")
    pending = SsaRecord.objects.filter(
        deleted_at__isnull=True, verification_status="pending"
    ).exclude(collector_type="partner")
    leads = User.objects.filter(roles__contains=["Program Lead"]).values("id")
    approved = Activity.objects.filter(
        status__in=("ia_verified", "accountant_confirmed", "closed"),
        pl_reviewed_by__isnull=False,
    ).values("id")
    if not (
        pending.filter(collected_by_user_id__in=leads).exists()
        or pending.filter(source_activity_id__in=approved).exists()
    ):
        return
    from apps.ssa.pl_confirmation import confirm_left_pending

    rows = confirm_left_pending(apply=True)
    if not rows:
        return
    print()
    for row in rows:
        outcome = f"skipped: {row['skipped']}" if "skipped" in row else "confirmed"
        print(
            f"  SSA {row['id']} school {row['school']} FY{row['fy']} "
            f"({row['basis']}): {outcome}"
        )
    print(f"  pending staff SSA a Programme Lead approved: {len(rows)}")


def core_assessment_follows_ssa(apps, schema_editor):
    SsaRecord = apps.get_model("ssa", "SsaRecord")
    CorePlan = apps.get_model("core_schools", "CorePlan")
    confirmed = set(
        SsaRecord.objects.filter(
            deleted_at__isnull=True, verification_status="confirmed"
        ).values_list("school__school_id", "fy")
    )
    changed = 0
    for plan in CorePlan.objects.only("id", "school_id", "fy", "assessment_completed"):
        done = int((plan.school_id, plan.fy) in confirmed)
        if plan.assessment_completed != done:
            CorePlan.objects.filter(pk=plan.pk).update(assessment_completed=done)
            changed += 1
    if changed:
        print(f"\n  Core packages reading their year's SSA: {changed} updated", end="")


class Migration(migrations.Migration):
    dependencies = [
        ("ssa", "0010_one_ssa_per_school_fy"),
        ("activities", "0067_hand_in_entered_work"),
        ("accounts", "0038_user_acting_until"),
        ("core_schools", "0012_index_slot_activity"),
        ("schools", "0025_ssa_import_row_duplicate"),
    ]

    operations = [
        migrations.RunPython(confirm_pending, migrations.RunPython.noop),
        migrations.RunPython(core_assessment_follows_ssa, migrations.RunPython.noop),
    ]
