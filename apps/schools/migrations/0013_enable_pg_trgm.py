"""Enables PostgreSQL's pg_trgm extension so School.name can be searched by
trigram similarity (apps.ssa.unmatched_service.compute_suggested_match) —
efficient fuzzy candidate matching without a per-row full-table ILIKE scan.
Safe/idempotent: TrigramExtension is a plain `CREATE EXTENSION IF NOT
EXISTS pg_trgm`. If the DB role lacks CREATE EXTENSION privilege (some
managed Postgres tiers restrict it), this migration fails loudly rather
than silently — apps.ssa.unmatched_service falls back to a Python
difflib-based similarity ranking if trigram functions are unavailable at
runtime, so the fuzzy-match feature itself never hard-depends on this."""

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0012_unmatchedssarecord_batch_and_more"),
    ]

    operations = [
        TrigramExtension(),
    ]
