"""Auth DTO serializers (login, refresh, reset, set-password)."""
from __future__ import annotations

from rest_framework import serializers

from apps.core.serializers import LenientSerializer


class LoginSerializer(LenientSerializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)
    activeRole = serializers.CharField(required=False, allow_blank=True)


class RefreshSerializer(LenientSerializer):
    refreshToken = serializers.CharField(trim_whitespace=False)


class LogoutSerializer(LenientSerializer):
    refreshToken = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)


class ForgotPasswordSerializer(LenientSerializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(LenientSerializer):
    token = serializers.CharField(trim_whitespace=False)
    password = serializers.CharField(trim_whitespace=False)
    confirm = serializers.CharField(trim_whitespace=False)


class SetPasswordSerializer(LenientSerializer):
    token = serializers.CharField(trim_whitespace=False)
    password = serializers.CharField(trim_whitespace=False)
    confirm = serializers.CharField(trim_whitespace=False)


class InviteValidateSerializer(LenientSerializer):
    token = serializers.CharField(trim_whitespace=False)
