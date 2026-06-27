"""
Accounts & RBAC models — ports of the legacy User / UserInvitation /
RefreshToken / Permission / RolePermission / StaffProfile* tables.

Key parity notes:
- `User` is Django's auth user model (AUTH_USER_MODEL = accounts.User). It keeps
  the legacy string CUID PK, the multi-role array (Postgres ArrayField), the
  brute-force lockout fields, and the lifecycle status.
- `passwordHash` is nullable (invited users exist before they set a password).
  We use Django's `password` field convention backed by bcrypt for hash parity
  with NestJS bcryptjs (cost 12) — Django's bcrypt hasher verifies those hashes.
- `RefreshToken` stores a SHA-256 hash of the rotating refresh token.
- `StaffProfile` is 1:1 with User and carries the field-staff portfolio links.
"""
from __future__ import annotations

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel
from apps.core.rbac import EdifyRole


class UserStatus(models.TextChoices):
    PENDING_INVITED = "pending_invited", "Pending (invited)"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    DISABLED = "disabled", "Disabled"


class UserManager(BaseUserManager):
    """Manager that supports creating users + superusers by email."""

    use_in_migrations = True

    def _create_user(self, email, name, *, roles=None, active_role=None, password=None, **extra):
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email).lower()
        roles = roles or [EdifyRole.CCEO.value]
        active_role = active_role or roles[0]
        user = self.model(email=email, name=name, roles=roles, active_role=active_role, **extra)
        if password:
            user.set_password(password)
        else:
            # Invited users have no password until they accept the invite.
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, name, *, roles=None, active_role=None, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, name, roles=roles, active_role=active_role, password=password, **extra)

    def create_superuser(self, email, name, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        roles = extra.pop("roles", None) or [EdifyRole.ADMIN.value]
        active_role = extra.pop("active_role", None) or EdifyRole.ADMIN.value
        extra.setdefault("status", UserStatus.ACTIVE)
        extra.setdefault("is_active", True)
        return self._create_user(
            email, name, roles=roles, active_role=active_role, password=password, **extra
        )


class User(AbstractBaseUser, PermissionsMixin, SoftDeleteModel):
    """The authenticated principal. Mirrors the legacy `User` Prisma model.

    `request.user` resolves to this; the JWT strategy attaches an `AuthUser`-style
    payload (userId, email, name, roles, activeRole, staffProfileId) to the request.
    """

    id = CuidField()
    email = models.EmailField(unique=True)
    # Nullable: admin-invited users exist before they set a password.
    # Django stores the bcrypt hash here (parity with NestJS bcryptjs cost 12).
    password = models.CharField(max_length=255, null=True, blank=True)
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=64, null=True, blank=True)
    roles = ArrayField(
        base_field=models.CharField(max_length=64, choices=[(r.value, r.value) for r in EdifyRole]),
        default=list,
    )
    active_role = models.CharField(
        max_length=64, choices=[(r.value, r.value) for r in EdifyRole],
        default=EdifyRole.CCEO.value,
    )
    is_active = models.BooleanField(default=True)
    # Lifecycle: invited → active → suspended/disabled. Only `active` may sign in.
    status = models.CharField(max_length=32, choices=UserStatus.choices, default=UserStatus.ACTIVE)
    password_set_at = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    # Brute-force protection (auth.service login gate).
    failed_login_count = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    # MFA seam (Phase 8 design): secret stored encrypted when enrolment ships.
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=512, null=True, blank=True)
    # Password-reset seam: store only a HASH of the reset token + its expiry.
    password_reset_token_hash = models.CharField(max_length=255, null=True, blank=True)
    password_reset_expires = models.DateTimeField(null=True, blank=True)

    # Django admin bookkeeping.
    is_staff = models.BooleanField(default=False)

    objects = UserManager()
    # Soft-delete-aware default manager; all_objects includes tombstones.
    # (AbstractBaseUser provides its own; we keep ours for deleted_at scoping.)
    all_objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        db_table = "user"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    @property
    def active_role_enum(self) -> EdifyRole:
        try:
            return EdifyRole(self.active_role)
        except ValueError:
            return EdifyRole.CCEO

    @property
    def role_enums(self) -> list[EdifyRole]:
        out = []
        for r in self.roles or []:
            try:
                out.append(EdifyRole(r))
            except ValueError:
                continue
        return out

    def get_short_name(self) -> str:
        return self.name


