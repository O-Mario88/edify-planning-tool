"""Resolve explicitly marked school display IDs in one query after rendering.

Only templates opting into school_identity are changed. Names are never used
for lookup. Existing view scoping determines which references reach this step;
this reads only the public display ID of those referenced schools.
"""
import re
from django.db.models import Q
from django.utils.html import format_html


class SchoolIdentityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        refs = getattr(request, '_school_display_references', {})
        if not refs or response.streaming or 'text/html' not in response.get('Content-Type', ''):
            return response
        from apps.schools.models import School
        values = set(refs.values())
        rows = list(School.objects.filter(Q(pk__in=values) | Q(school_id__in=values)).values_list('id', 'school_id'))
        by_pk = {str(pk): code for pk, code in rows}
        by_code = {code: code for _, code in rows}
        def replace(match):
            reference = refs.get(match[1])
            if reference is None:
                return match[0]
            code = by_pk.get(reference) or by_code.get(reference)
            return str(format_html('<span class="school-list-id" title="School ID">{}</span>', code or 'ID unavailable'))
        html = response.content.decode(response.charset)
        html = re.sub(r'<span data-school-code-token="([a-f0-9]{32})"></span>', replace, html)
        response.content = html.encode(response.charset)
        if response.has_header('Content-Length'):
            response['Content-Length'] = str(len(response.content))
        return response
