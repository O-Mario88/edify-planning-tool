"""
Pagination matching the NestJS `Paginated<T>` envelope.

Input:  `?page=1&pageSize=25&sortBy=<field>&sortDir=asc|desc`
Output: `{data: [...], page, pageSize, total, totalPages}`

Mirrors `PaginationDto` (1-based page, default 25, max 200; `skip`/`take` are
derived and explicitly ignored if sent inbound). Response arrays must never be
null/undefined — the frontend surfaces a DATA_CONTRACT_VIOLATION otherwise.
"""
from __future__ import annotations

from rest_framework.pagination import BasePagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.serializer_helpers import ReturnList


class EdifyPagination(BasePagination):
    page_query_param = "page"
    page_size_query_param = "pageSize"
    sort_by_query_param = "sortBy"
    sort_dir_query_param = "sortDir"

    default_page_size = 25
    max_page_size = 200

    def paginate_queryset(self, queryset, request: Request, view=None):
        self._request = request
        self._page = self._get_int(request, self.page_query_param, default=1, minimum=1)
        self._page_size = self._get_int(
            request,
            self.page_size_query_param,
            default=self.default_page_size,
            minimum=1,
            maximum=self.max_page_size,
        )

        sort_by = request.query_params.get(self.sort_by_query_param)
        sort_dir = (request.query_params.get(self.sort_dir_query_param) or "asc").lower()
        if sort_by:
            prefix = "-" if sort_dir == "desc" else ""
            # Defensive: only allow simple field names (no `__`, no relations)
            # to avoid injection via arbitrary ORM ordering. Relations can use
            # `field__related` once whitelisted per-view.
            if sort_by.replace("_", "").replace(".", "").isalnum():
                queryset = queryset.order_by(f"{prefix}{sort_by}")

        self._total = queryset.count()
        offset = (self._page - 1) * self._page_size
        self._list = list(queryset[offset : offset + self._page_size])  # noqa: E203
        return self._list

    def get_paginated_response(self, data) -> Response:
        total_pages = (self._total + self._page_size - 1) // self._page_size or 1
        return Response(
            {
                "data": data,
                "page": self._page,
                "pageSize": self._page_size,
                "total": self._total,
                "totalPages": total_pages,
            }
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "data": {"type": "array", "items": schema},
                "page": {"type": "integer"},
                "pageSize": {"type": "integer"},
                "total": {"type": "integer"},
                "totalPages": {"type": "integer"},
            },
        }

    @staticmethod
    def _get_int(request: Request, param: str, *, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
        raw = request.query_params.get(param)
        if raw in (None, ""):
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def get_results(self):
        # For nested-routers / convenience.
        if isinstance(self._list, ReturnList):
            return list(self._list)
        return self._list
