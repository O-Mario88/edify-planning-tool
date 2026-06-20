import { describe, it, expect } from "vitest";
import { normalizeEmail, hasPlusTag } from "@/lib/auth/social/email";
import { decideSocialLogin } from "@/lib/auth/social/decide";
import { socialMfaRequired, isPrivilegedRole } from "@/lib/auth/social/mfa-policy";
import type { ProviderClaims, RegisteredUser, ExistingLink } from "@/lib/auth/social/types";

// ── email normalization ──────────────────────────────────────────────
describe("normalizeEmail", () => {
  it("lowercases and trims", () => {
    expect(normalizeEmail("  Jane@Edify.ORG ")).toBe("jane@edify.org");
  });
  it("rejects missing / malformed input", () => {
    for (const bad of [null, undefined, "", "  ", "noatsign", "a@", "@b", "a@b@c", "a b@c.org"]) {
      expect(normalizeEmail(bad as string)).toBeNull();
    }
  });
  it("KEEPS the +tag (no plus-address normalization → no bypass)", () => {
    expect(normalizeEmail("jane+test@edify.org")).toBe("jane+test@edify.org");
    expect(hasPlusTag("jane+test@edify.org")).toBe(true);
    expect(hasPlusTag("jane@edify.org")).toBe(false);
  });
});

// ── MFA policy ───────────────────────────────────────────────────────
describe("socialMfaRequired", () => {
  const mk = (role: RegisteredUser["role"], mfaEnrolled = false): RegisteredUser =>
    ({ email: "x@edify.org", name: "X", role, status: "Active", mfaEnrolled });
  const opts = { enforce: true, includeProgramLead: true };

  it("requires MFA for privileged roles that haven't enrolled", () => {
    for (const r of ["Admin", "HumanResource", "ProgramAccountant", "CountryDirector", "RVP", "ImpactAssessment"] as const) {
      expect(socialMfaRequired(mk(r), opts)).toBe(true);
    }
  });
  it("does not require MFA for non-privileged roles", () => {
    for (const r of ["CCEO", "ProjectCoordinator", "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer"] as const) {
      expect(socialMfaRequired(mk(r), opts)).toBe(false);
    }
  });
  it("treats ProgramLead as privileged only when configured", () => {
    expect(isPrivilegedRole("CountryProgramLead", true)).toBe(true);
    expect(isPrivilegedRole("CountryProgramLead", false)).toBe(false);
  });
  it("is satisfied once the user has enrolled MFA", () => {
    expect(socialMfaRequired(mk("Admin", true), opts)).toBe(false);
  });
  it("is off entirely when enforcement is disabled", () => {
    expect(socialMfaRequired(mk("Admin"), { enforce: false, includeProgramLead: true })).toBe(false);
  });
});

// ── the gate ─────────────────────────────────────────────────────────
describe("decideSocialLogin", () => {
  const claims = (over: Partial<ProviderClaims> = {}): ProviderClaims => ({
    provider: "google",
    sub: "google-sub-1",
    email: "jane@edify.org",
    emailVerified: true,
    ...over,
  });
  const user = (over: Partial<RegisteredUser> = {}): RegisteredUser => ({
    email: "jane@edify.org",
    name: "Jane",
    role: "CCEO",
    status: "Active",
    mfaEnrolled: false,
    ...over,
  });
  const base = {
    claims: claims(),
    normalizedEmail: "jane@edify.org" as string | null,
    user: user(),
    existingLink: null as ExistingLink | null,
    mfaRequired: false,
  };

  it("ALLOWS a registered, verified, active, non-privileged user", () => {
    expect(decideSocialLogin(base).decision).toBe("allow");
  });

  it("DENIES an unregistered email (user not found)", () => {
    const d = decideSocialLogin({ ...base, user: null });
    expect(d).toMatchObject({ decision: "deny", reason: "UNREGISTERED_EMAIL", auditEvent: "SOCIAL_LOGIN_DENIED_UNREGISTERED_EMAIL" });
  });

  it("DENIES when the provider email is not verified", () => {
    const d = decideSocialLogin({ ...base, claims: claims({ emailVerified: false }) });
    expect(d).toMatchObject({ decision: "deny", reason: "UNVERIFIED_EMAIL", auditEvent: "SOCIAL_LOGIN_DENIED_UNVERIFIED_EMAIL" });
  });

  it("DENIES when the provider email is missing", () => {
    const d = decideSocialLogin({ ...base, normalizedEmail: null, claims: claims({ email: null }) });
    expect(d).toMatchObject({ decision: "deny", reason: "MISSING_EMAIL" });
  });

  it("DENIES a plus-address that isn't separately registered", () => {
    // Provider returns jane+test@edify.org; only jane@edify.org is registered →
    // the route's lookup returns null → unregistered.
    const d = decideSocialLogin({ ...base, normalizedEmail: "jane+test@edify.org", user: null });
    expect(d).toMatchObject({ decision: "deny", reason: "UNREGISTERED_EMAIL" });
  });

  it("DENIES when the resolved user email doesn't exactly match (defense in depth)", () => {
    const d = decideSocialLogin({ ...base, user: user({ email: "someone-else@edify.org" }) });
    expect(d).toMatchObject({ decision: "deny", reason: "UNREGISTERED_EMAIL" });
  });

  it("DENIES a suspended / deactivated / invited account (inactive)", () => {
    for (const status of ["Suspended", "Deactivated", "Invited", "Archived", "Deleted", "PasswordResetRequired", "weird-unknown"]) {
      const d = decideSocialLogin({ ...base, user: user({ status }) });
      expect(d).toMatchObject({ decision: "deny", reason: "INACTIVE_USER", auditEvent: "SOCIAL_LOGIN_DENIED_INACTIVE_USER" });
    }
  });

  it("DENIES a locked account distinctly", () => {
    const d = decideSocialLogin({ ...base, user: user({ status: "Locked" }) });
    expect(d).toMatchObject({ decision: "deny", reason: "LOCKED_USER", auditEvent: "SOCIAL_LOGIN_DENIED_LOCKED_USER" });
  });

  it("DENIES when the provider account is already linked to a different user", () => {
    const existingLink: ExistingLink = { provider: "google", providerAccountId: "google-sub-1", userEmail: "other@edify.org" };
    const d = decideSocialLogin({ ...base, existingLink });
    expect(d).toMatchObject({ decision: "deny", reason: "ACCOUNT_MISMATCH", auditEvent: "SOCIAL_ACCOUNT_MISMATCH" });
  });

  it("ALLOWS when the provider account is linked to the SAME user", () => {
    const existingLink: ExistingLink = { provider: "google", providerAccountId: "google-sub-1", userEmail: "jane@edify.org" };
    expect(decideSocialLogin({ ...base, existingLink }).decision).toBe("allow");
  });

  it("requires MFA (no session) for a privileged user", () => {
    const d = decideSocialLogin({ ...base, user: user({ role: "CountryDirector" }), mfaRequired: true });
    expect(d.decision).toBe("mfa_required");
  });

  it("denies BEFORE consulting MFA — an unregistered privileged-looking login never reaches MFA", () => {
    const d = decideSocialLogin({ ...base, user: null, mfaRequired: true });
    expect(d.decision).toBe("deny");
  });
});