class UserInvitation(TimeStampedModel):
    """One-time invitation token issued when an admin creates a user. The raw
    token is never stored — only its SHA-256 hash. Single-use + revocable +
    expiring (7d default)."""

    id = CuidField()
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="invitations")
    token_hash = models.CharField(max_length=255, unique=True)
    invited_by = models.ForeignKey(User, on_delete=models.RESTRICT, related_name="invited_by")
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "user_invitation"
        indexes = [models.Index(fields=["user"])]


class RefreshToken(TimeStampedModel):
    """Rotating, revocable refresh token (7d). The access JWT is short-lived
    (15m); this lets a user stay signed in, and logout revokes it so the
    session can't be refreshed."""

    id = CuidField()
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="refresh_tokens")
    token_hash = models.CharField(max_length=255, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "refresh_token"
        indexes = [models.Index(fields=["user"])]


class Permission(TimeStampedModel):
    """A canonical permission key (e.g. 'school.upload', 'budget.approve')."""

    id = CuidField()
    key = models.CharField(max_length=128, unique=True)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "permission"


class RolePermission(TimeStampedModel):
    """Join role → permission. The matrix in apps.core.rbac.ROLE_PERMISSIONS is
    the seed source of truth for this table."""

    id = CuidField()
    role = models.CharField(
        max_length=64, choices=[(r.value, r.value) for r in EdifyRole]
    )
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, related_name="roles")

    class Meta:
        db_table = "role_permission"
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="uniq_role_permission"),
        ]


# ── Staff / Supervisors ──────────────────────────────────────────────────────
class StaffOnboardingState(models.TextChoices):
    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"


class StaffProfile(SoftDeleteModel):
    """1:1 with User. Carries the field-staff portfolio links (geography,
    schools, supervisor/supervisee, targets, capacity)."""

    id = CuidField()
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_profile")
    staff_number = models.CharField(max_length=64, null=True, blank=True, unique=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    # Plain ref (FK to geography.District); left unenforced at this layer to
    # avoid a hard dependency cycle — geography app may not exist yet.
    primary_district_id = models.CharField(max_length=30, null=True, blank=True)
    onboarding_state = models.CharField(
        max_length=32, choices=StaffOnboardingState.choices, default=StaffOnboardingState.PENDING
    )

    class Meta:
        db_table = "staff_profile"


class StaffSupervisorAssignment(TimeStampedModel):
    """Join supervisee ↔ supervisor (the PL 'team lens' depends on this)."""

    id = CuidField()
    supervisee = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="supervisor_links")
    supervisor = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="supervisee_links")

    class Meta:
        db_table = "staff_supervisor_assignment"
        constraints = [
            models.UniqueConstraint(fields=["supervisee", "supervisor"], name="uniq_supervisee_supervisor"),
        ]
        indexes = [models.Index(fields=["supervisor"])]


class StaffGeographyAssignment(TimeStampedModel):
    """Join staff ↔ region/district (RVP region scope, field-staff district scope)."""

    id = CuidField()
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="geography_links")
    region_id = models.CharField(max_length=30, null=True, blank=True)
    district_id = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "staff_geography_assignment"
        indexes = [models.Index(fields=["staff"])]


class StaffSchoolAssignment(TimeStampedModel):
    """Join staff ↔ school (portfolio). Own vs team lens derives from this."""

    id = CuidField()
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="school_links")
    school_id = models.CharField(max_length=30)

    class Meta:
        db_table = "staff_school_assignment"
        constraints = [
            models.UniqueConstraint(fields=["staff", "school_id"], name="uniq_staff_school"),
        ]


class StaffSupportCapacity(TimeStampedModel):
    """CD/IA-set cap on direct schools a staff supports per FY. Once reached,
    self-assignment to a NEW school is blocked; partner assignment is the route."""

    id = CuidField()
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="support_capacities")
    fy = models.CharField(max_length=16)
    max_direct_schools_supported = models.IntegerField()
    set_by_user_id = models.CharField(max_length=30)
    set_by_role = models.CharField(max_length=64, choices=[(r.value, r.value) for r in EdifyRole])
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "staff_support_capacity"
        constraints = [
            models.UniqueConstraint(fields=["staff", "fy"], name="uniq_staff_capacity_fy"),
        ]
        indexes = [models.Index(fields=["fy"])]


