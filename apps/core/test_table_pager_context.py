from urllib.parse import parse_qs

from django.test import RequestFactory, SimpleTestCase

from apps.core.templatetags.table_pagination import pager_query


class PagerContextTests(SimpleTestCase):
    def test_preserves_other_tables_and_repeated_filters(self):
        request = RequestFactory().get(
            "/plan?district=A&district=B&school_page=2&cluster_page=3&q=school+%26+college"
        )
        query = parse_qs(pager_query({"request": request}, "school_page"))
        self.assertEqual(
            query,
            {"district": ["A", "B"], "cluster_page": ["3"], "q": ["school & college"]},
        )

    def test_no_request_or_no_filters(self):
        self.assertEqual(pager_query({}, "page"), "")
        self.assertEqual(
            pager_query({"request": RequestFactory().get("/?page=2")}, "page"), ""
        )
