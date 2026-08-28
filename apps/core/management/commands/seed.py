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


SUPER_ADMIN_EMAIL = "edwin.omario@gmail.com"

# The super-admin runs the platform AND works the field as a CCEO, so the
# account carries both hats and switches between them at /auth/switch-role
# (which writes an audit row each time, so every action stays attributable to
# the hat it was taken under). `roles` is the set of hats the account may wear;
# `active_role` is the one it is wearing.
#
# Admin stays first because that is where the account should land on a fresh
# login -- the field hat is chosen deliberately, not by default.
SUPER_ADMIN_ROLES = [EdifyRole.ADMIN.value, EdifyRole.CCEO.value]

# Demo role accounts — shared DEMO_LOGIN_PASSWORD. LOCAL DEVELOPMENT ONLY.
DEMO_ACCOUNTS = [
    ("admin@edify.org", "Edify Admin", EdifyRole.ADMIN.value),
    ("cd@edify.org", "Sarah Okello", EdifyRole.COUNTRY_DIRECTOR.value),
    ("ia@edify.org", "Grace Alimo", EdifyRole.IMPACT_ASSESSMENT.value),
    ("rvp@edify.org", "Robert Vance", EdifyRole.REGIONAL_VICE_PRESIDENT.value),
    ("accountant@edify.org", "Moses Tindi", EdifyRole.PROGRAM_ACCOUNTANT.value),
    ("hr@edify.org", "Hellen Auma", EdifyRole.HUMAN_RESOURCES.value),
    ("coordinator@edify.org", "Allan Ssentongo", EdifyRole.PROJECT_COORDINATOR.value),
    (
        "partner@edify.org",
        "Literacy Uganda Officer",
        EdifyRole.PARTNER_FIELD_OFFICER.value,
    ),
    (
        "partner-admin@edify.org",
        "Demo Partner Administrator",
        EdifyRole.PARTNER_ADMIN.value,
    ),
    (
        "business-transformation@edify.org",
        "Demo Business Transformation Officer",
        EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value,
    ),
    (
        "mfi-admin@edify.org",
        "Demo MFI Partner Administrator",
        EdifyRole.MFI_PARTNER_ADMIN.value,
    ),
    (
        "mfi-officer@edify.org",
        "Demo MFI Loan Officer",
        EdifyRole.MFI_LOAN_OFFICER.value,
    ),
]

# Realistic Uganda geography (reference admin boundaries) — local-test seed only.
GEOGRAPHY = [
    {
        "name": "Northern",
        "districts": [
            {"name": "Lira", "subCounties": ["Lira TC", "Aromo", "Ogur"]},
            {"name": "Gulu", "subCounties": ["Gulu TC", "Bungatira", "Unyama"]},
            {"name": "Kitgum", "subCounties": ["Kitgum TC", "Namokora", "Mucwini"]},
        ],
    },
    {
        "name": "Eastern",
        "districts": [
            {"name": "Soroti", "subCounties": ["Soroti TC", "Arapai", "Katine"]},
            {"name": "Mbale", "subCounties": ["Mbale TC", "Bukonde", "Bungokho"]},
            {"name": "Jinja", "subCounties": ["Jinja TC", "Butagaya", "Budondo"]},
        ],
    },
    {
        "name": "Western",
        "districts": [
            {
                "name": "Mbarara",
                "subCounties": ["Mbarara TC", "Bwizibwera", "Kashanyaraazi"],
            },
            {
                "name": "Fort Portal",
                "subCounties": ["Fort Portal TC", "Kikojo", "Buheesi"],
            },
            {"name": "Kasese", "subCounties": ["Kasese TC", "Rukoki", "Bwera"]},
        ],
    },
    {
        "name": "Central",
        "districts": [
            {"name": "Kampala", "subCounties": ["Kampala Central", "Rubaga", "Nakawa"]},
            {"name": "Mukono", "subCounties": ["Mukono TC", "Ntunga", "Kyampisi"]},
            {"name": "Wakiso", "subCounties": ["Wakiso TC", "Nangabo", "Ssisa"]},
        ],
    },
]


