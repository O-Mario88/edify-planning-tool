from django.test import SimpleTestCase

from apps.core.openapi import EdifyAutoSchema, normalize_api_prefix_paths
from rest_framework.views import APIView


class OpenApiContractTests(SimpleTestCase):
    def test_boundary_regex_path_is_normalized_for_path_parameters(self):
        callback = object()
        endpoints = [
            (
                "/api/schools{school_id}",
                r"^api/schools(?:/|$)<str:school_id>",
                "GET",
                callback,
            ),
        ]
        self.assertEqual(
            normalize_api_prefix_paths(endpoints),
            [
                (
                    "/api/schools/{school_id}",
                    r"^api/schools(?:/|$)<str:school_id>",
                    "GET",
                    callback,
                )
            ],
        )

    def test_path_parameter_makes_detail_operation_id_unique(self):
        schema = EdifyAutoSchema()
        schema.path = "/api/schools/{school_id}"
        schema.path_regex = r"^api/schools/(?P<school_id>[^/.]+)$"
        schema.path_prefix = "/api"
        schema.method = "GET"
        schema.view = APIView()
        self.assertTrue(schema.get_operation_id().endswith("_by_school_id"))
