"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import {
  CheckCircle2,
  Loader2,
  X,
  Users,
  Briefcase,
  Globe,
  Wallet,
  ShieldCheck,
  Sparkles,
  UserCog,
  Handshake,
  type LucideIcon,
} from "lucide-react";
import type { EdifyRole } from "@/lib/auth-public";
import { cn } from "@/lib/utils";
import { spring } from "@/lib/motion";
import { fetchJson } from "@/lib/csrf-client";

type DemoRole = {
  role:    EdifyRole;
  email:   string;
  name:    string;
  initials:string;
  blurb:   string;
  Icon:    LucideIcon;
  tone:    "edify" | "amber" | "green" | "rose" | "violet" | "sky" | "slate";
};

const DEMO_ROLES: DemoRole[] = [
  { role: "CCEO",               email: "paul.chinyama@edify.org",  name: "Paul Chinyama",  initials: "PC", blurb: "Field staff — my schools, plans, debriefs",        Icon: Briefcase,    tone: "edify"  },
  { role: "CountryProgramLead", email: "daniel.mwangi@edify.org",  name: "Daniel Mwangi",  initials: "DM", blurb: "Program Lead — my team + my field work",            Icon: Users,        tone: "amber"  },
  { role: "CountryDirector",    email: "sarah.okello@edify.org",   name: "Sarah Okello",   initials: "SO", blurb: "Country Director — national cockpit",                Icon: Globe,        tone: "violet" },
  { role: "RVP",                email: "esther.wanjiru@edify.org", name: "Esther Wanjiru", initials: "EW", blurb: "Regional VP — final approval + country rollups",    Icon: Sparkles,     tone: "violet" },
  { role: "ProgramAccountant",  email: "moses.tindi@edify.org",    name: "Moses Tindi",    initials: "MT", blurb: "Accountant — fund review, disbursement, variance",  Icon: Wallet,       tone: "green"  },
  { role: "ImpactAssessment",   email: "grace.alimo@edify.org",    name: "Grace Alimo",    initials: "GA", blurb: "M&E — verification queue + data intake",            Icon: ShieldCheck,  tone: "sky"    },
  { role: "HumanResource",      email: "anne.wairimu@edify.org",   name: "Anne Wairimu",   initials: "AW", blurb: "HR — fair performance, support reviews",            Icon: Users,        tone: "rose"   },
  { role: "Admin",              email: "admin@edify.org",          name: "Edify Admin",    initials: "EA", blurb: "Admin — tenant controls + cost settings",           Icon: UserCog,      tone: "slate"  },
  { role: "PartnerAdmin",       email: "daniel.mwangi@brightfuture.org", name: "Daniel Mwangi (BFEP)", initials: "DM", blurb: "Delivery Partner — command center, evidence, payments", Icon: Handshake, tone: "green" },
];

const TONE = {
  edify:  "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  amber:  "bg-amber-100   text-amber-700",
  green:  "bg-emerald-100 text-emerald-700",
  rose:   "bg-rose-100    text-rose-700",
  violet: "bg-violet-100  text-violet-700",
  sky:    "bg-sky-100     text-sky-700",
  slate:  "bg-slate-100   text-slate-700",
} as const;

