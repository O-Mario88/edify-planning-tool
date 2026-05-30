"use client";

// PartnerProfileSheet — contract + scope + people in one calm sheet.
// Three cards: Identity & status · Scope & contract · People &
// reporting. Read-only by design; mutation routes through "Request
// change" CTAs that ping the assigned CCEO.

import { Building2, ShieldCheck, MapPin, Calendar, Users, Mail, Phone, Send } from "lucide-react";
import { cn } from "@/lib/utils";

const ORG = {
  name: "Bright Future Education Partners",
  partnerCode: "BFEP-UG-012",
  status: "Active" as const,
  joinedAt: "Jan 15, 2026",
  category: "Training Provider",
  websiteOrEmail: "info@brightfuture.org",
};

const SCOPE = {
  contractRef: "BFEP-CTR-2026-001",
  contractStart: "Jan 1, 2026",
  contractEnd: "Dec 31, 2026",
  contractMonthsLeft: 7,
  districts: ["Mukono", "Kayunga"],
  subCountiesCount: 8,
  schoolsCount: 24,
  allowedActivities: [
    "In-School training",
    "Teacher training",
    "Follow-Up visit",
    "Coaching visit",
    "Classroom observation",
    "Resource delivery",
  ],
  paymentModel: "Reimbursement · UGX per verified activity",
  paymentTerms: "Net 14 from accountant clearance",
};

const PEOPLE = {
  partnerFocal: { name: "Daniel Mwangi",     role: "Partner Admin",          email: "daniel.mwangi@brightfuture.org", phone: "+256 700 123 456" },
  partnerFieldOfficer: { name: "Ruth Kabuye", role: "Field Officer",         email: "ruth.kabuye@brightfuture.org",   phone: "+256 700 222 333" },
  edifyFocal:   { name: "Sarah Nanyongo",    role: "Edify CCEO (Mukono)",    email: "sarah.nanyongo@edify.org",       phone: "+256 701 987 654" },
  edifyPl:      { name: "Daniel Mwangi (PL)",role: "Country Program Lead",   email: "daniel.mwangi@edify.org",        phone: "+256 702 555 444" },
};

const REPORTING = [
  { key: "weekly",    label: "Weekly partner update",   cadence: "Every Mon (covers prior week)" },
  { key: "monthly",   label: "Monthly impact summary",  cadence: "Last business day of each month" },
  { key: "quarterly", label: "Quarterly performance",   cadence: "Within 10 business days of Q close" },
  { key: "special",   label: "Special incident report", cadence: "Within 48h of any incident" },
];

const VERIFY = [
  "Activity report — narrative of what was delivered",
  "Attendance / participant proof",
  "School + date confirmation",
  "SSA / support-need link",
  "Debrief + recommendations",
  "Supporting documents (photos where allowed)",
];

