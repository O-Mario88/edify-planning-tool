// Last-login digest.
//
// Mock today; an audit-event-backed query tomorrow. The shape is
// deliberately a single function `changesSince(sinceIso, role)` so
// when AuditEvent persistence ships, only this file's body changes
// and every caller stays the same.
//
// What the "What changed since you last looked" surface needs:
//
//   • The user's previous last-viewed timestamp (per role; an Admin
//     who's also a CD has two cursors).
//   • A normalised stream of changes the user can scroll.
//   • Severity tone for the dot colour.
//
// We use a non-HttpOnly cookie because (a) the value is non-sensitive,
// (b) we need it on both server and client without an extra round-trip,
// (c) it's per-browser anyway — a single user across two browsers
// gets two cursors, which is correct (each device has its own
// "since I last looked here" memory).

import type { ChangedSinceEntry } from "./action-types";
import type { EdifyRole } from "@/lib/auth-public";

export const LAST_VIEWED_COOKIE = "edify-last-viewed";

// Read the cookie from a server-component context. The caller passes
// the cookie string (Next 16 makes `cookies()` async; passing the raw
// header keeps this util sync + pure).
export function lastViewedFromCookieHeader(cookieHeader: string | null | undefined): Date | null {
  if (!cookieHeader) return null;
  for (const pair of cookieHeader.split(";")) {
    const idx = pair.indexOf("=");
    if (idx < 0) continue;
    const k = pair.slice(0, idx).trim();
    if (k !== LAST_VIEWED_COOKIE) continue;
    const value = decodeURIComponent(pair.slice(idx + 1).trim());
    const t = Date.parse(value);
    return Number.isFinite(t) ? new Date(t) : null;
  }
  return null;
}

// ────────── Mock change stream ──────────
//
// Hand-tuned so the digest always renders something — production
// replaces this body with a real `auditEvent.findMany({ where:
// { actorVisibleTo: role, createdAt: { gt: since } } })`.

type Seed = Omit<ChangedSinceEntry, "at"> & { hoursAgo: number };