class Command(BaseCommand):
    help = (
        "Seed reference data (RBAC permissions). Use --demo for local-only demo "
        "accounts + sample data (refuses to run in production)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--demo",
            action="store_true",
            help="Also seed local-only demo accounts + sample data. Refuses in production.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
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
        # The env-only check above cannot catch the most dangerous accident:
        # a LOCAL shell whose DATABASE_URL points at the LIVE database. The
        # database's own stamp can — refuse demo seeding into any database
        # stamped production, regardless of what this process believes it is.
        if demo:
            from apps.system_health.models import EnvironmentStamp

            stamp = EnvironmentStamp.objects.filter(
                id=EnvironmentStamp.SINGLETON_ID
            ).first()
            if stamp and stamp.environment == "production":
                raise CommandError(
                    "Refusing to seed demo data: this DATABASE is stamped "
                    "'production' (your DATABASE_URL points at the live "
                    "database). Fix .env before seeding."
                )

        self.stdout.write(self.style.MIGRATE_HEADING("Seeding Edify API..."))
        self._seed_permissions()
        # Uganda's administrative boundaries are REFERENCE data, not demo data.
        # They were seeded only under --demo, so production came up with no
        # Region, District or SubCounty rows at all -- which is not a cosmetic
        # gap: the school upload resolves a district by name, so every school
        # imported without one, and district-scoped analytics reported
        # "Coverage: 0 of 0 districts". The post_migrate hook could not save it
        # either, being a documented no-op until districts already exist.
        self._seed_geography()
        self._seed_super_admin()
        if demo:
            if settings.IS_PRODUCTION:  # defensive double-check
                raise CommandError("Demo seed blocked in production.")
            if options["reset"]:
                self._purge_operational()
            self._seed_demo_accounts()
            self._seed_sample_data()
            # Mark THIS database as demo-seeded — if this database ever
            # reaches production (dump restore), System Health raises a
            # critical "demo data on production" blocker.
            from django.utils import timezone as _tz

            from apps.system_health.models import EnvironmentStamp

            EnvironmentStamp.objects.update_or_create(
                id=EnvironmentStamp.SINGLETON_ID,
                defaults={"seeded_demo_at": _tz.now()},
            )
            self.stdout.write(
                self.style.WARNING(
                    "  ⚠ Demo data seeded — LOCAL DEVELOPMENT ONLY. Do NOT deploy this database."
                )
            )
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
                    role=role.value,
                    permission=key_to_perm[perm.value],
                )
        self.stdout.write(
            f"  permissions: {Permission.objects.count()} keys, "
            f"{RolePermission.objects.count()} role grants."
        )

    def _seed_super_admin(self):
        """Super-admin — env-only password; the ONE account that legitimately
        ships to production (prod.py refuses to boot without
        SUPER_ADMIN_PASSWORD set). Runs on every seed, demo or not — before
        this was hoisted out of _seed_demo_accounts(), a plain production
        `seed` created zero login-able users and day-1 ops had no way in."""
        from django.utils import timezone

        super_pw = settings.SUPER_ADMIN_PASSWORD
        if not super_pw:
            self.stdout.write("  super-admin: skipped (SUPER_ADMIN_PASSWORD not set).")
            return
        email = getattr(settings, "SUPER_ADMIN_EMAIL", SUPER_ADMIN_EMAIL)
        u, created = User.objects.update_or_create(
            email=email,
            defaults={
                "name": "Omario Edwin",
                "roles": SUPER_ADMIN_ROLES,
                "status": "active",
                "is_active": True,
                # Django-admin access: /admin/ is the day-1 bootstrap surface
                # for reference data the app UI can't create yet (geography
                # Regions), so the super-admin must be a Django superuser too.
                "is_staff": True,
                "is_superuser": True,
            },
        )
        # `active_role` is deliberately absent from `defaults`: it is the hat
        # currently being worn, and re-running seed must not pull the account
        # out of the field hat mid-shift. Set it on creation (the model's own
        # default is CCEO, and a new super-admin should land in the admin
        # workspace), and otherwise only to correct a hat this account may not
        # wear at all.
        if created or u.active_role not in SUPER_ADMIN_ROLES:
            u.active_role = EdifyRole.ADMIN.value
        u.set_password(super_pw)
        u.password_set_at = timezone.now()

        # Clear any lockout. This account is the platform's way back in, and a
        # way back in that can itself be locked out is not one.
        #
        # The lockout ladder escalates after repeated cycles to a state only an
        # Admin can clear, through /admin-panel/users/<id>. For the sole
        # Admin that is circular: the one account that can lift the lock is the
        # locked account. Re-seeding already resets this user's password, so it
        # was offering half a recovery — new credentials against a door that
        # was still bolted.
        #
        # Deliberately only the super-admin, and only when SUPER_ADMIN_PASSWORD
        # is set: whoever can set that environment variable and deploy can
        # already reset this password, so nothing is granted that was not
        # already held. Every other account keeps its lockout, which is the
        # brute-force protection doing its job.
        u.locked_until = None
        u.lockout_escalated = False
        u.lockout_cycle_count = 0
        u.failed_login_count = 0
        u.failed_login_streak_started_at = None
        # A forced change here would send the bootstrap login straight into the
        # password-change funnel using the password just set from the
        # environment, which helps nobody.
        u.must_change_password = False
        u.save()
        # Field work binds to a StaffProfile, not to the User row: targets,
        # visit plans and assignments all key off it. Without one the CCEO hat
        # signs in to a set of empty surfaces with no way to populate them.
        StaffProfile.objects.get_or_create(
            user=u, defaults={"onboarding_state": "active"}
        )
        self.stdout.write(
            f"  super-admin: {email} {'created' if created else 'updated'} "
            f"(Admin super-role, active: {u.active_role})."
        )

    # ── Demo accounts (local only) ──────────────────────────────────────────
    def _seed_demo_accounts(self):
        demo_pw = settings.DEMO_LOGIN_PASSWORD

        for email, name, role in DEMO_ACCOUNTS:
            u, _ = User.objects.update_or_create(
                email=email,
                defaults={
                    "name": name,
                    "roles": [role],
                    "active_role": role,
                    "status": "active",
                    "is_active": True,
                },
            )
            u.set_password(demo_pw)
            u.save()
            if role not in {
                EdifyRole.PARTNER_ADMIN.value,
                EdifyRole.PARTNER_FIELD_OFFICER.value,
                EdifyRole.MFI_PARTNER_ADMIN.value,
                EdifyRole.MFI_LOAN_OFFICER.value,
            }:
                StaffProfile.objects.update_or_create(
                    user=u, defaults={"onboarding_state": "active"}
                )

        # Program Leads (4) + CCEOs (20) with staff profiles + supervisor links.
        pls = []
        for i in range(1, 5):
            u, _ = User.objects.update_or_create(
                email=f"pl{i}@edify.org",
                defaults={
                    "name": f"Program Lead {i}",
                    "roles": [EdifyRole.COUNTRY_PROGRAM_LEAD.value],
                    "active_role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
                    "status": "active",
                    "is_active": True,
                },
            )
            u.set_password(demo_pw)
            u.save()
            sp, _ = StaffProfile.objects.update_or_create(
                user=u, defaults={"onboarding_state": "active"}
            )
            pls.append(sp)
        CCEO_NAMES = [
            "Paul N.",
            "Moses K.",
            "Joel T.",
            "Alfred O.",
            "Deo M.",
            "Grace A.",
            "Esther N.",
            "Brian S.",
            "Ruth N.",
            "Daniel O.",
            "Grace K.",
            "James O.",
            "Simon P.",
            "Florence A.",
            "Alex M.",
            "Robert O.",
            "Mary A.",
            "David K.",
            "John B.",
            "Sarah N.",
        ]
        cceos = []
        for i in range(20):
            email = "cceo@edify.org" if i == 0 else f"cceo{i}@edify.org"
            name = CCEO_NAMES[i] if i < len(CCEO_NAMES) else f"CCEO {i + 1}"
            u, _ = User.objects.update_or_create(
                email=email,
                defaults={
                    "name": name,
                    "roles": [EdifyRole.CCEO.value],
                    "active_role": EdifyRole.CCEO.value,
                    "status": "active",
                    "is_active": True,
                },
            )
            u.set_password(demo_pw)
            u.save()
            sp, _ = StaffProfile.objects.update_or_create(
                user=u, defaults={"onboarding_state": "active"}
            )
            cceos.append(sp)
        from apps.accounts.models import StaffSupervisorAssignment

        # Distribute CCEOs across all PLs (round-robin) so every Program Lead
        # has a supervised team — the PL Fund Approval / team views need this.
        for i, cceo in enumerate(cceos):
            StaffSupervisorAssignment.objects.get_or_create(
                supervisee=cceo, supervisor=pls[i % len(pls)] if pls else pls[0]
            )
        self.stdout.write(f"  demo users: {User.objects.count()} (local only).")

    # ── Geography (reference admin boundaries — local-test seed) ────────────
    def _seed_geography(self):
        import csv
        from pathlib import Path
        from django.conf import settings
        from apps.geography.models import Region, District, SubCounty, Parish

        csv_path = (
            Path(settings.BASE_DIR) / "uganda_complete_administrative_mapping.csv"
        )
        if not csv_path.exists():
            self.stdout.write(f"  Geography CSV not found at {csv_path}")
            return

        regions_cache = {}
        districts_cache = {}

        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                region_name = row["Region"].strip()
                district_name = row["District"].strip()
                sub_county_name = row["Sub_County"].strip()

                if region_name not in regions_cache:
                    region, _ = Region.objects.get_or_create(name=region_name)
                    regions_cache[region_name] = region
                region = regions_cache[region_name]

                key = (region_name, district_name)
                if key not in districts_cache:
                    district, _ = District.objects.get_or_create(
                        name=district_name, region=region
                    )
                    districts_cache[key] = district
                district = districts_cache[key]

                sub_county, _ = SubCounty.objects.get_or_create(
                    name=sub_county_name, district=district
                )
                Parish.objects.get_or_create(
                    name=f"{sub_county_name} Central", sub_county=sub_county
                )

        # The CSV is the legacy/demo hierarchy. Reconcile it additively with
        # the current coded UBOS registry so School Profile can select every
        # mapped boundary without rewriting any existing school assignment.
        from apps.geography.ubos_registry import ensure_geography_reference

        reference_stats = ensure_geography_reference()
        ubos_stats = reference_stats["subcounties"]
        alias_count = self._seed_district_aliases()
        self.stdout.write(
            f"  geography: {Region.objects.count()} regions, "
            f"{District.objects.count()} districts, {SubCounty.objects.count()} sub-counties, "
            f"{Parish.objects.count()} parishes "
            f"({ubos_stats['created']} current UBOS identities added, "
            f"{alias_count} upload aliases)."
        )

    # Names the operational school register uses that are not UBOS districts.
    # Two kinds, and neither is a typo the uploader should be guessing at:
    #
    #   • Wakiso and Mukono are split into directional working zones by the
    #     field teams. They are real to the people filling in the register and
    #     absent from every official list, so ~2,700 schools resolved to no
    #     district at all rather than to the district they are plainly in.
    #   • Three spellings that predate the current UBOS register.
    #
    # Recorded as GeographyAlias rows rather than fuzzy matching, so the
    # mapping is inspectable, revertible, and cannot quietly absorb a genuinely
    # new district that happens to look similar.
    DISTRICT_UPLOAD_ALIASES = {
        "Wakiso East": "Wakiso",
        "Wakiso West": "Wakiso",
        "Wakiso North": "Wakiso",
        "Wakiso South": "Wakiso",
        "Mukono North": "Mukono",
        "Mukono South": "Mukono",
        "Sembabule": "Ssembabule",
        "Bukwa": "Bukwo",
        "Bunyangabo": "Bunyangabu",
    }

    def _seed_district_aliases(self) -> int:
        from apps.geography.models import District, GeographyAlias

        by_name = {
            district.name.strip().casefold(): district
            for district in District.objects.all()
        }
        created = 0
        for alias, official in self.DISTRICT_UPLOAD_ALIASES.items():
            district = by_name.get(official.strip().casefold())
            if district is None:
                # The official district is genuinely absent from the register:
                # skip rather than invent one, and say so.
                self.stdout.write(
                    f"    alias skipped — no district named {official!r} for {alias!r}."
                )
                continue
            _, was_created = GeographyAlias.objects.get_or_create(
                admin_level="district",
                normalized_alias=alias.strip().casefold(),
                defaults={
                    "admin_id": district.id,
                    "alias": alias,
                    "source": "operational school register",
                    "confidence": "curated",
                },
            )
            created += int(was_created)
        return created

    def _purge_operational(self):
        """Purge operational tables (keeps users, geography, reference)."""
        from apps.activities.models import Activity
        from apps.schools.models import School
        from apps.ssa.models import SsaRecord
        from apps.clusters.models import Cluster
        from apps.partners.models import Partner
        from apps.geography.models import Region, District, SubCounty, Parish
        from apps.accounts.models import StaffSchoolAssignment

        Activity.objects.all().delete()
        SsaRecord.objects.all().delete()
        School.objects.all().delete()
        Cluster.objects.all().delete()
        Partner.objects.all().delete()
        StaffSchoolAssignment.objects.all().delete()

        # Clean up geography to replace with complete scraped dataset
        Parish.objects.all().delete()
        SubCounty.objects.all().delete()
        District.objects.all().delete()
        Region.objects.all().delete()
        self.stdout.write("  purged operational and geography data.")

    def _seed_sample_data(self):
        from apps.geography.models import District, SubCounty
        from apps.schools.models import School
        from apps.partners.models import Partner
        from apps.budget.models import CostSetting
        from apps.projects.models import Project

        districts = list(District.objects.all())
        subs = list(SubCounty.objects.all())
        rnd = random.Random(42)
        name_frags = [
            "Primary School",
            "UMEA Primary School",
            "Church of Uganda Primary",
            "Hill Primary",
        ]
        from apps.core.rbac import EdifyRole
        from apps.accounts.models import StaffProfile, StaffSchoolAssignment
        from apps.core.enums import AccountOwnerStatus

        cceos = list(
            StaffProfile.objects.filter(
                user__active_role=EdifyRole.CCEO.value
            ).order_by("user__email")
        )

        mukono_district = District.objects.filter(name__iexact="Mukono").first()
        if mukono_district:
            districts = [mukono_district]
            subs = list(SubCounty.objects.filter(district=mukono_district))
        else:
            districts = list(District.objects.all())
            subs = list(SubCounty.objects.all())

        sample_school_ids = [str(1000 + i) for i in range(700)]
        for i in range(700):
            d = rnd.choice(districts)
            sc = subs[i % len(subs)] if subs else rnd.choice(subs)
            s, _ = School.objects.update_or_create(
                school_id=str(1000 + i),
                defaults={
                    "name": f"{sc.name} {name_frags[i % len(name_frags)]}",
                    "region": d.region,
                    "district": d,
                    "sub_county": sc,
                    "enrollment": rnd.randint(80, 900),
                    "school_type": rnd.choices(
                        ["client", "core", "champion"], weights=[80, 15, 5]
                    )[0],
                    "current_fy_ssa_status": (
                        "done" if rnd.random() < 0.15 else "not_done"
                    ),
                    "source": "local_test_upload",
                },
            )
            if cceos:
                # Primary owner: Paul Chinyama (cceos[0]) gets all schools assigned
                cceo = cceos[0]
                s.account_owner_id = cceo.id
                s.account_owner_name_raw = cceo.user.name
                s.account_owner_status = AccountOwnerStatus.MATCHED.value
                s.save()
                StaffSchoolAssignment.objects.get_or_create(staff=cceo, school_id=s.id)
            from apps.ssa.services import _recompute_readiness

            _recompute_readiness(s)
        seeded_schools = School.objects.filter(school_id__in=sample_school_ids)
        self.stdout.write(
            f"  sample schools: {seeded_schools.count()} fixture rows (local only)"
        )

        # Sample SSA.
        from apps.ssa.models import SsaRecord, SsaScore
        from apps.core.enums import SsaIntervention
        from apps.core.fy import get_operational_fy
        from django.utils import timezone

        interventions = [i.value for i in SsaIntervention]
        fy = get_operational_fy()
        prev_fy = str(int(fy) - 1)
        for s in seeded_schools:
            for fyyy, score_base in [(prev_fy, 3.0), (fy, 4.0)]:
                if fyyy == fy and s.school_type == "client" and rnd.random() > 0.3:
                    continue
                avg = round(score_base + rnd.random() * 4, 1)
                record_defaults = {
                    "date_of_ssa": timezone.now(),
                    "average_score": avg,
                    "collector_type": "staff",
                    "verification_status": "confirmed",
                    "verification_source": "staff_self_verified",
                    # A confirmed record carries who confirmed it and when —
                    # the real confirmation paths (apps/ssa/services.py and
                    # upload_service.py) always stamp both. Seeding "confirmed"
                    # with neither manufactured a state the application cannot
                    # produce, so anything reading verification metadata off
                    # seeded data was reasoning about an impossible row
                    # (2026-08 audit, AUD-008).
                    "verified_at": timezone.now(),
                    "verified_by_user_id": "seed",
                }
                # Some seeded assessments are protected by planned activities,
                # so delete-and-recreate is both unsafe and impossible. Reuse
                # the fixture's canonical row and update it in place instead.
                rec = SsaRecord.objects.filter(
                    school=s,
                    fy=fyyy,
                    quarter="Q1",
                    uploaded_by="seed",
                    source="local_test_upload",
                ).first()
                if rec:
                    for field, value in record_defaults.items():
                        setattr(rec, field, value)
                    rec.save(update_fields=[*record_defaults, "updated_at"])
                else:
                    rec = SsaRecord.objects.create(
                        school=s,
                        fy=fyyy,
                        quarter="Q1",
                        uploaded_by="seed",
                        source="local_test_upload",
                        **record_defaults,
                    )
                for interv in interventions:
                    SsaScore.objects.update_or_create(
                        ssa_record=rec,
                        intervention=interv,
                        defaults={
                            "score": round(
                                max(0, min(10, avg + rnd.uniform(-1.5, 1.5))), 1
                            )
                        },
                    )
        fixture_ssa_count = SsaRecord.objects.filter(
            school__school_id__in=sample_school_ids,
            source="local_test_upload",
            uploaded_by="seed",
        ).count()
        self.stdout.write(
            f"  sample SSA records: {fixture_ssa_count} fixture rows (local only)"
        )

        partner_user = User.objects.filter(email="partner@edify.org").first()
        for i, name in enumerate(
            [
                "Literacy Uganda",
                "Build Africa",
                "World Reader",
                "Pangea Educational",
                "Room to Read",
            ]
        ):
            Partner.objects.get_or_create(
                name=name,
                defaults={
                    "coverage_districts": [d.name for d in districts[:3]],
                    "is_certified": i % 2 == 0,
                    "active_status": True,
                    "contract_status": "active",
                    "user": partner_user if i == 0 else None,
                    "source": "local_test_upload",
                },
            )

        partner_admin = User.objects.filter(email="partner-admin@edify.org").first()
        if partner_admin:
            Partner.objects.update_or_create(
                name="Demo Partner Administration",
                defaults={
                    "active_status": True,
                    "contract_status": "active",
                    "user": partner_admin,
                    "source": "local_test_upload",
                },
            )
        self.stdout.write(f"  sample partners: {Partner.objects.count()} (local only)")

        from apps.business_transformation.models import (
            MfiMembership,
            MfiMembershipRole,
            MfiOrganization,
        )

        demo_mfi, _ = MfiOrganization.objects.update_or_create(
            code="DEMO-MFI",
            defaults={
                "name": "Demo Lending Partner",
                "country_code": "UG",
                "active": True,
                "data_sharing_agreement_active": True,
            },
        )
        for email, membership_role in (
            ("mfi-admin@edify.org", MfiMembershipRole.ADMIN),
            ("mfi-officer@edify.org", MfiMembershipRole.LOAN_OFFICER),
        ):
            member = User.objects.filter(email=email).first()
            if member:
                MfiMembership.objects.update_or_create(
                    mfi=demo_mfi,
                    user=member,
                    defaults={"role": membership_role, "active": True},
                )
        self.stdout.write("  sample MFI tenancy: Demo Lending Partner (local only)")

        rate_card = {
            "primary_transport_per_day": 50000,
            "primary_lunch_per_day": 12000,
            "secondary_transport_per_day": 80000,
            "secondary_lunch_per_day": 12000,
            "secondary_breakfast_per_day": 8000,
            "secondary_overnight_dinner_per_day": 12000,
            "secondary_accommodation_per_night": 40000,
            "secondary_incidentals_per_day": 5000,
            "group_training_facilitation_fee": 50000,
            "group_training_venue_cost": 30000,
            "group_training_participant_meal_cost_per_head": 5000,
            "cluster_meeting_participant_meal_cost_per_head": 10000,
            "partner_visit_lump_sum": 40000,
            "partner_training_lump_sum": 16000,
            "core_school_visit": 50000,
            "core_school_training": 250000,
            "ssa_visit_rate": 50000,
            "project_partner_lump_sum": 40000,
        }
        friendly_labels = {
            "cluster_meeting_participant_meal_cost_per_head": "Participant snacks",
            "group_training_participant_meal_cost_per_head": "Participant meals",
            "group_training_facilitation_fee": "Facilitation fee",
            "group_training_venue_cost": "Venue fee",
        }
        # get_or_create, never update_or_create: the CD's Cost Catalogue is
        # the authoritative rate card, and a reseed must not silently reset a
        # rate the CD changed (no version bump, no CostSettingHistory row —
        # exactly the overwrite budget/reference.py promises never happens).
        # New keys are seeded through the same canonical writer so version
        # and history stay consistent.
        from apps.budget.reference import ensure_active_catalogue

        seed_catalogue = ensure_active_catalogue()
        for key, cost in rate_card.items():
            CostSetting.objects.get_or_create(
                key=key,
                defaults={
                    "label": friendly_labels.get(key, key.replace("_", " ").title()),
                    "unit_cost": cost,
                    "catalogue": seed_catalogue,
                },
            )
        self.stdout.write(
            f"  sample cost settings: {CostSetting.objects.count()} (local only)"
        )

        # Link the demo Project Coordinator (Allan Ssentongo) to the sample
        # projects — with a focus intervention and a school cohort each — so the
        # Project Coordinator role has a populated Special Projects experience
        # out of the box (dashboard / planning / my-plan / analytics all scope to
        # the projects a coordinator manages via Project.manager_staff_id).
        from apps.accounts.models import StaffProfile
        from apps.projects.models import ProjectSchoolAssignment
        from apps.schools.models import School

        coord = User.objects.filter(email="coordinator@edify.org").first()
        coord_sp = StaffProfile.objects.filter(user=coord).first() if coord else None
        project_defs = [
            ("SP-EDTECH", "EdTech Pilot", "learning_environment"),
            ("SP-CCSEL", "CCSEL", "christlike_behaviour"),
            ("SP-DIP", "DIP", "leadership"),
            ("SP-ECC", "ECC", "teaching_environment"),
            ("SP-UCU", "UCU", "government_requirement"),
        ]
        all_schools = list(seeded_schools.filter(deleted_at__isnull=True)[:25])
        for idx, (code, name, focus) in enumerate(project_defs):
            proj, _ = Project.objects.get_or_create(
                code=code, defaults={"name": name, "category": "pilot"}
            )
            changed = []
            if coord_sp and not proj.manager_staff_id:
                proj.manager_staff_id = coord_sp.id
                changed.append("manager_staff_id")
            if focus and not proj.intervention:
                proj.intervention = focus
                changed.append("intervention")
            if changed:
                proj.save(update_fields=[*changed, "updated_at"])
            # Give each project a distinct 5-school cohort.
            for s in all_schools[idx * 5 : idx * 5 + 5]:
                ProjectSchoolAssignment.objects.get_or_create(project=proj, school=s)
        self.stdout.write(
            f"  sample projects: {Project.objects.count()} "
            f"(coordinator={'linked' if coord_sp else 'MISSING'}, "
            f"assignments={ProjectSchoolAssignment.objects.count()})"
        )

        # Seed activities for April 2026 (for Consolidated Fund Allocation dashboard)
        from apps.activities.models import Activity
        from apps.budget.costing_service import apply_to_activity
        from apps.clusters.models import Cluster
        from apps.clusters.models import ClusterSubCounty
        from apps.core.enums import ClusterRecordStatus
        from datetime import datetime, timezone

        schools = list(seeded_schools)
        clusters = []
        for i in range(15):
            cl_name = f"Cluster {chr(65+i)}"
            dist = rnd.choice(districts)
            cluster, _ = Cluster.objects.get_or_create(
                name=cl_name,
                defaults={
                    "district": dist,
                    "region": dist.region,
                    # "clustered" is a ClusterStatus — a *school's* clustering
                    # state — and was never a valid ClusterRecordStatus. Django
                    # does not enforce choices at the database level, so all 15
                    # seeded clusters saved happily and then matched no filter:
                    # every cluster surface selects active/needs_review, so the
                    # seed produced a country with 16 clusters of which one was
                    # visible.
                    "status": ClusterRecordStatus.ACTIVE,
                },
            )
            # A cluster with no declared sub-county can never claim a school.
            # `active_cluster_for_geography` matches on district AND
            # sub-county, so a seeded cluster carrying only a district made
            # the Add-to-Cluster drawer, the School Profile and School.save()
            # all resolve to nothing — silently, because "no cluster covers
            # this sub-county" and "no cluster declares any sub-county" look
            # identical from the outside.
            if not cluster.sub_county_id:
                covered = SubCounty.objects.filter(district=cluster.district).first()
                if covered:
                    cluster.sub_county = covered
                    cluster.save(update_fields=["sub_county", "updated_at"])
                    ClusterSubCounty.objects.get_or_create(
                        cluster=cluster, sub_county=covered
                    )
            clusters.append(cluster)

        from apps.partners.models import Partner, PartnerAssignment

        # Assignments reference activities, so they go first. Scope cleanup to
        # the deterministic April-2026 demo fixture; the previous all().delete
        # calls destroyed unrelated work whenever a developer refreshed seed
        # data without --reset.
        from datetime import date

        demo_actor_ids = [cceo.user.user_id for cceo in cceos]
        seeded_activities = Activity.objects.filter(
            responsible_staff_id__in=demo_actor_ids,
            scheduled_date__date__gte=date(2026, 4, 1),
            scheduled_date__date__lte=date(2026, 4, 30),
        )
        PartnerAssignment.objects.filter(
            scheduled_activity__in=seeded_activities
        ).delete()
        seeded_activities.delete()

        seed_partners = list(
            Partner.objects.filter(active_status=True).order_by("name")
        )

        # Seed 13 activities per CCEO
        for cceo_idx, cceo in enumerate(cceos):
            for act_idx in range(13):
                date_day = rnd.randint(1, 28)
                scheduled_date = datetime(2026, 4, date_day, 10, 0, tzinfo=timezone.utc)

                if act_idx < 4:
                    # Staff visit
                    act_type = "school_visit"
                    del_type = "staff"
                    school = schools[(cceo_idx * 10 + act_idx) % len(schools)]
                    cluster = None
                elif act_idx < 7:
                    # Partner visit
                    act_type = "school_visit"
                    del_type = "partner"
                    school = schools[(cceo_idx * 10 + act_idx) % len(schools)]
                    cluster = None
                elif act_idx < 9:
                    # SSA Activity
                    act_type = "ssa_activity"
                    del_type = "staff"
                    school = schools[(cceo_idx * 10 + act_idx) % len(schools)]
                    cluster = None
                elif act_idx < 11:
                    # Cluster training
                    act_type = (
                        "cluster_meeting"  # maps to 10k cluster meeting cost setting
                    )
                    del_type = "staff"
                    school = None
                    cluster = clusters[cceo_idx % len(clusters)]
                else:
                    # Partner In-school training
                    act_type = "partner_activity"
                    del_type = "partner"
                    school = schools[(cceo_idx * 10 + act_idx) % len(schools)]
                    cluster = None

                # A partner-delivered activity names the partner that
                # delivered it. Without this the seed produced 230 activities
                # whose delivery channel was "partner" and whose partner was
                # nobody — a state no write path in the application can
                # produce, priced at partner rates, and invisible on Partner
                # Oversight because nothing there has a partner to group it
                # under. The demo then showed partner work that no partner
                # could be held to.
                partner = (
                    seed_partners[(cceo_idx + act_idx) % len(seed_partners)]
                    if del_type == "partner" and seed_partners
                    else None
                )

                act = Activity.objects.create(
                    activity_type=act_type,
                    delivery_type=del_type
                    if partner or del_type != "partner"
                    else "staff",
                    school=school,
                    cluster=cluster,
                    scheduled_date=scheduled_date,
                    responsible_staff_id=cceo.user.user_id,
                    # `assigned_partner_id` is a plain CharField, not an FK —
                    # there is no `assigned_partner` to assign.
                    assigned_partner_id=partner.id if partner else None,
                    status="completed",
                )

                # The handover the work actually passed through. Seeded data
                # has to be a state the application could have reached, or
                # every board that reads it reports a defect that only the
                # seeder can cause.
                if partner is not None:
                    from apps.activity_catalogue.services import (
                        resolve_assignment_item,
                    )

                    seeded_item = resolve_assignment_item(
                        purpose_of_visit="ssa_support",
                        expected_activity_type=act_type,
                    )
                    PartnerAssignment.objects.create(
                        school=school,
                        cluster=cluster,
                        partner=partner,
                        assigning_staff_id=cceo.user.user_id,
                        monitoring_staff_id=cceo.user.user_id,
                        assignment_mode="specific_activity",
                        catalogue_item=seeded_item,
                        catalogue_snapshot=seeded_item.snapshot()
                        if seeded_item
                        else {},
                        purpose=f"Seeded {act_type.replace('_', ' ')}",
                        purpose_of_visit="ssa_support",
                        expected_activity_type=act_type,
                        scheduled_date=scheduled_date.date(),
                        status="completed",
                        scheduled_activity=act,
                    )

                apply_to_activity(
                    act,
                    {
                        "activityType": act_type,
                        "deliveryType": del_type,
                        "districtType": "primary",
                        "teachersAttended": 1,
                        "leadersAttended": 0,
                        "otherParticipants": 0,
                        "nights": 0,
                        "fy": "2026",
                    },
                    responsible_user_id=cceo.user.user_id,
                )

        self.stdout.write(
            f"  sample activities: {Activity.objects.count()} (local only)"
        )
