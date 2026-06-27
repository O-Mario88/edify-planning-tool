"""
Seed management command — REFERENCE DATA ONLY by default.

The CORE RULE: the database is the only runtime source of truth. Production must
never contain demo schools, demo SSA, demo users, demo budgets, etc. So:

  • `manage.py seed`              → seeds REFERENCE DATA ONLY (the RBAC
                                     permission matrix: Permission +
                                     RolePermission). Idempotent, safe to run
                                     on every deploy.
  • `manage.py seed --demo`       → ALSO seeds demo accounts + sample geography
                                     + sample operational data (local testing
                                     only). REFUSES to run in production.
  • `manage.py seed --demo --reset` → first purges operational tables.

Demo accounts are created with the shared DEMO_LOGIN_PASSWORD (default "edify").
They are intended ONLY for local development and are blocked from production.
The super-admin (SUPER_ADMIN_EMAIL) is admin setup, created only when
SUPER_ADMIN_PASSWORD is set (env-only, never hardcoded) — it is the one account
that may legitimately ship to production.

Reference data (kept):
  - Permission keys + the role→permission matrix (apps.core.rbac.ROLE_PERMISSIONS)
  - (via --demo) Uganda admin-boundary geography: Region/District/SubCounty

Demo/operational data (local only, --demo):
  - demo role accounts, PLs, CCEOs, super-admin
  - sample schools, SSA, partners, cost settings, projects
"""
from __future__ import annotations

import random

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import Permission, RolePermission, StaffProfile, User
from apps.core.rbac import EdifyRole, ROLE_PERMISSIONS, all_permission_keys


SUPER_ADMIN_EMAIL = "domario@edify.org"

# Demo role accounts — shared DEMO_LOGIN_PASSWORD. LOCAL DEVELOPMENT ONLY.
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

