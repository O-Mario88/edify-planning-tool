"""Regenerate the role x surface authorization matrix (mandate §45.5)."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.system_health.permission_matrix import (
    build_permission_matrix,
    matrix_as_json,
    matrix_as_markdown,
)

JSON_PATH = Path(settings.BASE_DIR) / "docs" / "platform-permission-matrix.json"
MARKDOWN_PATH = Path(settings.BASE_DIR) / "docs" / "platform-permission-matrix.md"


class Command(BaseCommand):
    help = "Write docs/platform-permission-matrix.{json,md} from the live source."

    def handle(self, *args, **options):
        matrix = build_permission_matrix()
        JSON_PATH.write_text(matrix_as_json(matrix), encoding="utf-8")
        MARKDOWN_PATH.write_text(matrix_as_markdown(matrix), encoding="utf-8")
        summary = matrix["summary"]
        for key, value in summary.items():
            self.stdout.write(f"  {key}: {value}")
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {JSON_PATH.name} and {MARKDOWN_PATH.name}")
        )
