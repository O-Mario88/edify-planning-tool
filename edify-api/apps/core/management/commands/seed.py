"""
Seed management command — ports prisma/seed.ts.

`manage.py seed`:
  1. ALWAYS: seed the Permission + RolePermission tables from the RBAC matrix.
  2. ALWAYS: upsert the demo role accounts (shared DEMO_LOGIN_PASSWORD) and the
     super-admin (SUPER_ADMIN_PASSWORD). On re-seed, the password is updated so
     a rotated demo secret stays in lockstep with the frontend bridge.
  3. GATED (ENABLE_MOCK_DATA=true & non-production): real Uganda geography,
     ~700 schools, baseline+follow-up SSA, partners, cost settings, projects,
     and sample activities across workflow states.

The demo password contract is the SAME as the frontend bridge
(DEMO_LOGIN_PASSWORD, default 'edify'); the super-admin password is env-only.
"""
from __future__ import annotations

import random

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import (
    Permission, RolePermission, StaffProfile, User,
)
from apps.core.rbac import (
    EdifyRole, ROLE_PERMISSIONS, all_permission_keys,
)


# Demo role accounts — shared DEMO_LOGIN_PASSWORD (lockstep with the FE bridge).
DEMO_ACCOUNTS = [
    ("admin@edify.org", "Edify Admin", EdifyRole.ADMIN.value),
    ("cd@edify.org", "Sarah Okello", EdifyRole.COUNTRY_DIRECTOR.value),
    ("ia@edify.org", "Grace Alimo", EdifyRole.IMPACT_ASSESSMENT.value),
    ("rvp@edify.org", "Robert Vance", EdifyRole.REGIONAL_VICE_PRESIDENT.value),
    ("accountant@edify.org", "Moses Tindi", EdifyRole.PROGRAM_ACCOUNTANT.value),
    ("hr@edify.org", "Hellen Auma", EdifyRole.HUMAN_RESOURCES.value),
    ("coordinator@edify.org", "Allan Ssentongo", EdifyRole.PROJECT_COORDINATOR.value),
    ("partner@edify.org", "Literacy Uganda Officer", EdifyRole.PARTNER_FIELD_OFFICER.value),
]

SUPER_ADMIN_EMAIL = "domario@edify.org"


# Realistic Uganda geography (region → district → sub-county).
GEOGRAPHY = [
    {"name": "Northern", "districts": [
        {"name": "Lira", "subCounties": ["Lira TC", "Aromo", "Ogur"]},
        {"name": "Gulu", "subCounties": ["Gulu TC", "Bungatira", "Unyama"]},
        {"name": "Kitgum", "subCounties": ["Kitgum TC", "Namokora", "Mucwini"]},
    ]},
    {"name": "Eastern", "districts": [
        {"name": "Soroti", "subCounties": ["Soroti TC", "Arapai", "Kami", "Katine"]},
        {"name": "Mbale", "subCounties": ["Mbale TC", "Bukonde", "Bungokho"]},
        {"name": "Jinja", "subCounties": ["Jinja TC", "Butagaya", "Budondo"]},
    ]},
    {"name": "Western", "districts": [
        {"name": "Mbarara", "subCounties": ["Mbarara TC", "Bwizibwera", "Kashanyaraazi"]},
        {"name": "Fort Portal", "subCounties": ["Fort Portal TC", "Kikojo", "Buheesi"]},
        {"name": "Kasese", "subCounties": ["Kasese TC", "Rukoki", "Bwera"]},
    ]},
    {"name": "Central", "districts": [
        {"name": "Kampala", "subCounties": ["Kampala Central", "Rubaga", "Nakawa"]},
        {"name": "Mukono", "subCounties": ["Mukono TC", "Ntunga", "Kyampisi"]},
        {"name": "Wakiso", "subCounties": ["Wakiso TC", "Nangabo", "Ssisa"]},
    ]},
]

SUB_COUNTY_SCHOOLS = [
    "Primary School", "UMEA Primary School", "Church of Uganda Primary",
    "Mosque Road Primary", "Hill Primary", "Valley Primary",
]


