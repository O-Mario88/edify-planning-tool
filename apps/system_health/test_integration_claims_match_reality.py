"""INTG-01 — the screens must not claim an integration the code does not have.

There is no HTTP transport for Salesforce anywhere in this codebase.
`apps.integrations.services.push_to_external` is a single unconditional
`raise IntegrationNotConfigured`, and so is `validate_external_reference`. That
is a deliberate, documented seam: "Until then it refuses loudly rather than
pretending."

The code refuses loudly. The screens did not. Two of them told the user the
system had confirmed something with Salesforce:

* the IA's partner-completion drawer — "Completing verifies the evidence and
  **confirms Salesforce**";
* the IA verification queue header — "Verify activity completions, **confirm
  Salesforce records integrity**".

What actually happens is that a person types a reference, it is matched against
a prefix (`TS-` / `SVE-`, or `Loan-<number>`), checked for local uniqueness,
and stored. Nothing is contacted. Nothing is verified. And that stored string
is the gate on activity closure, IA partner confirmation, core-activity
verification and partner-payment eligibility — so an IA who believes the
platform checked Salesforce is approving money on a belief the platform never
earned.

This is not a bug in the integration. It is the gap between what the product
says and what it does, which is this audit's other recurring shape: a claim
with nothing behind it. The transport landing is a roadmap decision with
credentials attached and is not closable from here. The claim is closable from
here, so it is closed, and asserted so it cannot drift back the next time
somebody tightens the copy.

WHEN THE TRANSPORT LANDS

Delete this test in the same change that implements `push_to_external`. Not
before: while that function raises, any screen promising confirmation is
telling the user something untrue. The assertion is deliberately conditional on
the code, so it tells you that itself rather than relying on anyone remembering.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.integrations import services

TEMPLATES = Path(settings.BASE_DIR) / "templates"

#: Phrases where the SYSTEM is the subject — it claims to have done something
#: with Salesforce.
#:
#: The boundary is grammatical and deliberate. An imperative addressed to the
#: person — "Confirm Salesforce Entry" on a button, "Confirm that this loan has
#: been entered into Salesforce" — asks a human to attest to something they
#: did, which is exactly what the workflow is and is not a false claim. The
#: third person is the problem: "Completing … confirms Salesforce" and "confirm
#: Salesforce records integrity" both tell the reader a check happened.
#:
#: Drawing it here rather than banning the word outright keeps the test honest
#: about what is actually wrong. Widening it to every occurrence would force
#: rewrites of copy that is already true, and a gate that cries wolf gets
#: deleted.
FORBIDDEN = (
    re.compile(r"\bconfirms\s+salesforce\b", re.IGNORECASE),
    re.compile(r"salesforce\s+records?\s+integrity", re.IGNORECASE),
    re.compile(
        r"(synced|syncs|pushed|pushes|sent|sends)\s+to\s+salesforce", re.IGNORECASE
    ),
    re.compile(r"verified\s+(?:in|with|against)\s+salesforce", re.IGNORECASE),
    re.compile(r"salesforce\s+(?:has\s+been\s+)?(?:checked|validated)", re.IGNORECASE),
)

#: All three comment syntaxes a Django template can carry: `{# … #}` (one line
#: only — `{% comment %}` is required for anything longer, and this repository
#: has its own guard for that), `{% comment %}…{% endcomment %}`, and HTML
#: `<!-- … -->`.
#:
#: Stripped before scanning, because this test is about what a user is TOLD.
#: A comment recording what the old wording used to say is not a claim to
#: anyone. Both of those comments tripped this rule while it was being written,
#: which is how the omission was found.
_COMMENT = re.compile(
    r"\{#.*?#\}|\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}|<!--.*?-->",
    re.DOTALL | re.IGNORECASE,
)


def _transport_is_implemented() -> bool:
    """True once push_to_external does something other than refuse.

    Read from the function's own source, so this cannot be satisfied by a
    comment or by the flag being flipped while the body still raises.
    """
    body = inspect.getsource(services.push_to_external)
    stripped = [
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    # def line, docstring, and a raise. Anything more means somebody wired it.
    return not any(
        line.startswith("raise IntegrationNotConfigured") for line in stripped
    )


def _template_texts(*, strip_comments: bool = True):
    for path in sorted(TEMPLATES.rglob("*.html")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if strip_comments:
            # Blanked, not deleted, so reported line numbers stay true.
            text = _COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
        yield path, text


class SalesforceClaimsMatchTheCodeTest(SimpleTestCase):
    def test_the_transport_really_is_unimplemented(self):
        """The premise of every assertion below.

        If this ever fails, the integration landed and the rest of this module
        should be deleted rather than worked around.
        """
        self.assertFalse(
            _transport_is_implemented(),
            "push_to_external no longer refuses — the Salesforce transport "
            "appears to be implemented. Delete this module in the same change, "
            "and update INTG-01 in the release-readiness record.",
        )

    def test_the_scanner_reads_real_templates(self):
        """A scanner that found no templates would pass the next test forever."""
        found = list(_template_texts())
        self.assertGreater(len(found), 100, "found almost no templates to scan")
        haystack = "\n".join(text for _, text in found)
        self.assertIn("Salesforce", haystack, "no template mentions Salesforce at all")

    def test_no_screen_claims_the_system_confirmed_salesforce(self):
        offenders = []
        for path, text in _template_texts():
            for pattern in FORBIDDEN:
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    offenders.append(
                        f"{path.relative_to(settings.BASE_DIR)}:{line} "
                        f"— {match.group(0)!r}"
                    )
        self.assertEqual(
            offenders,
            [],
            "INTG-01: these screens tell the user the system did something with "
            "Salesforce, and it did not — push_to_external raises "
            "IntegrationNotConfigured. A person types the reference and it is "
            "stored. Say that, or implement the transport.\n  "
            + "\n  ".join(offenders),
        )

    def test_the_replacement_wording_is_actually_there(self):
        """The fix, asserted — not just the absence of the old wording.

        Deleting the sentence would satisfy the test above and leave the IA
        with no statement at all about what completing does. The point was
        never to remove the claim; it was to replace it with a true one.
        """
        drawer = (
            TEMPLATES / "partials" / "ia" / "partner_complete_drawer.html"
        ).read_text(encoding="utf-8")
        self.assertIn("does not contact Salesforce", drawer)
