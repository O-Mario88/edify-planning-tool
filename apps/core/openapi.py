"""OpenAPI integration for Edify's dictionary-returning DRF APIViews."""

from __future__ import annotations

import re

from drf_spectacular.extensions import OpenApiAuthenticationExtension
from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import build_bearer_security_scheme_object
from drf_spectacular.types import OpenApiTypes
from rest_framework.views import APIView


class EdifyAutoSchema(AutoSchema):
    """Keep legacy APIViews visible without emitting an unusable empty schema.

    Most Edify endpoints deliberately return service dictionaries rather than
    model serializers. Field-level serializers remain preferable, but a
    truthful free-form JSON contract is safer than silently dropping hundreds
    of live endpoints from the generated document.
    """

    def _get_serializer(self):
        view = self.view
        if isinstance(view, APIView) and not any(
            (
                callable(getattr(view, "get_serializer", None)),
                callable(getattr(view, "get_serializer_class", None)),
                hasattr(view, "serializer_class"),
            )
        ):
            return OpenApiTypes.OBJECT
        return super()._get_serializer()

    def get_operation_id(self) -> str:
        operation_id = super().get_operation_id()
        variables = re.findall(r"\{([\w-]+)\}", self.path)
        if variables:
            operation_id += "_by_" + "_and_".join(
                variable.replace("-", "_") for variable in variables
            )
        return operation_id


class JwtAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.jwt.JwtAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return build_bearer_security_scheme_object(
            header_name="Authorization",
            token_prefix="Bearer",
        )


def normalize_api_prefix_paths(endpoints, **kwargs):
    """Restore the slash consumed by the boundary-aware root URL regex."""
    normalized = []
    for path, path_regex, method, callback in endpoints:
        prefix_match = re.match(
            r"^\^?api/(?P<prefix>.*?)\(\?:/\|\$\)",
            path_regex,
        )
        if prefix_match:
            root = f"/api/{prefix_match.group('prefix')}"
            if path.startswith(root) and len(path) > len(root):
                suffix = path[len(root) :]
                if not suffix.startswith("/"):
                    path = f"{root}/{suffix}"
        path = re.sub(r"(?<!/)(\{[^/{}]+\})", r"/\1", path)
        normalized.append((path, path_regex, method, callback))
    return normalized
