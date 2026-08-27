"""Regression contracts for platform-wide interaction responsiveness."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class ClientResponsivenessContractTest(SimpleTestCase):
    def test_mutations_are_scoped_and_diagnostics_run_when_idle(self):
        behavior = _read("static/js/micro-ux.js")

        self.assertIn("pendingEnhanceRoots.add(node)", behavior)
        self.assertIn("pendingDialogRoots.add(mutation.target)", behavior)
        self.assertIn("requestIdleCallback", behavior)
        self.assertIn("scheduleAudit(root)", behavior)
        self.assertNotIn("scheduleFullScan", behavior)
        self.assertNotIn("enhanceFormLabels(document)", behavior)
        self.assertNotIn("normalizeActionButtonTypes(document)", behavior)
        self.assertNotIn("auditInteractiveNames(document)", behavior)
        self.assertNotIn("!visible(control) || controlHasName(control)", behavior)

    def test_dead_button_monitor_never_serializes_the_document(self):
        behavior = _read("static/js/platform-defect-beacon.js")

        self.assertNotIn("document.body.innerHTML", behavior)
        self.assertIn("var changeObserver = new MutationObserver", behavior)
        self.assertIn("changeObserver.disconnect()", behavior)

    def test_htmx_requests_are_bounded_with_upload_exceptions(self):
        base = _read("templates/base.html")
        self.assertIn("htmx.config.timeout = 45000", base)

        for path in ROOT.joinpath("templates").rglob("*.html"):
            source = path.read_text(encoding="utf-8")
            if 'hx-encoding="multipart/form-data"' not in source:
                continue
            with self.subTest(template=str(path.relative_to(ROOT))):
                self.assertIn("hx-request='{\"timeout\":120000}'", source)

    def test_prefetch_never_competes_eagerly_with_active_page(self):
        base = _read("templates/base.html")

        self.assertNotIn('"eagerness": "eager"', base)
        self.assertIn('"eagerness": "moderate"', base)
        self.assertIn('"eagerness": "conservative"', base)
