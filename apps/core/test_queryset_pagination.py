"""`{% paginate %}` pages a QuerySet in the database, not in Python.

`paginate_rows` used to call `list(rows)` on anything that was not a lazy
sequence, and the template tag passed `rows or []`, whose truth test fetches a
QuerySet in full. Every table fed a QuerySet therefore loaded every row to
draw ten: the Blocked Closures page loaded every blocker in scope, each with
its activity and school joined (2026-09-24 live-performance audit, PERF-03).
"""

from django.template import Context, Template
from django.test import RequestFactory, TestCase

from apps.core.pagination import paginate_rows
from apps.geography.models import Region


class QuerySetPaginationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        Region.objects.bulk_create(
            [Region(name=f"Pager Region {i:03d}") for i in range(35)]
        )

    def _regions(self):
        return Region.objects.filter(name__startswith="Pager Region").order_by("name")

    def test_a_queryset_is_counted_and_sliced_not_fetched(self):
        # One COUNT and one LIMIT/OFFSET page, whatever the table's size.
        with self.assertNumQueries(2):
            page = paginate_rows(self._regions(), page=2, page_size=10)
        self.assertEqual(page["total"], 35)
        self.assertEqual(page["page_count"], 4)
        self.assertEqual(
            [r.name for r in page["rows"]],
            [f"Pager Region {i:03d}" for i in range(10, 20)],
        )
        self.assertIsInstance(page["rows"], list)

    def test_an_out_of_range_page_clamps_to_the_last_page(self):
        page = paginate_rows(self._regions(), page=99, page_size=10)
        self.assertEqual(page["page"], 4)
        self.assertEqual(len(page["rows"]), 5)
        self.assertEqual(page["first_index"], 31)
        self.assertEqual(page["last_index"], 35)

    def test_an_evaluated_queryset_is_not_queried_again(self):
        regions = self._regions()
        list(regions)
        with self.assertNumQueries(0):
            page = paginate_rows(regions, page=1, page_size=10)
        self.assertEqual(page["total"], 35)

    def test_an_empty_queryset_is_one_count(self):
        with self.assertNumQueries(1):
            page = paginate_rows(Region.objects.filter(name="No such region"), page=1)
        self.assertEqual(page["total"], 0)
        self.assertEqual(page["rows"], [])
        self.assertFalse(page["paginated"])

    def test_lists_still_page_in_memory(self):
        page = paginate_rows(list(range(25)), page=3, page_size=10)
        self.assertEqual(page["rows"], [20, 21, 22, 23, 24])

    def test_the_template_tag_does_not_truth_test_the_queryset(self):
        template = Template(
            "{% load table_pagination %}"
            '{% paginate regions "regions_page" as pager %}'
            "{% for r in pager.rows %}{{ r.name }};{% endfor %}|{{ pager.total }}"
        )
        request = RequestFactory().get("/?regions_page=4")
        with self.assertNumQueries(2):
            out = template.render(
                Context({"regions": self._regions(), "request": request})
            )
        self.assertTrue(out.endswith("|35"))
        self.assertEqual(out.count(";"), 5)

    def test_a_missing_variable_renders_an_empty_table(self):
        template = Template(
            "{% load table_pagination %}"
            '{% paginate missing "p" as pager %}{{ pager.total }}'
        )
        self.assertEqual(template.render(Context({})), "0")