# Realistic Uganda geography (reference admin boundaries) — local-test seed only.
GEOGRAPHY = [
    {"name": "Northern", "districts": [
        {"name": "Lira", "subCounties": ["Lira TC", "Aromo", "Ogur"]},
        {"name": "Gulu", "subCounties": ["Gulu TC", "Bungatira", "Unyama"]},
        {"name": "Kitgum", "subCounties": ["Kitgum TC", "Namokora", "Mucwini"]},
    ]},
    {"name": "Eastern", "districts": [
        {"name": "Soroti", "subCounties": ["Soroti TC", "Arapai", "Katine"]},
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


class Command(BaseCommand):
    help = (
        "Seed reference data (RBAC permissions). Use --demo for local-only demo "
        "accounts + sample data (refuses to run in production)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo", action="store_true",
            help="Also seed local-only demo accounts + sample data. Refuses in production.",
        )
        parser.add_argument(
            "--reset", action="store_true",
            help="With --demo: purge operational tables before seeding sample data.",
        )

    def handle(self, *args, **options):
        demo = options["demo"]
        if demo and settings.IS_PRODUCTION:
            raise CommandError(
                "Refusing to seed demo data in production. Demo accounts and sample "
                "data are for local development only — production receives real data "
                "through backend upload/admin workflows."
            )

        self.stdout.write(self.style.MIGRATE_HEADING("Seeding Edify API..."))
        self._seed_permissions()
        if demo:
            if settings.IS_PRODUCTION:  # defensive double-check
                raise CommandError("Demo seed blocked in production.")
            self._seed_demo_accounts()
            self._seed_geography()
            if options["reset"]:
                self._purge_operational()
            self._seed_sample_data()
            self.stdout.write(self.style.WARNING(
                "  ⚠ Demo data seeded — LOCAL DEVELOPMENT ONLY. Do NOT deploy this database."
            ))
        else:
            self.stdout.write("  Reference-only seed complete (no demo data).")
        self.stdout.write(self.style.SUCCESS("Seed complete."))

    # ── Reference data (always) ─────────────────────────────────────────────
    def _seed_permissions(self):
        for key in all_permission_keys():
            Permission.objects.update_or_create(key=key, defaults={"description": key})
        key_to_perm = {p.key: p for p in Permission.objects.all()}
        for role, perms in ROLE_PERMISSIONS.items():
            for perm in perms:
                RolePermission.objects.update_or_create(
                    role=role.value, permission=key_to_perm[perm.value],
                )
        self.stdout.write(
            f"  permissions: {Permission.objects.count()} keys, "
            f"{RolePermission.objects.count()} role grants."
        )

    # ── Demo accounts (local only) ──────────────────────────────────────────
    def _seed_demo_accounts(self):
        from django.utils import timezone

        demo_pw = settings.DEMO_LOGIN_PASSWORD
        super_pw = settings.SUPER_ADMIN_PASSWORD

        for email, name, role in DEMO_ACCOUNTS:
            u, _ = User.objects.update_or_create(
                email=email,
                defaults={"name": name, "roles": [role], "active_role": role,
                          "status": "active", "is_active": True},
            )
            u.set_password(demo_pw)
            u.save()

        # Super-admin — env-only password; the one admin-setup account that may
        # legitimately exist in production. Created only when the secret is set.
        if super_pw:
            u, _ = User.objects.update_or_create(
                email=SUPER_ADMIN_EMAIL,
                defaults={"name": "Omario Edwin", "roles": [EdifyRole.ADMIN.value],
                          "active_role": EdifyRole.ADMIN.value, "status": "active", "is_active": True},
            )
            u.set_password(super_pw)
            u.password_set_at = timezone.now()
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
        from apps.accounts.models import StaffSupervisorAssignment
        for cceo in cceos:
            StaffSupervisorAssignment.objects.get_or_create(supervisee=cceo, supervisor=pls[0])
        self.stdout.write(f"  demo users: {User.objects.count()} (local only).")

    # ── Geography (reference admin boundaries — local-test seed) ────────────
    def _seed_geography(self):
        from apps.geography.models import Region, District, SubCounty

        for r in GEOGRAPHY:
            region, _ = Region.objects.get_or_create(name=f"{r['name']} Region")
            for d in r["districts"]:
                district, _ = District.objects.get_or_create(name=d["name"], region=region)
                for sc in d["subCounties"]:
                    SubCounty.objects.get_or_create(name=sc, district=district)
        self.stdout.write(
            f"  geography: {Region.objects.count()} regions, "
            f"{District.objects.count()} districts, {SubCounty.objects.count()} sub-counties."
        )

    def _purge_operational(self):
        """Purge operational tables (keeps users, geography, reference)."""
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

    def _seed_sample_data(self):
        from apps.geography.models import District, SubCounty
        from apps.schools.models import School
        from apps.partners.models import Partner
        from apps.budget.models import CostSetting
        from apps.projects.models import Project

        districts = list(District.objects.all())
        subs = list(SubCounty.objects.all())
        rnd = random.Random(42)
        name_frags = ["Primary School", "UMEA Primary School", "Church of Uganda Primary", "Hill Primary"]
        for i in range(700):
            d = rnd.choice(districts)
            sc = rnd.choice([s for s in subs if s.district_id == d.id] or subs)
            s = School.objects.create(
                school_id=f"S-{1000 + i}",
                name=f"{sc.name} {name_frags[i % len(name_frags)]}",
                region=d.region, district=d, sub_county=sc,
                enrollment=rnd.randint(80, 900),
                school_type=rnd.choices(["client", "core", "champion"], weights=[80, 15, 5])[0],
                current_fy_ssa_status="done" if rnd.random() < 0.15 else "not_done",
                source="local_test_upload",
            )
            from apps.ssa.services import _recompute_readiness
            _recompute_readiness(s)
        self.stdout.write(f"  sample schools: {School.objects.count()} (local only)")

        # Sample SSA.
        from apps.ssa.models import SsaRecord, SsaScore
        from apps.core.enums import SsaIntervention
        from apps.core.fy import get_operational_fy
        from django.utils import timezone
        interventions = [i.value for i in SsaIntervention]
        fy = get_operational_fy()
        prev_fy = str(int(fy) - 1)
        for s in School.objects.all():
            for fyyy, score_base in [(prev_fy, 3.0), (fy, 4.0)]:
                if fyyy == fy and s.school_type == "client" and rnd.random() > 0.3:
                    continue
                avg = round(score_base + rnd.random() * 4, 1)
                rec = SsaRecord.objects.create(
                    school=s, fy=fyyy, quarter="Q1", date_of_ssa=timezone.now(),
                    average_score=avg, uploaded_by="seed", collector_type="staff",
                    verification_status="confirmed", verification_source="staff_self_verified",
                    source="local_test_upload",
                )
                for interv in interventions:
                    SsaScore.objects.create(ssa_record=rec, intervention=interv,
                                            score=round(max(0, min(10, avg + rnd.uniform(-1.5, 1.5))), 1))
        self.stdout.write(f"  sample SSA records: {SsaRecord.objects.count()} (local only)")

        partner_user = User.objects.filter(email="partner@edify.org").first()
        for i, name in enumerate(["Literacy Uganda", "Build Africa", "World Reader", "Pangea Educational", "Room to Read"]):
            Partner.objects.get_or_create(
                name=name,
                defaults={"coverage_districts": [d.name for d in districts[:3]],
                          "is_certified": i % 2 == 0, "active_status": True,
                          "contract_status": "active", "user": partner_user if i == 0 else None,
                          "source": "local_test_upload"},
            )
        self.stdout.write(f"  sample partners: {Partner.objects.count()} (local only)")

        rate_card = {
            "staff_visit_transport_primary": 15000, "lunch": 10000, "breakfast": 8000,
            "dinner": 12000, "accommodation": 40000, "staff_visit_transport_secondary": 25000,
            "training_session_fee": 50000, "venue": 30000, "meals_per_participant": 5000,
            "mobilisation_per_participant": 2000, "cluster_meeting_cost": 10000,
            "partner_visit_lump_sum": 35000, "partner_training_lump_sum": 120000,
        }
        for key, cost in rate_card.items():
            CostSetting.objects.update_or_create(key=key, defaults={"label": key.replace("_", " ").title(), "unit_cost": cost})
        self.stdout.write(f"  sample cost settings: {CostSetting.objects.count()} (local only)")

        for code, name in [("SP-EDTECH", "EdTech Pilot"), ("SP-CCSEL", "CCSEL"), ("SP-DIP", "DIP"), ("SP-ECC", "ECC"), ("SP-UCU", "UCU")]:
            Project.objects.get_or_create(code=code, defaults={"name": name, "category": "pilot"})
        self.stdout.write(f"  sample projects: {Project.objects.count()} (local only)")
