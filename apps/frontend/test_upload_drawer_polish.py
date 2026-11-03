"""The visit-form upload drawer, as a partner meets it on a phone (partner
audit, 2026-11-03).

Pinned here:

  1. Adding a page clears the last Submit's refusal ("Add the form ...
     then Submit."), which stayed up beside the pages that answered it.
  2. A HEIC photo is redrawn as JPEG where the browser can read it; the
     server refuses one it receives, saying what to do (apps/evidence).
  3. A disabled primary button looks disabled in the blue and dark themes:
     their fill outranked the disabled mute, so a held Submit looked live.
  4. The "Discard your changes?" cover has the drawer scrim's tint and no
     blur (owner, 2026-10-31: "remove blury background").
"""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
PAGES_STATE = ROOT / "templates/components/evidence_pages_state.html"


def _rule(css: str, selector: str) -> str:
    start = css.index(selector + " {") + len(selector) + 2
    return css[start : css.index("}", start)]


class TheUploadDrawerReadsRightOnAPhone(SimpleTestCase):
    def test_adding_a_page_clears_the_last_refusal(self):
        source = PAGES_STATE.read_text()
        add = source[source.index("async add(event)") : source.index("remove(index)")]
        self.assertIn("getElementById('evidence-errors')?.replaceChildren()", add)

    def test_a_heic_photo_is_redrawn_as_jpeg_whatever_its_size(self):
        shrink = PAGES_STATE.read_text().split("async shrink(file)", 1)[1]
        self.assertIn("/^image\\/hei[cf]$/", shrink)
        self.assertIn("if (!heic &&", shrink)

    def test_a_disabled_primary_keeps_its_mute_in_the_blue_and_dark_themes(self):
        css = (ROOT / "static/css/consistency.css").read_text()
        rule = css[css.index("Blue primary actions stay unmistakable") :]
        fill = rule[: rule.index("{")]
        self.assertTrue(fill.rstrip().endswith("):not(:disabled)"), fill[-80:])
        built = (ROOT / "static/build/css/consistency.css").read_text()
        self.assertIn(
            ":is(.theme-blue,.theme-dark) :where(.btn-primary):is(*,._._):not(:disabled)",
            built,
        )

    def test_the_discard_cover_is_tinted_not_blurred(self):
        cover = _rule(
            (ROOT / "static/css/components.css").read_text(), ".drawer-discard"
        )
        self.assertIn("background: var(--edify-drawer-scrim);", cover)
        self.assertNotIn("blur(", cover)
        # drawers.css loads later; a cover of its own there is what blurred.
        drawers = (ROOT / "static/css/drawers.css").read_text()
        self.assertNotIn(".drawer-discard {", drawers)
