"""One SSA per school per financial year (owner, 2026-10-14).

Until now several dated assessments in one year were kept as monitoring
history, and only the same school on the same date was a duplicate. The
owner's rule is one SSA a school a year, enforced by the database. Asked what
to do with the years that already hold more than one, the owner chose to keep
each year's latest confirmed record (else its latest) and archive the rest:
they are soft-deleted, not erased, and each is listed as it is archived.

A record holds its year while it is pending or confirmed; returned, flagged
and deleted records do not, so only those two states are de-duplicated.
"""

from django.db import migrations, models
from django.utils import timezone

HOLDING = ("pending", "confirmed")


def archive_extra_records(apps, schema_editor):
    SsaRecord = apps.get_model("ssa", "SsaRecord")
    rows = (
        SsaRecord.objects.filter(
            deleted_at__isnull=True, verification_status__in=HOLDING
        )
        .order_by("school_id", "fy")
        .values_list(
            "id", "school_id", "fy", "verification_status", "date_of_ssa", "created_at"
        )
    )
    years: dict[tuple, list] = {}
    for row in rows.iterator():
        years.setdefault((row[1], row[2]), []).append(row)
    archive = []
    for (school_id, fy), records in years.items():
        if len(records) < 2:
            continue
        # The year's latest confirmed record stays; with none confirmed, its
        # latest. Ties fall to the one created last.
        records.sort(key=lambda r: (r[3] == "confirmed", r[4], r[5]), reverse=True)
        kept = records[0]
        for extra in records[1:]:
            archive.append(extra[0])
            print(
                f"\n  SSA {extra[0]} archived: school {school_id} FY{fy} "
                f"({extra[3]}, {extra[4]:%Y-%m-%d}); kept {kept[0]} "
                f"({kept[3]}, {kept[4]:%Y-%m-%d})",
                end="",
            )
    if archive:
        SsaRecord.objects.filter(id__in=archive).update(
            deleted_at=timezone.now(), updated_at=timezone.now()
        )
        print(
            f"\n  {len(archive)} SSA record(s) archived to one a school a year.", end=""
        )


class Migration(migrations.Migration):
    dependencies = [
        ("ssa", "0009_ssa_record_source_and_return"),
    ]

    operations = [
        migrations.RunPython(archive_extra_records, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="ssarecord",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    deleted_at__isnull=True,
                    verification_status__in=["pending", "confirmed"],
                ),
                fields=("school", "fy"),
                name="uniq_live_ssa_school_fy",
            ),
        ),
    ]
