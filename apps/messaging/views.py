"""Messaging endpoints — /api/messages/*."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class MessageListSendView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.recent(request.user, _q(request)))

    def post(self, request: Request) -> Response:
        return Response(services.send(request.data, request.user), status=201)


class MessageCountsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.counts(request.user))


class MessageRecipientsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.recipients(request.user))


class MessageContextsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response(services.contexts(_q(request), request.user))


class MessageThreadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, thread_id: str) -> Response:
        return Response(services.thread(thread_id, request.user))


class MessageReplyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, thread_id: str) -> Response:
        return Response(
            services.reply(thread_id, request.data, request.user), status=201
        )


class MessageReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request: Request, message_id: str) -> Response:
        return Response(services.mark_read(message_id, request.user))
