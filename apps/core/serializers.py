"""
Serializer base classes.

`LenientSerializer` reproduces the NestJS `ValidationPipe` with
`whitelist:true, forbidNonWhitelisted:false`: unknown JSON keys are silently
dropped, never rejected with a 400. The legacy backend intentionally avoided
`forbidNonWhitelisted` because the frontend sends best-effort bodies and an
extra/renamed field must be dropped, not rejected (see edify-api.legacy main.ts).
"""
from __future__ import annotations

from typing import Any

from rest_framework import serializers


class LenientSerializer(serializers.Serializer):
    """Drop unknown input keys instead of raising a validation error.

    DRF's default `to_internal_value` rejects unknown fields with a 400. We
    override `run_validation` to strip them first, matching the NestJS lenient
    validation contract.
    """

    def run_validation(self, data: Any = serializers.empty) -> Any:
        if isinstance(data, dict):
            known = set(self.fields.keys())
            data = {k: v for k, v in data.items() if k in known}
        return super().run_validation(data)


class StrictModelSerializer(serializers.ModelSerializer):
    """Model serializer that also drops unknown fields (same leniency)."""

    def run_validation(self, data: Any = serializers.empty) -> Any:
        if isinstance(data, dict):
            known = set(self.fields.keys())
            data = {k: v for k, v in data.items() if k in known}
        return super().run_validation(data)


__all__ = ["LenientSerializer", "StrictModelSerializer"]
