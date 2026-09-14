"""Contrast contracts for night surfaces and decorative separators."""
import re
from pathlib import Path
from django.test import SimpleTestCase
from apps.frontend.test_design_system_quality import _contrast_ratio


class ThemeDividerTests(SimpleTestCase):
    def test_each_dark_theme_defines_quiet_dividers_and_readable_accents(self):
        css = Path('static/css/design-system.css').read_text()
        for theme in ('blue', 'dark'):
            body = re.search(r':root\.theme-' + theme + r'\s*\{(.*?)\n\}', css, re.S)[1]
            tokens = dict(re.findall(r'(--[\w-]+):\s*([^;]+);', body))
            with self.subTest(theme=theme):
                surface = tokens['--edify-surface']
                divider = tokens['--edify-divider']
                self.assertLess(_contrast_ratio(divider, surface), 2)
                self.assertGreaterEqual(_contrast_ratio(tokens['--edify-accent-text'], surface), 4.5)
                control = tokens['--edify-control-border']
                if control.startswith('var('):
                    control = tokens[control[4:-1]]
                self.assertGreaterEqual(_contrast_ratio(control, surface), 3)
                for token in ('--edify-surface-hover', '--edify-surface-selected', '--edify-text-disabled'):
                    self.assertIn(token, tokens)
