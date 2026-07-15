"""Django-admin registration for the geography hierarchy.

The app's own UI can classify districts and manage secondary-district groups
(/admin-panel/region-district-setup) but has no way to CREATE Regions — and
districts can only be created inside an existing Region. On a fresh
production database that made the whole geography → schools → activities
chain unreachable. /admin/ (super-admin only) is the deliberate bootstrap
surface for that reference data; day-to-day operations still happen in the
app UI.
"""

from django.contrib import admin

from .models import District, Region, SubCounty


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("name", "pcode")
    search_fields = ("name", "pcode")


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "region", "district_type", "pcode")
    list_filter = ("region", "district_type")
    search_fields = ("name", "pcode")


@admin.register(SubCounty)
class SubCountyAdmin(admin.ModelAdmin):
    list_display = ("name", "district", "pcode")
    list_filter = ("district__region",)
    search_fields = ("name", "pcode")