const SEED_BY_ROLE: Record<EdifyRole, Seed[]> = {
  CCEO: [
    { id: "c1", kind: "Fund approved",            subject: "Week 2 fund slip",          context: "UGX 1.2M",  hoursAgo: 3,  tone: "success", href: "/weekly-funds" },
    { id: "c2", kind: "Salesforce match cleared", subject: "Mbale Central PS visit",   context: "Smart match", hoursAgo: 9, tone: "info",    href: "/data-verification" },
    { id: "c3", kind: "Plan returned for fix",    subject: "Your May plan",             context: "missing evidence on 2 visits", hoursAgo: 22, tone: "warn", href: "/my-plan" },
    { id: "c4", kind: "New school assigned",      subject: "Bright Future PS",          context: "Kitgum District",  hoursAgo: 36, tone: "info", href: "/schools" },
  ],
  CountryProgramLead: [
    { id: "p1", kind: "Plan submitted",           subject: "Grace Njeri",               context: "32 activities, UGX 4.2M", hoursAgo: 2,  tone: "info",    href: "/approvals" },
    { id: "p2", kind: "Staff behind pace",        subject: "Abdi Hassan",               context: "33% vs expected 70%",     hoursAgo: 5,  tone: "warn",    href: "/team-targets" },
    { id: "p3", kind: "School moved to high risk",subject: "Sunrise School",            context: "SSA dropped to 4.5",      hoursAgo: 8,  tone: "danger",  href: "/ssa" },
    { id: "p4", kind: "Funds disbursed",          subject: "James Otieno · Week 1",     context: "UGX 0.9M",                hoursAgo: 18, tone: "success", href: "/weekly-funds" },
    { id: "p5", kind: "Field debrief submitted",  subject: "East region",               context: "5 schools covered",       hoursAgo: 26, tone: "info",    href: "/debriefs" },
  ],
  CountryDirector: [
    { id: "d1", kind: "Plans approved by PLs",       subject: "12 plans this week",  context: "UGX 38M total",         hoursAgo: 4,  tone: "info",   href: "/approvals" },
    { id: "d2", kind: "Cost settings draft",         subject: "Q2 cost rates",       context: "awaiting your activation", hoursAgo: 14, tone: "warn", href: "/cost-settings" },
    { id: "d3", kind: "Country backlog cleared",     subject: "Salesforce match queue", context: "down from 164 to 81",   hoursAgo: 20, tone: "success", href: "/data-verification" },
    { id: "d4", kind: "RVP requested clarification", subject: "May funding envelope", context: "see RVP note",          hoursAgo: 30, tone: "warn",  href: "/approvals" },
  ],
  RVP: [
    { id: "r1", kind: "Country envelope submitted",  subject: "Uganda · May 2026",   context: "UGX 142M",              hoursAgo: 3,  tone: "info",    href: "/approvals" },
    { id: "r2", kind: "Country at risk",             subject: "Kenya · staff pace",  context: "5 of 8 CCEOs behind",   hoursAgo: 12, tone: "danger",  href: "/dashboards/rvp" },
    { id: "r3", kind: "Quarterly report ready",      subject: "Region Q1",           context: "ready to export",       hoursAgo: 28, tone: "success", href: "/reports" },
  ],
  ProgramAccountant: [
    { id: "a1", kind: "New fund approval",           subject: "Grace Njeri · Week 2", context: "UGX 1.2M ready to disburse", hoursAgo: 1, tone: "info", href: "/dashboards/accountant" },
    { id: "a2", kind: "Reimbursement claim",         subject: "James Otieno",         context: "UGX 220K · over-spend reason supplied", hoursAgo: 6, tone: "warn", href: "/weekly-funds" },
    { id: "a3", kind: "Balance return overdue",      subject: "Abdi Hassan · Week 1", context: "3 days past",          hoursAgo: 20, tone: "danger", href: "/dashboards/accountant" },
    { id: "a4", kind: "Receipt uploaded",            subject: "Purity Muthoni",       context: "Week 2 · 4 receipts",  hoursAgo: 11, tone: "success", href: "/dashboards/accountant" },
  ],
  ImpactAssessment: [
    { id: "i1", kind: "Possible matches queued",     subject: "12 activities",          context: "needs your review",  hoursAgo: 2,  tone: "warn",   href: "/data-verification" },
    { id: "i2", kind: "No-match records",            subject: "Mbale region",           context: "3 activities, no SF candidate", hoursAgo: 9, tone: "danger", href: "/data-verification" },
    { id: "i3", kind: "Quality cert. ready",         subject: "April records",          context: "ready for CD sign-off", hoursAgo: 24, tone: "success", href: "/quality-checks" },
  ],
  HumanResource: [
    { id: "h1", kind: "Staff fairness flag",       subject: "Purity Muthoni",         context: "low pace under very high load", hoursAgo: 4, tone: "warn", href: "/team-targets" },
    { id: "h2", kind: "Leave approved",            subject: "James Otieno · 3 days",  context: "May 18–20",            hoursAgo: 7, tone: "info",  href: "/leave" },
    { id: "h3", kind: "Coaching session logged",   subject: "Daniel Mwangi → Grace",  context: "30 min · Salesforce flow", hoursAgo: 19, tone: "success", href: "/team-targets" },
  ],
  ProjectCoordinator: [
    { id: "pc1", kind: "Project school assigned",  subject: "Soroti Faith Junior",    context: "EdTech project",          hoursAgo: 3,  tone: "info",    href: "/special-projects" },
    { id: "pc2", kind: "Partner evidence uploaded",subject: "World Vision · EdTech",  context: "follow-up visit form",    hoursAgo: 9,  tone: "success", href: "/special-projects" },
    { id: "pc3", kind: "Project impact available", subject: "Christ-Centered SEL",    context: "+3.0 on Christlike Behaviour", hoursAgo: 20, tone: "success", href: "/special-projects" },
  ],
  Admin: [
    { id: "ad1", kind: "User signup",              subject: "new.cceo@edify.org",     context: "pending role assignment", hoursAgo: 2, tone: "warn", href: "/admin" },
    { id: "ad2", kind: "Failed import",            subject: "school-roster.csv",      context: "3 rows rejected",        hoursAgo: 14, tone: "danger", href: "/admin" },
    { id: "ad3", kind: "Audit log spike",          subject: "Role-switch endpoint",   context: "12 calls in last hour",  hoursAgo: 5, tone: "info", href: "/admin/audit-log" },
  ],
  // Partner Operating Layer — change streams per partner user type.
  PartnerAdmin: [
    { id: "padm1", kind: "Activity returned",         subject: "Bright Future PS · Training",   context: "M&E requested missing training report", hoursAgo: 3,  tone: "warn",    href: "/dashboards/partner" },
    { id: "padm2", kind: "Activity verified",         subject: "Hope PS · Phonics Training",    context: "Counted toward national targets",       hoursAgo: 8,  tone: "success", href: "/dashboards/partner" },
    { id: "padm3", kind: "Follow-Up scheduled",       subject: "Hope PS · CCEO follow-up",      context: "by 26 May",                              hoursAgo: 14, tone: "info",    href: "/dashboards/partner" },
    { id: "padm4", kind: "Spot Check flag",           subject: "Sunrise School · Training",     context: "Possible duplicate attendance sheet",   hoursAgo: 22, tone: "danger",  href: "/dashboards/partner" },
  ],
  PartnerFieldOfficer: [
    { id: "pfo1", kind: "Today's activity assigned",  subject: "Hope PS · 10:30",               context: "Joint with CCEO Paul Chinyama",          hoursAgo: 1,  tone: "info",    href: "/dashboards/partner" },
    { id: "pfo2", kind: "Evidence accepted",          subject: "Hope PS · attendance sheet",    context: "M&E accepted",                            hoursAgo: 12, tone: "success", href: "/dashboards/partner" },
    { id: "pfo3", kind: "Evidence requested",         subject: "Bright Future PS",              context: "Training report missing",                 hoursAgo: 20, tone: "warn",    href: "/dashboards/partner" },
  ],
  PartnerViewer: [
    { id: "pv1", kind: "Activity verified",           subject: "Hope PS",                       context: "Phonics training counted",                hoursAgo: 8,  tone: "success", href: "/dashboards/partner" },
    { id: "pv2", kind: "Monthly impact report",       subject: "May 2026",                      context: "Available to download",                   hoursAgo: 30, tone: "info",    href: "/dashboards/partner" },
  ],
};

// Returns changes that happened after `since`. When `since` is null
// (the user has never recorded a view), we still return the most
// recent few so the digest is never empty on first visit.

export function changesSince(
  since: Date | null,
  role: EdifyRole,
  now: Date = new Date(),
): ChangedSinceEntry[] {
  const seeds = SEED_BY_ROLE[role] ?? [];
  return seeds
    .map<ChangedSinceEntry>((s) => {
      const at = new Date(now.getTime() - s.hoursAgo * 60 * 60 * 1000);
      return {
        id: s.id,
        kind: s.kind,
        subject: s.subject,
        context: s.context,
        at: at.toISOString(),
        tone: s.tone,
        href: s.href,
      };
    })
    .filter((e) => since === null || new Date(e.at).getTime() > since.getTime())
    .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
}

// Pretty "5h ago" rendering — keeps the digest scannable without
// pulling in date-fns.

export function relativeFromNow(iso: string, now: Date = new Date()): string {
  const diffMs = now.getTime() - new Date(iso).getTime();
  const min = Math.round(diffMs / 60_000);
  if (min < 1)  return "just now";
  if (min < 60) return `${min} min ago`;
  const hours = Math.round(min / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