class Command(BaseCommand):
    help = "Seed the permission matrix + demo data (gated on ENABLE_MOCK_DATA)."

    def add_arguments(self, parser):
        parser.add_argument("--mock", action="store_true", help="Force the mock-data demo seed.")
        parser.add_argument("--reset", action="store_true", help="Purge operational data before seeding demo data.")

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding Edify API..."))
        self._seed_permissions()
        self._seed_accounts()
        if self._mock_enabled(options):
            if options["reset"]:
                self._purge_operational()
            self._seed_geography()
            self._seed_demo_data()
        else:
            self.stdout.write("Mock data skipped (ENABLE_MOCK_DATA=false).")
        self.stdout.write(self.style.SUCCESS("Seed complete."))

    # ── Always-run ──────────────────────────────────────────────────────────
    def _seed_permissions(self):
        from apps.core.rbac import ROLE_PERMISSIONS, Permission as Perm

        for key in all_permission_keys():
            Permission.objects.update_or_create(key=key, defaults={"description": key})
        # Map role -> permissions.
        key_to_perm = {p.key: p for p in Permission.objects.all()}
        for role, perms in ROLE_PERMISSIONS.items():
            for perm in perms:
                RolePermission.objects.update_or_create(
                    role=role.value, permission=key_to_perm[perm.value],
                )
        self.stdout.write(f"  permissions: {Permission.objects.count()} keys, "
                          f"{RolePermission.objects.count()} role grants.")

    def _seed_accounts(self):
        """Upsert demo accounts + super-admin. Re-seed updates the password."""
        demo_pw = settings.DEMO_LOGIN_PASSWORD
        super_pw = settings.SUPER_ADMIN_PASSWORD
        # Demo role accounts.
        for email, name, role in DEMO_ACCOUNTS:
            u, created = User.objects.update_or_create(
                email=email,
                defaults={"name": name, "roles": [role], "active_role": role,
                          "status": "active", "is_active": True},
            )
            u.set_password(demo_pw)
            u.save()
        # Super-admin (env-only password; never a hardcoded fallback).
        if super_pw:
            u, created = User.objects.update_or_create(
                email=SUPER_ADMIN_EMAIL,
                defaults={"name": "Omario Edwin", "roles": [EdifyRole.ADMIN.value],
                          "active_role": EdifyRole.ADMIN.value, "status": "active", "is_active": True},
            )
            u.set_password(super_pw)
            u.password_set_at = timezone_now()
            u.save()
        # Program Leads (4) + CCEOs (20) with staff profiles + supervisor links.
        pls = []
        for i in range(1, 5):
            u, _ = User.objects.update_or_create(
                email=f"pl{i}@edify.org",
                defaults={"name": f"Program Lead {i}", "roles": [EdifyRole.COUNTRY_PROGRAM_LEAD.value],
                          "active_role": EdifyRole.COUNTRY_PROGRAM_LEAD.value, "status": "active", "is_active": True},
            )
            u.set_password(demo_pw); u.save()
            sp, _ = StaffProfile.objects.update_or_create(user=u, defaults={"onboarding_state": "active"})
            pls.append(sp)
        cceos = []
        for i in range(20):
            email = "cceo@edify.org" if i == 0 else f"cceo{i}@edify.org"
            u, _ = User.objects.update_or_create(
                email=email,
                defaults={"name": f"CCEO {i + 1}", "roles": [EdifyRole.CCEO.value],
                          "active_role": EdifyRole.CCEO.value, "status": "active", "is_active": True},
            )
            u.set_password(demo_pw); u.save()
            sp, _ = StaffProfile.objects.update_or_create(user=u, defaults={"onboarding_state": "active"})
            cceos.append(sp)
        # Link each CCEO to the first PL (the demo supervisor).
        from apps.accounts.models import StaffSupervisorAssignment
        for cceo in cceos:
            StaffSupervisorAssignment.objects.get_or_create(supervisee=cceo, supervisor=pls[0])
        self.stdout.write(f"  users: {User.objects.count()} (8 demo + 1 super-admin + 4 PL + 20 CCEO).")

    # ── Gated demo data ─────────────────────────────────────────────────────
    def _mock_enabled(self, options) -> bool:
        if options.get("mock"):
            return True
        if settings.IS_PRODUCTION:
            return False
        return bool(getattr(settings, "ENABLE_MOCK_DATA", False))

    def _purge_operational(self):
        """TRUNCATE operational tables (keep users + geography + reference)."""
        from apps.activities.models import Activity
        from apps.schools.models import School
        from apps.ssa.models import SsaRecord
        from apps.clusters.models import Cluster
        from apps.partners.models import Partner

        Activity.objects.all().delete()
        SsaRecord.objects.all().delete()
        School.objects.all().delete()
        Cluster.objects.all().delete()
        Partner.objects.all().delete()
        self.stdout.write("  purged operational data.")

    def _seed_geography(self):
        from apps.geography.models import Region, District, SubCounty

        for r in GEOGRAPHY:
            region, _ = Region.objects.get_or_create(name=f"{r['name']} Region")
            for d in r["districts"]:
                district, _ = District.objects.get_or_create(name=d["name"], region=region)
                for sc in d["subCounties"]:
                    SubCounty.objects.get_or_create(name=sc, district=district)
        self.stdout.write(f"  geography: {Region.objects.count()} regions, "
                          f"{District.objects.count()} districts, "
                          f"{SubCounty.objects.count()} sub-counties.")

    def _seed_demo_data(self):
        from apps.geography.models import District, SubCounty
        from apps.schools.models import School, SchoolEnrollmentHistory
        from apps.partners.models import Partner
        from apps.budget.models import CostSetting
        from apps.projects.models import Project
        from apps.ssa.models import SsaRecord, SsaScore
        from apps.ssa.services import _recompute_readiness
        from apps.core.enums import SsaIntervention, SchoolType
        from apps.core.fy import get_operational_fy

        districts = list(District.objects.all())
        subs = list(SubCounty.objects.all())
        rnd = random.Random(42)

        # 700 schools across districts.
        schools = []
        for i in range(700):
            d = rnd.choice(districts)
            sc = rnd.choice([s for s in subs if s.district_id == d.id] or subs)
            enrollment = rnd.randint(80, 900)
            school_type = rnd.choices(
                [SchoolType.CLIENT.value, SchoolType.CORE.value, SchoolType.CHAMPION.value],
                weights=[80, 15, 5])[0]
            s = School.objects.create(
                school_id=f"S-{1000 + i}",
                name=f"{sc.name} {SUB_COUNTY_SCHOOLS[i % len(SUB_COUNTY_SCHOOLS)]}",
                region=d.region, district=d, sub_county=sc,
                enrollment=enrollment,
                school_type=school_type,
                current_fy_ssa_status="done" if rnd.random() < 0.15 else "not_done",
            )
            _recompute_readiness(s)
            schools.append(s)
        self.stdout.write(f"  schools: {School.objects.count()}")

        # Baseline (prior FY) + follow-up (current FY for core) SSA.
        interventions = [i.value for i in SsaIntervention]
        fy = get_operational_fy()
        prev_fy = str(int(fy) - 1)
        from django.utils import timezone
        for s in schools:
            for fyyy, score_base in [(prev_fy, 3.0), (fy, 4.0)]:
                if fyyy == fy and s.school_type == SchoolType.CLIENT.value and rnd.random() > 0.3:
                    continue  # not every client has a current-FY SSA
                avg = round(score_base + rnd.random() * 4, 1)
                rec = SsaRecord.objects.create(
                    school=s, fy=fyyy, quarter="Q1",
                    date_of_ssa=timezone.now(),
                    average_score=avg, uploaded_by="seed",
                    collector_type="staff", verification_status="confirmed",
                    verification_source="staff_self_verified",
                )
                for interv in interventions:
                    SsaScore.objects.create(ssa_record=rec, intervention=interv,
                                            score=round(max(0, min(10, avg + rnd.uniform(-1.5, 1.5))), 1))
        self.stdout.write(f"  SSA records: {SsaRecord.objects.count()}")

        # 5 partners (active + certified), linked to the partner demo user.
        partner_user = User.objects.filter(email="partner@edify.org").first()
        for i, name in enumerate(["Literacy Uganda", "Build Africa", "World Reader",
                                  "Pangea Educational", "Room to Read"]):
            Partner.objects.get_or_create(
                name=name,
                defaults={
                    "region_name": rnd.choice(["Northern Region", "Eastern Region"]),
                    "coverage_districts": [d.name for d in districts[:3]],
                    "is_certified": i % 2 == 0, "active_status": True,
                    "contract_status": "active",
                    "user": partner_user if i == 0 else None,
                },
            )
        self.stdout.write(f"  partners: {Partner.objects.count()}")

        # 14 cost settings (the CD Cost Catalogue).
        rate_card = {
            "staff_visit_transport_primary": 15000, "lunch": 10000,
            "breakfast": 8000, "dinner": 12000, "accommodation": 40000,
            "staff_visit_transport_secondary": 25000,
            "training_session_fee": 50000, "venue": 30000,
            "meals_per_participant": 5000, "mobilisation_per_participant": 2000,
            "cluster_meeting_cost": 10000, "partner_visit_lump_sum": 35000,
            "partner_training_lump_sum": 120000,
        }
        for key, cost in rate_card.items():
            CostSetting.objects.update_or_create(key=key, defaults={"label": key.replace("_", " ").title(), "unit_cost": cost})
        self.stdout.write(f"  cost settings: {CostSetting.objects.count()}")

        # 5 special projects.
        for code, name in [("SP-EDTECH", "EdTech Pilot"), ("SP-CCSEL", "CCSEL"),
                           ("SP-DIP", "DIP"), ("SP-ECC", "ECC"), ("SP-UCU", "UCU")]:
            Project.objects.get_or_create(code=code, defaults={"name": name, "category": "pilot"})
        self.stdout.write(f"  projects: {Project.objects.count()}")


def timezone_now():
    from django.utils import timezone
    return timezone.now()
