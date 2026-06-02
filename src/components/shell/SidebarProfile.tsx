"use client";

// SidebarProfile — the ONE identity surface for the whole app.
//
// Lives at the foot of every sidebar (all roles + the mobile drawer). Shows the
// user's framed headshot (or initials), name, primary district, role, and online
// status, and opens an upward popover with the account menu: Profile, Settings,
// Appearance, Switch role (demo — removed on deployment), Sign Out.
//
// This replaces the old upper-right avatar menu — there is exactly one place to
// manage your account now, and exactly one avatar to upload a photo to.

import { useEffect, useRef, useState } from "react";
import {
  User as UserIcon,
  Settings as SettingsIcon,
  LogOut,
  ChevronUp,
} from "lucide-react";
import { ProfileAvatar } from "@/components/ui/ProfileAvatar";
import { MenuLink, RoleSwitchButton, ThemeToggle } from "@/components/shell/AvatarMenu";
import { cn } from "@/lib/utils";

// Concise role labels for the profile row (not the verbose console names).
const ROLE_LABEL: Record<string, string> = {
  CCEO:                "CCEO",
  CountryProgramLead:  "Program Lead",
  CountryDirector:     "Country Director",
  RVP:                 "Regional VP",
  ProgramAccountant:   "Accountant",
  ImpactAssessment:    "M&E / Impact",
  HumanResource:       "Human Resource",
  Admin:               "Administrator",
  PartnerAdmin:        "Partner Admin",
  PartnerFieldOfficer: "Partner Field Officer",
  PartnerViewer:       "Partner Viewer",
};

export function SidebarProfile({
  staffId,
  name,
  initials,
  color = "#10b981",
  role,
  district,
  online = true,
  onNavigate,
}: {
  staffId: string;
  name: string;
  initials: string;
  color?: string;
  role: string;
  district?: string;
  online?: boolean;
  /** Called when a menu link is followed (so the parent can close the drawer). */
  onNavigate?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const roleLabel = ROLE_LABEL[role] ?? role;

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const close = () => setOpen(false);
  const followLink = () => { setOpen(false); onNavigate?.(); };

  return (
    <div ref={wrapperRef} className="relative">
      {/* Profile row — click to open the account menu. */}
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "w-full flex items-center gap-3 rounded-xl border border-white/10 p-2.5 text-left transition-colors",
          open ? "bg-white/[.12]" : "bg-white/[.06] hover:bg-white/[.1]",
        )}
      >
        <span className="relative shrink-0">
          <ProfileAvatar staffId={staffId} name={name} initials={initials} color={color} size={40} rounded="full" ring />
          {online && (
            <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-400 border-2 border-[var(--color-edify-deep)]" />
          )}
        </span>
        <span className="leading-tight min-w-0 flex-1">
          <span className="block text-[13px] font-extrabold text-white truncate">{name}</span>
          {district && <span className="block text-[11px] text-white/70 font-semibold truncate">{district}</span>}
          <span className="block text-[11px] text-white/60 truncate">{roleLabel}</span>
          <span className="mt-0.5 flex items-center gap-1.5 text-[10px] text-white/80">
            <span className={cn("w-1.5 h-1.5 rounded-full inline-block", online ? "bg-emerald-400" : "bg-white/40")} />
            {online ? "Online" : "Offline"}
          </span>
        </span>
        <ChevronUp size={15} className={cn("text-white/55 shrink-0 transition-transform", open ? "" : "rotate-180")} />
      </button>

      {/* Account menu — opens upward (the profile sits at the foot of the rail). */}
      {open && (
        <div
          role="menu"
          aria-label="Account menu"
          className="premium-popover absolute left-0 right-0 bottom-[calc(100%+8px)] rounded-2xl text-[var(--color-edify-text)] shadow-[0_18px_44px_-16px_rgba(0,0,0,0.45)] overflow-hidden z-50"
        >
          {/* Identity header */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--color-edify-divider)]">
            <ProfileAvatar staffId={staffId} name={name} initials={initials} color={color} size={40} rounded="full" ring={false} />
            <div className="min-w-0">
              <div className="text-[13px] font-extrabold tracking-tight truncate">{name}</div>
              <div className="text-[11px] text-[var(--color-edify-muted)] truncate">{roleLabel}{district ? ` · ${district}` : ""}</div>
            </div>
          </div>

          {/* Links */}
          <div className="py-1.5">
            <MenuLink Icon={UserIcon}     label="Profile"  href="/profile"  onClose={followLink} />
            <MenuLink Icon={SettingsIcon} label="Settings" href="/settings" onClose={followLink} />
            <RoleSwitchButton onClose={close} />
          </div>

          {/* Appearance */}
          <div className="border-t border-[var(--color-edify-divider)] px-3 py-2.5">
            <div className="text-[10px] uppercase tracking-[0.08em] font-extrabold text-[var(--color-edify-muted)] mb-1.5 px-1">
              Appearance
            </div>
            <ThemeToggle />
          </div>

          {/* Sign Out */}
          <div className="border-t border-[var(--color-edify-divider)] py-1.5">
            <form action="/api/auth/logout" method="post">
              <button
                type="submit"
                className="w-full flex items-center gap-3 px-4 py-2 text-body font-semibold text-[#b42318] hover:bg-rose-50/40 dark:hover:bg-rose-500/10"
              >
                <LogOut size={14} />
                Sign Out
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
