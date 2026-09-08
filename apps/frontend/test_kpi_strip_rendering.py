"""Behavioral coverage of the shared strip's server-rendered data and actions."""
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class KpiStripRenderingTests(SimpleTestCase):
    def render(self, items, **context):
        return render_to_string('components/context_metrics.html', {'items': items, **context})

    def test_empty_data_omits_strip_and_zero_is_not_missing(self):
        self.assertNotIn('data-context-metrics', self.render([]))
        output = self.render([{'label': 'Visits', 'value': 0}])
        self.assertIn('>0</strong>', output)

    def test_all_eight_metrics_and_real_helpers_are_retained(self):
        output = self.render([{'label': f'Metric {i}', 'value': i, 'helper': 'Within plan'} for i in range(8)])
        self.assertEqual(output.count('role="listitem"'), 8)
        self.assertEqual(output.count('>Within plan</span>'), 8)
        self.assertIn('data-kpi-count="8"', output)

    def test_missing_data_metadata_and_accessible_description_are_preserved(self):
        output = self.render([{'label': 'Coverage', 'value': '—', 'data_state': 'not_collected', 'is_measured': False, 'metric_key': 'coverage', 'period': 'FY27', 'scope': 'Uganda', 'accessible_description': 'Coverage has not been collected.'}])
        for text in ['context-metrics__fact--pending', 'data-metric-key="coverage"', 'data-metric-period="FY27"', 'data-metric-scope="Uganda"', 'Coverage has not been collected.']:
            self.assertIn(text, output)
        self.assertNotIn('>0</strong>', output)

    def test_links_and_htmx_drawer_actions_keep_their_destinations(self):
        output = self.render([{'label': 'Schools', 'value': 3, 'drilldown_url': '/schools/?type=core'}, {'label': 'Approvals', 'value': 7, 'hx_get': '/approvals/drawer'}])
        self.assertIn('href="/schools/?type=core"', output)
        self.assertIn('hx-get="/approvals/drawer"', output)
        self.assertIn('hx-target="#drawer-container"', output)

    def test_labels_and_helpers_are_escaped_and_trends_are_never_invented(self):
        output = self.render([{'label': '<script>bad</script>', 'value': 2, 'helper': '<b>test</b>'}])
        self.assertIn('&lt;script&gt;', output)
        self.assertIn('&lt;b&gt;', output)
        self.assertNotIn('12.8%', output)


class PlatformMetricBlockTests(SimpleTestCase):
    def render(self, source, **context):
        from django.template import Context, Template
        return Template('{% load kpi_metrics %}' + source).render(Context(context))

    def test_loop_conditions_values_helpers_and_links_keep_their_scope(self):
        source = '''{% kpi_strip %}{% for item in rows %}{% if item.visible %}
        {% kpi_metric %}{% kpi_label %}{{ item.label }}{% endkpi_label %}
        {{ item.value }}<span> / {{ item.target }}</span>
        {% kpi_helper %}{{ item.helper }}{% endkpi_helper %}
        {% kpi_link %}/schools/?q={{ item.label }}&fy=2027{% endkpi_link %}
        {% endkpi_metric %}{% endif %}{% endfor %}{% endkpi_strip %}'''
        html = self.render(source, rows=[dict(label='A & B', value=0, target=10, visible=True, helper='No work yet'), dict(label='Hidden', visible=False)])
        self.assertEqual(html.count('data-component="context-metric"'), 1)
        self.assertIn('>0 / 10</strong>', html)
        self.assertIn('A &amp; B', html)
        self.assertIn('/schools/?q=A &amp; B&amp;fy=2027', html)
        self.assertNotIn('Hidden', html)
        self.assertNotIn('kpi_metric', html)

    def test_fields_cannot_leak_between_strips(self):
        html = self.render('''{% kpi_strip %}{% kpi_metric %}{% kpi_label %}First{% endkpi_label %}1{% kpi_helper %}Only first{% endkpi_helper %}{% endkpi_metric %}{% endkpi_strip %}
        {% kpi_strip %}{% kpi_metric %}{% kpi_label %}Second{% endkpi_label %}2{% endkpi_metric %}{% endkpi_strip %}''')
        self.assertEqual(html.count('data-context-metrics'), 2)
        self.assertEqual(html.count('>Only first</span>'), 1)

    def test_missing_value_remains_unknown_and_compact_density_keeps_all_metrics(self):
        html = self.render('{% kpi_strip %}{% kpi_metric %}{% kpi_label %}Coverage{% endkpi_label %}{{ missing }}{% endkpi_metric %}{% endkpi_strip %}')
        self.assertIn('>—</strong>', html)
        html = render_to_string('components/context_metrics.html', {'items': [dict(label=str(i), value=i) for i in range(9)], 'density': 'compact'})
        self.assertEqual(html.count('data-component="context-metric"'), 9)

    def test_all_platform_templates_compile(self):
        from pathlib import Path
        from django.conf import settings
        from django.template.loader import get_template
        for path in (Path(settings.BASE_DIR) / 'templates').rglob('*.html'):
            with self.subTest(template=str(path)):
                get_template(str(path.relative_to(Path(settings.BASE_DIR) / 'templates')))

    def test_no_metric_strip_is_nested_in_an_anchor(self):
        from pathlib import Path
        from django.conf import settings
        import re
        for path in (Path(settings.BASE_DIR) / 'templates').rglob('*.html'):
            for anchor in re.findall(r'<a\b.*?</a>', path.read_text(), re.S):
                self.assertNotIn('{% kpi_strip %}', anchor, str(path))

    def test_large_currency_has_compact_display_and_exact_accessible_amount(self):
        html = render_to_string('components/context_metrics.html', {'items': [dict(label='Approved', value='UGX 1,250,000,000')]})
        self.assertIn('title="UGX 1,250,000,000"', html)
        self.assertIn('<span class="sr-only">UGX 1,250,000,000</span>', html)
        self.assertIn('<span aria-hidden="true">UGX 1.25B</span>', html)

    def test_platform_has_no_remaining_standalone_summary_value_family(self):
        from pathlib import Path
        from django.conf import settings
        import re
        violations = []
        markers = ('edify-metric__value', 'ia-insight__value', 'login-stat__value', 'auth-stat-value')
        for path in (Path(settings.BASE_DIR) / 'templates').rglob('*.html'):
            source = re.sub(r'{% kpi_strip %}.*?{% endkpi_strip %}', '', path.read_text(), flags=re.S)
            for marker in markers:
                if marker in source:
                    violations.append(f'{path.name}: {marker}')
        self.assertEqual(violations, [])
