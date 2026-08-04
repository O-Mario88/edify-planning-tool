"""The sign-in layout must not reload the whole application stylesheet.

layouts/login.html is the first thing every user downloads, before they can
type a password, on whatever connection they have. It used to pull main.css —
the 322 KB Tailwind bundle — for five custom properties and no utilities at
all, and content-hashed filenames meant every release made them fetch it again.

Two things have to stay true for that to keep working, and neither is visible
by looking at the page:

  1. No template rendered by this layout may use a Tailwind utility. They all
     currently style themselves with bespoke `login-*` rules from login.css.
     The moment one reaches for `flex` or `mb-4` it will silently not apply.

  2. tokens.css must carry the radius scale. login.css consumes
     var(--radius-control) and friends in eight places; Tailwind tree-shakes
     theme values whose utilities are unused, which is why the shared theme
     block is `@theme static`. Without it every radius on the page renders 0 —
     which looks approximately fine at a glance, and is how it was nearly
     shipped.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = ROOT / "templates"
CSS = ROOT / "static" / "css"

LOGIN_LAYOUT = TEMPLATES / "layouts" / "login.html"

# Everything that can render inside layouts/login.html. change_password.html is
# deliberately absent: it extends layouts/auth.html, which goes through
# base.html and does load the full stylesheet set.
LOGIN_LAYOUT_TEMPLATES = [
    LOGIN_LAYOUT,
    TEMPLATES / "partials" / "pwa_head.html",
    TEMPLATES / "pages" / "auth" / "login.html",
    TEMPLATES / "pages" / "auth" / "reset_password.html",
]

RADIUS_TOKENS = (
    "--radius-surface",
    "--radius-control",
    "--radius-overlay",
    "--radius-small",
    "--radius-pill",
)


def classes_in(path: Path) -> set[str]:
    out: set[str] = set()
    for group in re.findall(r'class="([^"]*)"', path.read_text(errors="replace")):
        for cls in group.split():
            # Skip anything carrying template syntax — `{% if %}` fragments are
            # not class names.
            if "{" in cls or "}" in cls:
                continue
            out.add(cls)
    return out


class LoginBundleTests(SimpleTestCase):
    def test_sign_in_does_not_load_the_application_bundle(self):
        markup = LOGIN_LAYOUT.read_text()
        self.assertNotIn(
            "css/main.css",
            markup,
            "layouts/login.html is loading the 322 KB application bundle again. "
            "If a template here needs a utility, add the rule to login.css or "
            "build a login-scoped bundle — do not restore main.css.",
        )

    def test_sign_in_loads_the_token_bundle(self):
        markup = LOGIN_LAYOUT.read_text()
        self.assertIn("css/tokens.css", markup)

    def test_token_bundle_carries_the_radius_scale(self):
        tokens = (CSS / "tokens.css").read_text()
        for token in RADIUS_TOKENS:
            with self.subTest(token=token):
                self.assertRegex(
                    tokens,
                    rf"{re.escape(token)}:\s*\S+",
                    f"{token} is missing from tokens.css — login.css consumes it, "
                    "so every radius on the sign-in page will render 0. Check "
                    "that assets/css/_theme.css still says `@theme static`.",
                )

    def test_shared_theme_block_is_static(self):
        # `@theme` (without static) tree-shakes unused values, which drops the
        # radius tokens from tokens.css because nothing there uses a rounded-*
        # utility.
        theme = (ROOT / "assets" / "css" / "_theme.css").read_text()
        self.assertIn("@theme static", theme)

    def test_both_bundles_build_from_the_one_theme_block(self):
        # Two definitions of the same tokens is the failure design-system.css
        # documents at its --edify-radius-* aliases.
        for source in ("tailwind.source.css", "tokens.source.css"):
            with self.subTest(source=source):
                self.assertIn(
                    '@import "./_theme.css"',
                    (ROOT / "assets" / "css" / source).read_text(),
                )

    def test_no_sign_in_template_uses_a_tailwind_utility(self):
        # The utilities are generated into main.css, which this layout no longer
        # loads. Anything matching here would silently render unstyled.
        main = (CSS / "main.css").read_text(errors="replace")
        local = "".join(
            (CSS / name).read_text(errors="replace")
            for name in ("login.css", "design-system.css", "tokens.css")
        )
        for path in LOGIN_LAYOUT_TEMPLATES:
            if not path.exists():
                continue
            for cls in sorted(classes_in(path)):
                pattern = re.compile(r"\." + re.escape(cls) + r"(?![\w-])")
                if pattern.search(local):
                    continue  # satisfied by a stylesheet this layout loads
                with self.subTest(template=path.name, cls=cls):
                    self.assertIsNone(
                        pattern.search(main),
                        f"{path.name} uses `{cls}`, which is only defined in "
                        "main.css — a bundle the sign-in layout no longer loads, "
                        "so this class renders as nothing.",
                    )