export function PartnerProfileSheet() {
  return (
    <div className="grid grid-cols-12 gap-4">
      {/* Identity */}
      <section className="card p-3.5 col-span-12 lg:col-span-5">
        <header className="flex items-start gap-3">
          <span className="h-12 w-12 shrink-0 rounded-2xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center text-body-lg font-extrabold">
            BF
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-[16px] font-extrabold tracking-tight">{ORG.name}</h2>
              <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide bg-emerald-50 text-emerald-700 border border-emerald-200">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                {ORG.status}
              </span>
            </div>
            <p className="text-[11.5px] muted mt-1">Partner Code: <span className="font-semibold text-[var(--color-edify-text)]">{ORG.partnerCode}</span></p>
          </div>
        </header>
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
          <Stat label="Category"    value={ORG.category}    Icon={Building2} />
          <Stat label="Joined"      value={ORG.joinedAt}    Icon={Calendar} />
          <Stat label="Org contact" value={ORG.websiteOrEmail} Icon={Mail} />
          <Stat label="Status"      value={`Contract ${SCOPE.contractMonthsLeft} months remaining`} Icon={ShieldCheck} />
        </dl>
        <footer className="mt-4 pt-3 border-t border-[var(--color-edify-divider)] flex items-center justify-between gap-2">
          <p className="text-[11px] muted">
            Changes to org name, code, or status must be approved by the Country Program Lead.
          </p>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
          >
            Request change <Send size={11} />
          </button>
        </footer>
      </section>

      {/* Scope & contract */}
      <section className="card p-3.5 col-span-12 lg:col-span-7">
        <header className="flex items-center gap-2 mb-3">
          <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
            <ShieldCheck size={14} />
          </span>
          <h3 className="text-[15px] font-extrabold tracking-tight">Scope &amp; contract</h3>
        </header>

        <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-3 mb-4">
          <Stat label="Contract ref"   value={SCOPE.contractRef} Icon={ShieldCheck} />
          <Stat label="Period"         value={`${SCOPE.contractStart} - ${SCOPE.contractEnd}`} Icon={Calendar} />
          <Stat label="Months left"    value={`${SCOPE.contractMonthsLeft} months`} Icon={Calendar} />
          <Stat label="Districts"      value={SCOPE.districts.join(", ")} Icon={MapPin} />
          <Stat label="Sub-counties"   value={`${SCOPE.subCountiesCount} sub-counties`} Icon={MapPin} />
          <Stat label="Schools"        value={`${SCOPE.schoolsCount} schools`} Icon={Building2} />
        </dl>

        <div className="rounded-xl border border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30 px-3.5 py-3 mb-3">
          <div className="text-caption uppercase tracking-wider font-bold muted">Allowed activity types</div>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {SCOPE.allowedActivities.map((a) => (
              <li key={a} className="inline-flex items-center px-2 py-[3px] rounded-md text-[11px] font-semibold bg-white border border-[var(--color-edify-border)]">
                {a}
              </li>
            ))}
          </ul>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <PanelBox label="Payment model" value={SCOPE.paymentModel} />
          <PanelBox label="Payment terms" value={SCOPE.paymentTerms} />
        </div>
      </section>

      {/* People */}
      <section className="card p-3.5 col-span-12 lg:col-span-7">
        <header className="flex items-center gap-2 mb-3">
          <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
            <Users size={14} />
          </span>
          <h3 className="text-[15px] font-extrabold tracking-tight">People</h3>
        </header>
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
          <PersonCard {...PEOPLE.partnerFocal}        side="partner" />
          <PersonCard {...PEOPLE.partnerFieldOfficer} side="partner" />
          <PersonCard {...PEOPLE.edifyFocal}          side="edify"   />
          <PersonCard {...PEOPLE.edifyPl}             side="edify"   />
        </ul>
      </section>

      {/* Reporting + verification */}
      <section className="card p-3.5 col-span-12 lg:col-span-5">
        <header className="mb-3">
          <h3 className="text-[15px] font-extrabold tracking-tight">Reporting &amp; verification</h3>
          <p className="text-[11.5px] muted mt-1">
            Cadence Edify expects, and what counts as evidence.
          </p>
        </header>
        <ul className="space-y-2 mb-4">
          {REPORTING.map((r) => (
            <li key={r.key} className="flex items-center justify-between gap-3 text-[11.5px]">
              <span className="font-extrabold text-[var(--color-edify-text)] truncate">{r.label}</span>
              <span className="muted whitespace-nowrap">{r.cadence}</span>
            </li>
          ))}
        </ul>
        <div className="rounded-xl border border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30 px-3.5 py-3">
          <div className="text-caption uppercase tracking-wider font-bold muted">Verification requirements</div>
          <ul className="mt-2 space-y-1">
            {VERIFY.map((v) => (
              <li key={v} className="text-[11.5px] inline-flex items-start gap-1.5 w-full">
                <span className="mt-1.5 h-1 w-1 rounded-full bg-[var(--color-edify-muted)] shrink-0" />
                <span className="text-[var(--color-edify-text)]">{v}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}

function Stat({
  label, value, Icon,
}: {
  label: string;
  value: string;
  Icon: typeof Building2;
}) {
  return (
    <div className="flex items-start gap-2 min-w-0">
      <span className="mt-0.5 grid place-items-center h-6 w-6 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
        <Icon size={11} />
      </span>
      <div className="min-w-0">
        <dt className="text-[10px] uppercase tracking-wide font-bold muted">{label}</dt>
        <dd className="text-[12px] font-extrabold text-[var(--color-edify-text)] truncate">{value}</dd>
      </div>
    </div>
  );
}

function PanelBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[var(--color-edify-divider)] bg-white px-3.5 py-3">
      <div className="text-caption uppercase tracking-wider font-bold muted">{label}</div>
      <div className="text-body font-extrabold mt-1 text-[var(--color-edify-text)]">{value}</div>
    </div>
  );
}

function PersonCard({
  name, role, email, phone, side,
}: {
  name: string;
  role: string;
  email: string;
  phone: string;
  side: "partner" | "edify";
}) {
  const tone = side === "partner"
    ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]"
    : "bg-emerald-50 text-emerald-700";
  const initials = name.split(" ").map((p) => p[0]).join("").slice(0, 2);
  return (
    <li className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3 flex items-center gap-3">
      <span className={cn("grid place-items-center h-10 w-10 rounded-full font-extrabold text-[12px]", tone)}>
        {initials}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-body font-extrabold tracking-tight truncate">{name}</div>
        <div className="text-caption muted truncate">{role}</div>
        <div className="text-caption muted mt-1 flex items-center gap-3">
          <a href={`mailto:${email}`} className="inline-flex items-center gap-1 hover:text-[var(--color-edify-text)] truncate">
            <Mail size={10} /> {email}
          </a>
        </div>
        <div className="text-caption muted mt-0.5 inline-flex items-center gap-1">
          <Phone size={10} /> {phone}
        </div>
      </div>
    </li>
  );
}
