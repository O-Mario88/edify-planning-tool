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


class LoginHeroImageTests(SimpleTestCase):
    """The brand photo must not be downloaded by viewports that never show it.

    .login-brand is display:none below 70rem, so every phone, every tablet in
    portrait and plenty of laptops render no brand panel at all. The 92 KB
    photo behind it was still fetched twice over: once by a preload with
    fetchpriority="high", competing with the stylesheets that block first
    paint, and — once that was scoped — again by the <img> itself, because a
    hidden <img> is still loaded.

    It is a backdrop under a gradient carrying alt="", so it is now a CSS
    background on a div. Backgrounds on unrendered elements are not fetched.
    Verified in the browser: absent from the resource list at 390px, present
    at 1440px.
    """

    HERO = "login-classroom-portrait"
    BREAKPOINT = "(min-width: 70.01rem)"

    def test_the_preload_is_scoped_to_the_breakpoint_that_shows_it(self):
        markup = LOGIN_LAYOUT.read_text()
        preload = [
            line
            for line in markup.splitlines()
            if 'rel="preload"' in line and self.HERO in line
        ]
        self.assertEqual(len(preload), 1, "expected exactly one hero preload")
        self.assertIn(
            self.BREAKPOINT,
            preload[0],
            "an unscoped preload fetches the photo on phones, at high priority, "
            "for a panel that is display:none there",
        )

    def test_the_hero_is_a_background_not_an_img(self):
        markup = LOGIN_LAYOUT.read_text()
        img_tags = re.findall(r"<img[^>]*>", markup)
        self.assertFalse(
            [tag for tag in img_tags if self.HERO in tag],
            "the brand photo is back as an <img>; a hidden <img> is still "
            "downloaded, which is the 92 KB this removed",
        )
        self.assertIn(
            "login-brand__photo",
            markup,
            "the decorative div that carries the background is missing",
        )

    def test_login_css_carries_the_background(self):
        css = (CSS / "login.css").read_text()
        rule = css.split(".login-brand__photo {", 1)
        self.assertGreater(len(rule), 1, ".login-brand__photo rule is missing")
        block = rule[1].split("}", 1)[0]
        self.assertIn(self.HERO, block)
        self.assertIn("background-size: cover", block)

    def test_the_panel_is_still_hidden_below_the_breakpoint(self):
        # The whole optimisation rests on this. If the panel starts rendering
        # on small screens the preload scope and the background trick both
        # become wrong, and mobile silently loses its backdrop instead.
        css = (CSS / "login.css").read_text()
        self.assertRegex(
            css,
            r"@media \(max-width: 70rem\)[^@]*?\.login-brand \{\s*display: none",
        )
