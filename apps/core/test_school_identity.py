from pathlib import Path

from django.http import HttpResponse
from django.template import Context, Template, engines
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from apps.core.school_identity_middleware import SchoolIdentityMiddleware
from apps.schools.models import School


class SchoolIdentityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(school_id='ED-0042', name='Grace & Hope')

    def render_response(self, markup, data=None):
        request = RequestFactory().get('/', HTTP_HX_REQUEST='true')
        context = {'request': request, **(data or {})}
        return SchoolIdentityMiddleware(lambda req: HttpResponse(
            Template('{% load school_identity %}' + markup).render(Context(context))
        ))(request).content.decode()

    def test_public_id_resolution_is_batched_and_names_are_escaped(self):
        refs = [self.school.pk, self.school.school_id] * 20
        with self.assertNumQueries(1):
            html = self.render_response(
                '{% for ref in refs %}{% school_identity name ref %}{% endfor %}',
                {'refs': refs, 'name': '<script>unsafe</script>'},
            )
        self.assertEqual(html.count('ED-0042'), 40)
        self.assertNotIn('data-school-code-token', html)
        self.assertNotIn('<script>', html)
        self.assertNotIn(str(self.school.pk), html)

    def test_cluster_and_protected_names_do_not_trigger_lookup(self):
        with self.assertNumQueries(0):
            html = self.render_response('{% school_identity "School identity protected" %}')
        self.assertEqual(html, 'School identity protected')

    def test_missing_reference_does_not_expose_database_identifier(self):
        html = self.render_response('{% school_identity "School" "unknown-private-key" %}')
        self.assertIn('ID unavailable', html)
        self.assertNotIn('unknown-private-key', html)

    def test_urgent_columns_and_school_code(self):
        request = RequestFactory().get('/')
        rows = [{'school_id': self.school.pk, 'school': self.school.name,
                 'district': 'Kampala', 'owner_name': 'Jane Officer',
                 'issue': 'Low SSA', 'shipping_address': 'Plot 7',
                 'recommended_activity_label': 'Schedule visit'}]
        response = SchoolIdentityMiddleware(lambda req: HttpResponse(render_to_string(
            'partials/dashboards/urgent_schools_table.html',
            {'urgent_schools': rows, 'request': req},
        )))(request)
        html = response.content.decode()
        from html.parser import HTMLParser
        class Headers(HTMLParser):
            def __init__(self):
                super().__init__(); self.headers=[]; self.active=False
            def handle_starttag(self, tag, attrs):
                if tag == 'th' and ('scope', 'col') in attrs: self.active=True
            def handle_endtag(self, tag):
                if tag == 'th': self.active=False
            def handle_data(self, data):
                if self.active and data.strip(): self.headers.append(data.strip().lower())
        parser=Headers(); parser.feed(html)
        self.assertEqual(parser.headers, ['district', 'school id', 'school name', 'staff name',
            'priority issue', 'shipping address', 'recommended response', 'action'])
        for value in ['ED-0042', 'Grace &amp; Hope', 'Jane Officer', 'Plot 7']:
            self.assertIn(value, html)

    def test_all_templates_compile(self):
        engine = engines['django'].engine
        for path in Path('templates').rglob('*.html'):
            with self.subTest(template=str(path)):
                engine.get_template(str(path.relative_to('templates')))
