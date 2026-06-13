import Link from "next/link";
import {
  User,
  Bell,
  ChevronRight,
  ShieldCheck,
  Languages,
  Palette,
  Laptop,
  KeyRound,
  LogOut,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { SignOutButton } from "@/components/auth/SignOutButton";
import { SectionCard } from "@/components/ui/primitives";
import { Button } from "@/components/ui/Button";
import { getCurrentUser } from "@/lib/auth";

// Toggle pattern. Read-only — the production identity provider will wire
// onChange when integrated. For now we render the visual state so the
// settings page reads as a complete account surface rather than a stub.
function ReadOnlyToggle({ label, caption, enabled }: { label: string; caption?: string; enabled: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2">
      <div className="min-w-0">
        <div className="text-body font-semibold">{label}</div>
        {caption && <div className="text-[11px] muted leading-snug">{caption}</div>}
      </div>
      <span
        aria-label={`${label} (read-only, currently ${enabled ? "on" : "off"})`}
        title={`${label} (${enabled ? "on" : "off"})`}
        className={`relative inline-block w-9 h-5 rounded-full shrink-0 transition-colors ${
          enabled ? "bg-[var(--color-edify-primary)]" : "bg-[#cfd6dc]"
        }`}
      >
        <span
          className={`absolute top-0.5 ${enabled ? "left-[18px]" : "left-0.5"} w-4 h-4 rounded-full bg-white shadow-sm transition-all`}
        />
      </span>
    </div>
  );
}

// Thin wrapper around the canonical Button primitive. Kept so the call
// sites below stay terse; under the hood it just picks the right variant.
function SmallBtn({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "danger" }) {
  return (
    <Button size="sm" variant={tone === "danger" ? "danger" : "secondary"}>
      {children}
    </Button>
  );
}

export default async function SettingsPage() {
  const user = await getCurrentUser();

  return (
    <StubPage
      title="Settings"
      subtitle="Manage your account, security, and workspace preferences."
    >
      {/* Identity card */}
      <section className="card p-3.5 flex items-center gap-3">
        <div className="h-12 w-12 rounded-full bg-[var(--color-edify-primary)] text-white text-body-lg font-extrabold grid place-items-center shrink-0">
          {user.initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-body-lg font-extrabold tracking-tight truncate">{user.name}</div>
          <div className="text-[11.5px] muted truncate">
            {user.email} · {user.scope} · {user.role.replace(/([A-Z])/g, " $1").trim()}
          </div>
        </div>
        <SignOutButton variant="light" fullWidth={false} className="shrink-0" />
      </section>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Profile (link card) */}
        <SectionCard
          icon={<User size={13} />}
          title="Profile"
          subtitle="Name, email, role visibility"
        >
          <Link
            href="/profile"
            className="flex items-center gap-3 px-3 py-2.5 -mx-1 rounded-lg hover:bg-[var(--color-edify-soft)]/40"
          >
            <div className="flex-1 min-w-0">
              <div className="text-body font-semibold">View Profile</div>
              <div className="text-[11px] muted">Identity, scope, and account details</div>
            </div>
            <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
          </Link>
        </SectionCard>

        {/* Security */}
        <SectionCard
          icon={<ShieldCheck size={13} />}
          title="Security"
          subtitle="Two-factor authentication and active sessions"
        >
          <div className="divide-y divide-[var(--color-edify-divider)]">
            <div className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <div className="text-body font-semibold">Two-Factor Authentication</div>
                <div className="text-[11px] muted">Not enabled</div>
              </div>
              <SmallBtn>Enable</SmallBtn>
            </div>
            <div className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <div className="text-body font-semibold">Active Sessions</div>
                <div className="text-[11px] muted">1 device</div>
              </div>
              <SmallBtn>Manage</SmallBtn>
            </div>
          </div>
        </SectionCard>

        {/* Notifications */}
        <SectionCard
          icon={<Bell size={13} />}
          title="Notifications"
          subtitle="Decide what pings you and how"
          actions={
            <Link
              href="/notifications"
              className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-1"
            >
              Open Inbox
              <ChevronRight size={12} />
            </Link>
          }
        >
          <div className="divide-y divide-[var(--color-edify-divider)]">
            <ReadOnlyToggle
              label="Email Digest"
              caption="Daily summary of approvals, escalations, and field signals"
              enabled
            />
            <ReadOnlyToggle
              label="Field-Alert Push"
              caption="Real-time push for critical field events in your scope"
              enabled
            />
            <ReadOnlyToggle
              label="Weekly Report Reminder"
              caption="Friday reminder to file your weekly report"
              enabled={false}
            />
          </div>
        </SectionCard>

        {/* Language & Region */}
        <SectionCard
          icon={<Languages size={13} />}
          title="Language & Region"
          subtitle="Localisation and time zone"
        >
          <div className="divide-y divide-[var(--color-edify-divider)]">
            <div className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <div className="text-body font-semibold">Language</div>
                <div className="text-[11px] muted">English (UK)</div>
              </div>
              <SmallBtn>Change</SmallBtn>
            </div>
            <div className="flex items-center justify-between gap-3 py-2.5">
              <div className="min-w-0">
                <div className="text-body font-semibold">Time Zone</div>
                <div className="text-[11px] muted">Africa/Kampala (EAT, UTC+3)</div>
              </div>
              <SmallBtn>Change</SmallBtn>
            </div>
          </div>
        </SectionCard>

        {/* Appearance */}
        <SectionCard
          icon={<Palette size={13} />}
          title="Appearance"
          subtitle="Theme preferences"
        >
          <div className="flex items-center gap-3">
            {([
              { key: "Light", bg: "#ffffff", border: "var(--color-edify-border)", selected: true },
              { key: "Dim", bg: "#1f2937", border: "#1f2937", selected: false },
              { key: "Dark", bg: "#0b1220", border: "#0b1220", selected: false },
            ] as const).map((t) => (
              <div key={t.key} className="flex flex-col items-center gap-1">
                <span
                  className={`block w-12 h-12 rounded-xl border-2 ${
                    t.selected ? "ring-2 ring-[var(--color-edify-primary)] ring-offset-2" : ""
                  }`}
                  style={{ background: t.bg, borderColor: t.border }}
                  aria-label={t.key}
                />
                <span
                  className={`text-[11px] ${
                    t.selected ? "font-extrabold text-[var(--color-edify-primary)]" : "muted font-semibold"
                  }`}
                >
                  {t.key}
                </span>
              </div>
            ))}
          </div>
        </SectionCard>

        {/* Devices & Sessions */}
        <SectionCard
          icon={<Laptop size={13} />}
          title="Devices & Sessions"
          subtitle="Where you're signed in"
        >
          <div className="flex items-center justify-between gap-3 py-1">
            <div className="flex items-center gap-3 min-w-0">
              <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <Laptop size={15} />
              </span>
              <div className="min-w-0">
                <div className="text-body font-semibold truncate">MacBook Pro · Chrome · Kampala</div>
                <div className="text-[11px] muted">last active just now</div>
              </div>
            </div>
            <SignOutButton variant="light" fullWidth={false} className="shrink-0" />
          </div>
        </SectionCard>

        {/* Account access */}
        <SectionCard
          icon={<KeyRound size={13} />}
          title="Account Access"
          subtitle="Password and global sign-out"
          className="md:col-span-2"
        >
          <div className="divide-y divide-[var(--color-edify-divider)]">
            <Link
              href="/reset-password"
              className="flex items-center gap-3 py-2.5"
            >
              <span className="h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <KeyRound size={14} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-semibold">Reset Password</div>
                <div className="text-[11px] muted">Set a new password using a one-time link</div>
              </div>
              <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
            </Link>
            <div className="flex items-center justify-between gap-3 py-2.5">
              <div className="flex items-center gap-3 min-w-0">
                <span className="h-8 w-8 rounded-md bg-rose-50 text-rose-700 grid place-items-center shrink-0">
                  <LogOut size={14} />
                </span>
                <div className="min-w-0">
                  <div className="text-body font-semibold">Sign Out of All Devices</div>
                  <div className="text-[11px] muted">Revokes every active session on your account</div>
                </div>
              </div>
              <SignOutButton variant="light" fullWidth={false} className="shrink-0 !border-rose-200 !text-rose-700" />
            </div>
          </div>
        </SectionCard>
      </div>
    </StubPage>
  );
}
