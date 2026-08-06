"""Schools serializers."""

from __future__ import annotations

from rest_framework import serializers

from .models import School


class SchoolRowSerializer(serializers.ModelSerializer):
    """List-row shape — includes resolved geography names."""

    region = serializers.SerializerMethodField()
    district = serializers.SerializerMethodField()
    subCounty = serializers.SerializerMethodField()
    parish = serializers.SerializerMethodField()
    clusterId = serializers.CharField(source="cluster_id")
    schoolId = serializers.CharField(source="school_id")
    schoolType = serializers.CharField(source="school_type")
    clusterStatus = serializers.CharField(source="cluster_status")
    currentFySsaStatus = serializers.CharField(source="current_fy_ssa_status")
    planningReadiness = serializers.CharField(source="planning_readiness")
    accountOwnerStatus = serializers.CharField(source="account_owner_status")
    accountOwnerNameRaw = serializers.CharField(source="account_owner_name_raw")
    duplicateStatus = serializers.CharField(source="duplicate_status")

    class Meta:
        model = School
        fields = [
            "id",
            "schoolId",
            "name",
            "schoolType",
            "clusterId",
            "clusterStatus",
            "currentFySsaStatus",
            "planningReadiness",
            "accountOwnerStatus",
            "accountOwnerNameRaw",
            "duplicateStatus",
            "enrollment",
            "region",
            "district",
            "subCounty",
            "parish",
            "latitude",
            "longitude",
        ]

    def get_region(self, obj):
        return {"name": obj.region.name} if obj.region_id else None

    def get_district(self, obj):
        return {"name": obj.district.name} if obj.district_id else None

    def get_subCounty(self, obj):
        return {"name": obj.sub_county.name} if obj.sub_county_id else None

    def get_parish(self, obj):
        return {"name": obj.parish.name} if obj.parish_id else None


class SchoolDetailSerializer(SchoolRowSerializer):
    """Detail shape — adds the full geography + contact + audit fields."""

    class Meta(SchoolRowSerializer.Meta):
        fields = SchoolRowSerializer.Meta.fields + [
            "shippingAddress",
            "schoolPhone",
            "primaryContactName",
            "primaryContactPhone",
            "uploadedRegionText",
            "uploadedDistrictText",
            "uploadedSubCountyText",
            "uploadedParishText",
            "geographyMatchStatus",
            "geographyMatchConfidence",
            "salesforceAccountId",
            "createdByIa",
        ]

    shippingAddress = serializers.CharField(source="shipping_address")
    schoolPhone = serializers.CharField(source="school_phone")
    primaryContactName = serializers.CharField(source="primary_contact_name")
    primaryContactPhone = serializers.CharField(source="primary_contact_phone")
    uploadedRegionText = serializers.CharField(source="uploaded_region_text")
    uploadedDistrictText = serializers.CharField(source="uploaded_district_text")
    uploadedSubCountyText = serializers.CharField(source="uploaded_sub_county_text")
    uploadedParishText = serializers.CharField(source="uploaded_parish_text")
    geographyMatchStatus = serializers.CharField(source="geography_match_status")
    geographyMatchConfidence = serializers.FloatField(
        source="geography_match_confidence"
    )
    salesforceAccountId = serializers.CharField(source="salesforce_account_id")
    createdByIa = serializers.BooleanField(source="created_by_ia")