export function RoleSwitcher({ currentRole }: { currentRole: EdifyRole }) {
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const [switching, setSwitching] = useState<EdifyRole | null>(null);
  const reduce = useReducedMotion();
  const router = useRouter();

  // The avatar menu (AvatarMenu) dispatches `edify:open-role-switcher`
  // when the user picks "Switch role" — we listen here so the floating
  // pill is unnecessary. Single trigger surface, less visual noise.
  useEffect(() => {
    function onOpen() { setOpen(true); }
    window.addEventListener("edify:open-role-switcher", onOpen);
    return () => window.removeEventListener("edify:open-role-switcher", onOpen);
  }, []);

  const switchTo = async (role: DemoRole) => {
    setSwitching(role.role);
    try {
      const { ok } = await fetchJson("/api/demo/role-switch", {
        body: { email: role.email },
      });
      if (!ok) throw new Error("switch failed");
      startTransition(() => {
        setOpen(false);
        router.refresh();
        // Hard reload so server components re-render with new cookies.
        window.location.href = LANDING_BY_ROLE[role.role];
      });
    } catch {
      setSwitching(null);
    }
  };

  return (
    <>
      {/* Sheet only — trigger lives in the avatar menu via custom event. */}
      <AnimatePresence>
        {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <motion.div
            initial={reduce ? false : { y: 24, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={reduce ? { opacity: 0 } : { y: 24, opacity: 0 }}
            transition={reduce ? { duration: 0 } : spring.soft}
            className="absolute bottom-0 right-0 left-0 sm:top-16 sm:bottom-auto sm:right-4 sm:left-auto sm:w-[460px] sm:max-w-[90vw] rounded-t-3xl sm:rounded-2xl bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-edify-border)]">
              <div>
                <h2 className="text-body-lg font-extrabold tracking-tight">Demo · Switch role</h2>
                <p className="text-caption muted">Currently signed in as <span className="font-extrabold text-[var(--color-edify-text)]">{LABEL_BY_ROLE[currentRole]}</span></p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="h-8 w-8 rounded-md grid place-items-center hover:bg-[var(--color-edify-soft)]/60"
                aria-label="Close"
              >
                <X size={14} className="text-[var(--color-edify-muted)]" />
              </button>
            </header>

            <ul className="max-h-[60vh] sm:max-h-[480px] overflow-y-auto py-1.5">
              {DEMO_ROLES.map((r) => {
                const active = r.role === currentRole;
                const isBusy = switching === r.role || pending && switching === r.role;
                return (
                  <li key={r.role}>
                    <button
                      type="button"
                      disabled={active || isBusy}
                      onClick={() => switchTo(r)}
                      className={cn(
                        "w-full flex items-start gap-3 px-4 py-2.5 text-left transition-colors",
                        active
                          ? "bg-[var(--color-edify-soft)]/40 cursor-default"
                          : "hover:bg-[var(--color-edify-soft)]/40 cursor-pointer",
                      )}
                    >
                      <span className={cn("h-9 w-9 rounded-full grid place-items-center shrink-0", TONE[r.tone])}>
                        <r.Icon size={14} />
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-baseline justify-between gap-2">
                          <div className="text-body font-extrabold tracking-tight truncate">{r.name}</div>
                          {active && (
                            <span className="text-[10px] font-extrabold uppercase tracking-wide text-emerald-700 inline-flex items-center gap-1">
                              <CheckCircle2 size={10} />
                              Active
                            </span>
                          )}
                        </div>
                        <div className="text-caption muted">{LABEL_BY_ROLE[r.role]}</div>
                        <div className="text-[11px] muted leading-snug line-clamp-1">{r.blurb}</div>
                      </div>
                      {isBusy && <Loader2 size={14} className="animate-spin text-[var(--color-edify-muted)] shrink-0 mt-2" />}
                    </button>
                  </li>
                );
              })}
            </ul>

            <footer className="px-4 py-2.5 border-t border-[var(--color-edify-border)] text-caption muted">
              Demo Mode · Role switches are instant. Status overlays + audit entries are stored in the browser.
            </footer>
          </motion.div>
        </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

const LABEL_BY_ROLE: Record<EdifyRole, string> = {
  CCEO:                "CCEO",
  CountryProgramLead:  "Program Lead",
  CountryDirector:     "Country Director",
  RVP:                 "RVP",
  ProgramAccountant:   "Accountant",
  ImpactAssessment:    "Impact Assessment",
  HumanResource:       "Human Resource",
  Admin:               "Admin",
  PartnerAdmin:        "Partner Admin",
  PartnerFieldOfficer: "Partner Field Officer",
  PartnerViewer:       "Partner Viewer",
};

const LANDING_BY_ROLE: Record<EdifyRole, string> = {
  CCEO:                "/dashboards/cceo",
  CountryProgramLead:  "/dashboards/cpl",
  CountryDirector:     "/dashboards/director",
  RVP:                 "/dashboards/rvp",
  ProgramAccountant:   "/dashboards/accountant",
  ImpactAssessment:    "/dashboards/impact",
  HumanResource:       "/dashboards/hr",
  Admin:               "/dashboards/director",
  PartnerAdmin:        "/dashboards/partner",
  PartnerFieldOfficer: "/dashboards/partner",
  PartnerViewer:       "/dashboards/partner",
};
