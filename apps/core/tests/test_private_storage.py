from __future__ import annotations

import os

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, override_settings

from apps.core.exceptions import BadRequest
from apps.core.private_storage import (
    delete_file,
    file_exists,
    materialized_file,
    object_key,
    open_file,
    save_file,
)


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.InMemoryStorage",
        },
        "private_uploads": {
            "BACKEND": "django.core.files.storage.InMemoryStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class PrivateObjectStorageTest(SimpleTestCase):
    def test_private_object_round_trip_and_delete(self):
        name = "0123456789abcdef0123456789abcdef.pdf"
        save_file("evidence", name, ContentFile(b"%PDF-test"))

        self.assertTrue(file_exists("evidence", name))
        with open_file("evidence", name) as stored:
            self.assertEqual(stored.read(), b"%PDF-test")

        delete_file("evidence", name)
        self.assertFalse(file_exists("evidence", name))

    def test_remote_object_is_materialized_only_for_local_processing(self):
        name = "0123456789abcdef0123456789abcdef.docx"
        save_file("documents", name, ContentFile(b"document"))

        with materialized_file("documents", name) as local:
            self.assertTrue(os.path.exists(local))
            with open(local, "rb") as staged:
                self.assertEqual(staged.read(), b"document")
            materialized_path = local

        self.assertFalse(os.path.exists(materialized_path))

    def test_storage_key_rejects_traversal_and_nested_database_values(self):
        for value in ("../secret", "nested/file.pdf", "/etc/passwd", "", ".."):
            with self.subTest(value=value), self.assertRaises(BadRequest):
                object_key("evidence", value)