class AssignmentAudit(TimeStampedModel):
    """Every assignment attempt — allowed or blocked — for accountability."""

    id = CuidField()
    action = models.CharField(max_length=64)  # assign.self | assign.partner | assign.staff
    school_id = models.CharField(max_length=30, null=True, blank=True)
    activity_id = models.CharField(max_length=30, null=True, blank=True)
    assigner_id = models.CharField(max_length=30)
    assigner_role = models.CharField(max_length=64, choices=[(r.value, r.value) for r in EdifyRole])
    assigned_to_type = models.CharField(max_length=16)  # staff | partner
    assigned_staff_id = models.CharField(max_length=30, null=True, blank=True)
    assigned_partner_id = models.CharField(max_length=30, null=True, blank=True)
    allowed = models.BooleanField()
    blocked_reason = models.CharField(max_length=512, null=True, blank=True)
    override_used = models.BooleanField(default=False)
    override_reason = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "assignment_audit"
        indexes = [
            models.Index(fields=["assigner_id"]),
            models.Index(fields=["school_id"]),
            models.Index(fields=["created_at"]),
        ]


class StaffTargetProfile(TimeStampedModel):
    """Annual targets for a staff member — configurable by CD/HR. Each metric
    has a target value; 0 means 'not set' for that metric."""

    id = CuidField()
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="target_profiles")
    fy = models.CharField(max_length=16)
    visits_target = models.IntegerField(default=0)
    trainings_target = models.IntegerField(default=0)
    # Extended target types for the performance engine.
    ssa_target = models.IntegerField(default=0)
    cluster_meetings_target = models.IntegerField(default=0)
    group_trainings_target = models.IntegerField(default=0)
    evidence_target = models.IntegerField(default=0)
    activity_codes_target = models.IntegerField(default=0)
    ia_verified_target = models.IntegerField(default=0)
    accountability_target = models.IntegerField(default=0)

    class Meta:
        db_table = "staff_target_profile"
        constraints = [
            models.UniqueConstraint(fields=["staff", "fy"], name="uniq_staff_target_fy"),
        ]


class Leave(TimeStampedModel):
    """HR leave requests. type/status are plain strings (legacy convention)."""

    id = CuidField()
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="leaves")
    type = models.CharField(max_length=64)  # annual|sick|compassionate|unpaid
    start_date = models.CharField(max_length=32)
    end_date = models.CharField(max_length=32)
    days = models.IntegerField()
    status = models.CharField(max_length=32, default="pending")
    reason = models.TextField(null=True, blank=True)
    reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "leave"
        indexes = [
            models.Index(fields=["staff"]),
            models.Index(fields=["status"]),
        ]


class Report(TimeStampedModel):
    """A saved/generated report."""

    id = CuidField()
    title = models.CharField(max_length=255)
    type = models.CharField(max_length=64)
    fy = models.CharField(max_length=16)
    scope = models.CharField(max_length=64, default="country")
    created_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    summary_json = models.JSONField(default=dict)

    class Meta:
        db_table = "report"
        indexes = [
            models.Index(fields=["type"]),
            models.Index(fields=["fy"]),
        ]


class StaffSetupCandidateStatus(models.TextChoices):
    """Lifecycle of an uploaded staff name that didn't match an existing user."""
    PENDING_PROFILE = "pending_profile", "Pending Profile"
    INVITED = "invited", "Invited"
    ACTIVE = "active", "Active"
    MERGED = "merged", "Merged"
    IGNORED = "ignored", "Ignored"


class StaffSetupCandidate(TimeStampedModel):
    """An uploaded staff name that did not match an existing user — Admin's queue
    to add an email and create/merge the profile.

    One candidate per NORMALIZED name (no duplicates across uploads). When the
    Admin creates or matches a user, ALL schools whose account_owner_name_raw
    normalizes to this name are linked to that user via StaffSchoolAssignment and
    their account_owner_status flips to matched."""

    id = CuidField()
    full_name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255, unique=True)
    source_upload_batch = models.CharField(max_length=30, null=True, blank=True)
    school_count = models.IntegerField(default=0)
    sample_school_ids = ArrayField(base_field=models.CharField(max_length=30), default=list, blank=True)
    suggested_role = models.CharField(max_length=32, null=True, blank=True)  # CCEO | PL if inferable
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(
        max_length=32, choices=StaffSetupCandidateStatus.choices,
        default=StaffSetupCandidateStatus.PENDING_PROFILE,
    )
    matched_user_id = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "staff_setup_candidate"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["normalized_name"]),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.status})"


__all__ = [
    "UserStatus",
    "User",
    "UserManager",
    "UserInvitation",
    "RefreshToken",
    "Permission",
    "RolePermission",
    "StaffOnboardingState",
    "StaffProfile",
    "StaffSupervisorAssignment",
    "StaffGeographyAssignment",
    "StaffSchoolAssignment",
    "StaffSupportCapacity",
    "AssignmentAudit",
    "StaffTargetProfile",
    "Leave",
    "Report",
    "StaffSetupCandidateStatus",
    "StaffSetupCandidate",
]
