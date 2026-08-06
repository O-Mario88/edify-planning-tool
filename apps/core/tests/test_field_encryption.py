"""Regression coverage for the production field-encryption boot gate."""

from django.test import SimpleTestCase

from apps.core.crypto import load_field_encryption_key


class FieldEncryptionKeyValidationTest(SimpleTestCase):
    def test_accepts_a_32_byte_hex_key(self):
        self.assertEqual(load_field_encryption_key("ab" * 32), bytes.fromhex("ab" * 32))

    def test_rejects_missing_malformed_and_wrong_length_keys(self):
        for value in ("", "not-base64!", "ab" * 31):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "FIELD_ENCRYPTION_KEY"):
                    load_field_encryption_key(value)
