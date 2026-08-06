"""Geography endpoints — cascading admin-boundary reads (/api/geography/*)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import District, Parish, Region, SubCounty, Village
from .serializers import (
    DistrictSerializer,
    ParishSerializer,
    RegionSerializer,
    SubCountySerializer,
    VillageSerializer,
)


class RegionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        qs = Region.objects.all().order_by("name")
        return Response(RegionSerializer(qs, many=True).data)


class DistrictListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        region_id = request.query_params.get("regionId")
        qs = District.objects.all()
        if region_id:
            qs = qs.filter(region_id=region_id)
        qs = qs.select_related("region").order_by("name")
        return Response(DistrictSerializer(qs, many=True).data)


class SubCountyListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        district_id = request.query_params.get("districtId")
        if district_id:
            qs = SubCounty.objects.filter(district_id=district_id).order_by("name")
        else:
            qs = SubCounty.objects.all().order_by("name")
        return Response(SubCountySerializer(qs, many=True).data)


class ParishListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        sub_county_id = request.query_params.get("subCountyId", "")
        qs = Parish.objects.filter(sub_county_id=sub_county_id).order_by("name")
        return Response(ParishSerializer(qs, many=True).data)


class VillageListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        parish_id = request.query_params.get("parishId", "")
        qs = Village.objects.filter(parish_id=parish_id).order_by("name")
        return Response(VillageSerializer(qs, many=True).data)
