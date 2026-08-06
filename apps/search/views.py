"""Search endpoint — /api/search."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


class SearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        q = request.query_params.get("q", "")
        context = request.query_params.get("context")
        return Response(services.search(request.user, q, context))
