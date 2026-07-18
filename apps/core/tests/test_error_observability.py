from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from apps.core.middleware import AllExceptionsMiddleware
from apps.core.request_context import RequestContext, set_request_context


class UnhandledRequestAuditTest(SimpleTestCase):
    def test_500_response_writes_a_safe_correlation_audit_record(self):
        request = RequestFactory().post("/team-targets/catchup")
        request.user = SimpleNamespace(
            is_authenticated=True, id="usr_123", active_role="ProgramLead"
        )
        set_request_context(
            RequestContext(
                ip_address="127.0.0.1",
                user_agent="test-agent",
                correlation_id="correlation-123",
            )
        )
        middleware = AllExceptionsMiddleware(lambda _: None)

        with (
            patch("apps.audit.services.log") as audit_log,
            patch("apps.core.middleware.logger.exception") as exception_log,
        ):
            response = middleware.process_exception(request, RuntimeError("secret"))

        self.assertEqual(response.status_code, 500)
        self.assertEqual(audit_log.call_count, 1)
        exception_log.assert_called_once()
        self.assertEqual(
            audit_log.call_args.kwargs,
            {
                "action": "request_failed",
                "subject_kind": "Request",
                "subject_id": "/team-targets/catchup",
                "actor_id": "usr_123",
                "actor_role": "ProgramLead",
                "success": False,
                "reason": "Unhandled RuntimeError",
                "payload": {
                    "method": "POST",
                    "path": "/team-targets/catchup",
                    "exception_type": "RuntimeError",
                },
            },
        )
