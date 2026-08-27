"""DEP-01 — the repository's two records of the live app describe two apps.

Not two descriptions of one app that drifted. Two different DigitalOcean
application UUIDs:

    .do/README.md                            edify-planning-app
                                             dacdc3eb-0ebe-4b47-bea2-88fe1155347b
    docs/live-production-audit-2026-08-09.md edify-planning-fra
                                             8f8682cd-a00a-42d9-b9a6-4fa4b4140bde

and, downstream of that, two different topologies: one web instance against
two, a development-tier database against managed PostgreSQL 17, no cache
against Valkey 8, migrations on container boot against a dedicated pre-deploy
job.

WHY THIS IS A TEST AND NOT JUST A PARAGRAPH

Nothing in the repository notices. Each document is internally coherent and
confidently written, so whichever one a reader opens gives them a clear answer,
and the two answers are incompatible. A contradiction nobody trips over is
indistinguishable from agreement — which is the same shape as every other
defect this audit found: a claim that reads as settled because nothing is
positioned to disagree with it.

This cannot be resolved from a source-only container; settling it needs
`doctl apps spec get` against the live app. So the test carries
`expectedFailure` rather than `skipTest`, for the reason GOV-01's guard did and
which that guard then demonstrated: a skipped test reports nothing, while an
expected failure runs, records its failure, and the moment somebody reconciles
the records reports an UNEXPECTED SUCCESS that fails the build and forces this
marker off. The gap cannot be closed quietly and cannot stay hidden.

THE ASYMMETRY, WHICH MATTERS MORE THAN THE CONTRADICTION

The two documents do not claim equal authority, and the release assessment
should not treat them as if they did.

`.do/README.md` labels its own topology section "Recorded 2026-08-04 after the
spec repair. **Treat as documentation, not as input**". The live audit is five
days newer, was performed against the running application, and labels its
infrastructure table **LIVE PRODUCTION VERIFIED** — the same document
distinguishes that label from "REPAIRED IN SOURCE" and "NOT VERIFIED"
deliberately, and says "A passing local test is not treated as production
evidence."

If the newer, live-verified record is the accurate one, then production runs
**two** web instances. DEP-02 recorded `RUN_MIGRATIONS=true` on the web service,
which makes migrations run on container boot — and two instances booting
together with no advisory lock is the exact configuration `DEPLOY.md` calls
unsafe. That is why the advisory lock fixed in this audit was not a theoretical
hardening. The safer-looking single-instance number comes from the record that
disclaims itself.

This test therefore asserts the contradiction is gone, and the control tests
below assert the premise is still real — so it cannot pass by the facts having
been quietly deleted from one side.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
DO_README = ROOT / ".do" / "README.md"
LIVE_AUDIT = ROOT / "docs" / "live-production-audit-2026-08-09.md"

#: A DigitalOcean application UUID as either document spells it.
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
#: `app edify-planning-app` / `**DigitalOcean app:** \`edify-planning-fra\``
_APP_NAME = re.compile(r"edify-planning-(?:app|fra|tool)\b")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _claims_only(text: str) -> str:
    """The document's own assertions, with blockquoted commentary removed.

    A document must be able to WARN about the other record — naming the app it
    disagrees with — without that being read as agreement. The first version of
    this test had no such rule, so adding a DEP-01 pointer to `.do/README.md`
    made the UUID check pass: the two files now shared a UUID because one of
    them was quoting the other. An unexpected success for entirely the wrong
    reason, and it would have read as somebody having resolved DEP-01.

    Markdown blockquotes are where a cross-reference belongs, so lines starting
    `>` are commentary and everything else is a claim.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith(">")
    )


def _app_identities(text: str) -> set[str]:
    """Every app name this document names, minus the service component name.

    `edify-planning-tool` is the SERVICE inside the app, not the app, and both
    documents mention it; including it would make the two sides look like they
    disagree about something they do not.
    """
    return {name for name in _APP_NAME.findall(text) if name != "edify-planning-tool"}


def _app_uuids(text: str) -> set[str]:
    return set(_UUID.findall(text))


class DeploymentRecordsDescribeOneAppTest(SimpleTestCase):
    """DEP-01. Quarantined: open, and not closable from a source-only audit."""

    @unittest.expectedFailure
    def test_the_two_records_name_the_same_application(self):
        readme_names = _app_identities(_claims_only(_read(DO_README)))
        audit_names = _app_identities(_claims_only(_read(LIVE_AUDIT)))

        self.assertEqual(
            readme_names,
            audit_names,
            "DEP-01 is still open: .do/README.md and the live production audit "
            "name different DigitalOcean applications, so the repository has no "
            "single answer to what is deployed. Settle it with "
            "`doctl apps spec get` and make both records say the same thing.",
        )

    @unittest.expectedFailure
    def test_the_two_records_name_the_same_application_uuid(self):
        """The decisive fact — a name can be renamed, a UUID cannot."""
        shared = _app_uuids(_claims_only(_read(DO_README))) & _app_uuids(
            _claims_only(_read(LIVE_AUDIT))
        )
        self.assertTrue(
            shared,
            "DEP-01: the two records share no application UUID at all, which "
            "means they are not two descriptions of one app that drifted — "
            "they are descriptions of two apps.",
        )


class ThePremiseIsStillRealTest(SimpleTestCase):
    """Guards against the expected failures above passing for a bad reason.

    Deleting the facts from one document would reconcile the records and turn
    both expected failures into unexpected successes, which reads exactly like
    somebody having resolved DEP-01. These make that impossible: each document
    must still carry its own claim.
    """

    def test_a_cross_reference_is_not_agreement(self):
        """The rule the extractor rests on, driven rather than assumed.

        `.do/README.md` now carries a DEP-01 warning that names the other app
        and its UUID. That warning must not make the two records look like they
        agree — which is exactly what it did before blockquotes were excluded.
        """
        raw = _read(DO_README)
        self.assertIn("edify-planning-fra", raw, "the warning is still there")
        self.assertNotIn(
            "edify-planning-fra",
            _claims_only(raw),
            "a blockquoted cross-reference is commentary, not a claim about "
            "what is deployed",
        )

    def test_the_do_readme_still_records_a_live_topology(self):
        text = _claims_only(_read(DO_README))
        self.assertIn("What is actually running", text)
        self.assertIn("edify-planning-app", text)
        self.assertIn("dev-db-315277", text)

    def test_the_live_audit_still_records_its_own(self):
        text = _claims_only(_read(LIVE_AUDIT))
        self.assertIn("edify-planning-fra", text)
        self.assertIn("LIVE PRODUCTION VERIFIED", text)

    def test_the_two_records_still_disagree_about_the_web_instance_count(self):
        """One instance against two — the number DEP-02's severity turns on."""
        self.assertIn("1 × `apps-s-1vcpu-2gb`", _claims_only(_read(DO_README)))
        self.assertIn("2 × `apps-s-1vcpu-2gb`", _read(LIVE_AUDIT))

    def test_the_do_readme_disclaims_its_own_topology_section(self):
        """The asymmetry this file's docstring rests on, held to the source."""
        self.assertIn("Treat as documentation, not as input", _read(DO_README))

    def test_the_live_audit_claims_production_verification(self):
        text = _read(LIVE_AUDIT)
        self.assertIn("LIVE PRODUCTION VERIFIED", text)
        self.assertIn(
            "A passing local test is not treated as production evidence", text
        )
