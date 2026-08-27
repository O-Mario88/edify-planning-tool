"""BACKUP-01 — the production database must be a tier that has backups.

DigitalOcean App Platform offers two kinds of database. A *dev database* is
included with the app and is cheaper. A *managed cluster* costs more and is the
only one with backups:

    "App Platform's dev databases do not support backups."
    "because dev databases lack these features, we do not recommend using dev
     databases in production environments."
        -- DigitalOcean documentation, "How do I back up my dev database on
           App Platform?"

`.do/app.yaml` declared `production: false`, which is the dev tier. The
comment above it named two consequences -- no automated failover, no private
VPC networking -- and not the third.

That is the whole platform's backup story collapsing into nothing. §53 has a
rehearsal script, a restore manifest, a verified round trip and a runbook. All
of it describes what to do WITH a backup. Nothing was taking one. An incident
would have been unrecoverable: no snapshot, no point-in-time recovery, no
failover, and one copy of the financial ledger, the SSA history and the
child-welfare records, on a tier whose vendor says not to run production on it.

This is the same defect the rest of this audit kept finding, at the layer below
all of it: a reader with no writer. A restore procedure is a reader. Something
has to be writing the backups.

WHY THIS IS A TEST AND NOT A COMMENT

The tier is one word in a YAML file. It reverts by a copy-paste from
`staging.yaml`, where `production: false` is correct and says so. Nothing in a
deploy would object, and the failure is invisible until the day it matters, at
which point it is not fixable. So the invariant is asserted where it will be
read: in the suite, on every commit.

STAGING IS DELIBERATELY EXEMPT. `.do/staging.yaml` carries seeded data, not the
live estate, and says "Dev-tier is intentional". Losing it costs a reseed. The
rule here is about the file that describes production.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

#: The tiers DigitalOcean documents as having backups. `production: true` is
#: the flag that selects a managed cluster; everything else is the dev tier.
_DB_BLOCK = re.compile(r"^databases:\s*$(.*?)^(?=\S)", re.MULTILINE | re.DOTALL)
_ENTRY = re.compile(r"^  - name:\s*(\S+)\s*$", re.MULTILINE)


def _spec(name: str) -> str:
    return (Path(settings.BASE_DIR) / ".do" / name).read_text(encoding="utf-8")


def _database_entries(text: str) -> list[tuple[str, str]]:
    """[(name, body)] for each entry under `databases:`.

    Parsed rather than grepped for `production:` anywhere in the file: the spec
    carries commented-out examples of a managed cache that also say
    `production: true`, and a whole-file grep would read one of those as
    evidence about the database and pass while the database was dev-tier.
    """
    block = _DB_BLOCK.search(text)
    if block is None:
        return []
    body = block.group(1)
    starts = [(m.group(1), m.start()) for m in _ENTRY.finditer(body)]
    entries = []
    for index, (name, start) in enumerate(starts):
        end = starts[index + 1][1] if index + 1 < len(starts) else len(body)
        entries.append((name, body[start:end]))
    return entries


def _is_managed(entry_body: str) -> bool:
    for line in entry_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # a comment about the tier is not the tier
        if stripped.startswith("production:"):
            return stripped.split(":", 1)[1].strip() == "true"
    return False  # absent means dev tier, which is the default


class ProductionDatabaseHasBackupsTest(SimpleTestCase):
    def test_the_parser_finds_the_databases_at_all(self):
        """A parser that finds nothing would pass every test below forever.

        This is the check that stops BACKUP-01 being closed by a regex that
        quietly stopped matching -- which is exactly how the gate it replaces
        came to certify a wiped database.
        """
        entries = _database_entries(_spec("app.yaml"))
        self.assertTrue(entries, "no database entries parsed out of .do/app.yaml")
        self.assertIn("db", [name for name, _ in entries])

    def test_the_production_database_is_a_managed_cluster(self):
        for name, body in _database_entries(_spec("app.yaml")):
            with self.subTest(database=name):
                self.assertTrue(
                    _is_managed(body),
                    f"BACKUP-01: .do/app.yaml declares database {name!r} on App "
                    f"Platform's dev tier, which DigitalOcean documents as "
                    f"having no backups and explicitly does not recommend for "
                    f"production. §53's whole restore procedure describes what "
                    f"to do with a backup that nothing would be taking. Set "
                    f"`production: true` with a cluster_name, size and "
                    f"num_nodes. Applying it is a data migration, not a "
                    f"redeploy -- docs/runbooks.md §12.",
                )

    def test_the_spec_records_why_the_tier_matters(self):
        """The reason has to travel with the setting.

        `production: true` reads as a performance knob to anyone who has not
        met this finding, and the cheaper value is one word away. The next
        person to weigh the line item should find the reason next to it rather
        than in a ledger they have no cause to open.
        """
        text = _spec("app.yaml")
        self.assertIn("BACKUP-01", text)
        self.assertIn("do not support backups", text)

    def test_staging_is_allowed_to_be_dev_tier_and_says_so(self):
        """The exemption is real, and it is asserted so it stays deliberate."""
        text = _spec("staging.yaml")
        entries = _database_entries(text)
        self.assertTrue(entries, "no database entries parsed out of staging.yaml")
        self.assertFalse(
            any(_is_managed(body) for _, body in entries),
            "staging is expected on the dev tier; if that changed on purpose, "
            "this test is the thing to update",
        )
        self.assertIn("Dev-tier is intentional", text)
