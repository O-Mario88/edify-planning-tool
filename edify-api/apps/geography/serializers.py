"""Geography serializers."""
from __future__ import annotations

from rest_framework import serializers

from .models import District, Parish, Region, SubCounty, Village


class RegionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Region
        fields = ["id", "name", "code", "pcode", "source", "latitude", "longitude"]


class DistrictSerializer(serializers.ModelSerializer):
    region = serializers.SerializerMethodField()

    class Meta:
        model = District
        fields = ["id", "name", "code", "pcode", "region_id", "region", "latitude", "longitude"]

    def get_region(self, obj):
        return {"name": obj.region.name} if obj.region_id else None


class SubCountySerializer(serializers.ModelSerializer):
    class Meta:
        model = SubCounty
        fields = ["id", "name", "pcode", "source", "district_id", "latitude", "longitude"]


class ParishSerializer(serializers.ModelSerializer):
    class Meta:
        model = Parish
        fields = ["id", "name", "source"]


class VillageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Village
        fields = ["id", "name"]
