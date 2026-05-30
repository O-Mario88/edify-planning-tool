// District Gateway — the first question every plan answers:
// "Is the school in your primary district, or a secondary district?"
//
// Why this card exists:
// The CD-set cost rates differ sharply by district type — secondary
// district triggers higher transport, dinner allowance, and overnight
// accommodation by default. The user shouldn't have to math it. They
// pick the district type (or accept the auto-detection from their home
// base), drop in the schools they plan to visit, and the cost
// materializes from the canonical cost engine.
//
// What it does:
//   1. Shows the planner their home district (from StaffHomeBase).
//   2. Lets them toggle Primary / Secondary, or accept the auto-detection.
//   3. Lets them add/remove schools (mocked picker for the prototype —
//      the production version will pair with the PlanBuilder's school
//      selector).
//   4. Renders a live cost breakdown using computeVisitCost(). Lines
//      come straight from the engine — single source of truth.
//   5. Calls out the secondary-district drivers ("dinner & accommodation
//      auto-included") so the planner doesn't think the cost is wrong.
//
// This component lives in src/components/planning/ and is rendered at
// the very top of /plans/new (above the existing PlanBuilder).

"use client";

import { useMemo, useState } from "react";
import {
  Building2,
  Home,
  MapPin,
  Plus,
  TrendingUp,
  X,
} from "lucide-react";
import {
  computeVisitCost,
  type DistrictType,
  type SchoolStop,
  type VisitCostRates,
  type VisitMode,
} from "@/lib/cost-engine/cost-engine";
import { cn } from "@/lib/utils";

// ────────── Sample school catalog (prototype) ──────────
//
// In production this comes from the school directory + the planner's
// assigned portfolio. For the prototype we surface a handful so the
// planner can click around and see the rates shift.

type CatalogSchool = SchoolStop & { district: string };

const SCHOOL_CATALOG: CatalogSchool[] = [
  { schoolId: "S-HP-1", schoolName: "Hope Primary School",   district: "Mukono",  districtType: "primary"   },
  { schoolId: "S-MK-1", schoolName: "Mukono Central PS",     district: "Mukono",  districtType: "primary"   },
  { schoolId: "S-GP-1", schoolName: "Grace Primary School",  district: "Mukono",  districtType: "primary"   },
  { schoolId: "S-VP-1", schoolName: "Victory Primary School", district: "Mukono",  districtType: "primary"   },
  { schoolId: "S-KT-1", schoolName: "Kitgum Central PS",     district: "Kitgum",  districtType: "secondary" },
  { schoolId: "S-KT-2", schoolName: "Layibi Memorial PS",    district: "Kitgum",  districtType: "secondary" },
  { schoolId: "S-KT-3", schoolName: "Pajule Primary",        district: "Kitgum",  districtType: "secondary" },
];

// ────────── Props ──────────

export type DistrictGatewayCardProps = {
  /// Staff's home district label — used to render the "primary district"
  /// callout. Currently mocked; production pulls from StaffHomeBase.
  homeDistrict: string;
  /// Canonical CD-set rates. Read server-side via loadVisitCostRates().
  rates: VisitCostRates;
};

// ────────── Helpers ──────────

const ugxFormatter = new Intl.NumberFormat("en-UG", { maximumFractionDigits: 0 });
const fmtUgx = (n: number) => `UGX ${ugxFormatter.format(n)}`;

// ────────── Component ──────────

export function DistrictGatewayCard({ homeDistrict, rates }: DistrictGatewayCardProps) {
  // Visit mode — partner vs staff. Partner short-circuits to the lump sum.
  const [mode, setMode] = useState<VisitMode>("staff");
  // Selected schools (chips).
  const [selected, setSelected] = useState<CatalogSchool[]>([SCHOOL_CATALOG[0]]);
  // Day count (1..5 in practice).
  const [days, setDays] = useState<number>(1);

  // Auto-detected district type for the current selection.
  const autoDistrictType: DistrictType = useMemo(() => {
    if (selected.length === 0) return "primary";
    return selected.some((s) => s.districtType === "secondary") ? "secondary" : "primary";
  }, [selected]);

  // Allow the planner to override — but most of the time auto wins.
  // For the prototype the toggle simply switches the rate tier; in
  // production overriding triggers a CD-approval note on the plan.
  const [overrideDistrict, setOverrideDistrict] = useState<DistrictType | null>(null);
  const districtType = overrideDistrict ?? autoDistrictType;

  // Pricing — straight from the engine.
  const breakdown = useMemo(
    () =>
      computeVisitCost({
        mode,
        // If user overrode, treat all schools as that type so the engine
        // tier matches the explicit choice.
        schools: selected.map((s) => ({ ...s, districtType })),
        days,
        rates,
      }),
    [mode, selected, days, districtType, rates],
  );

  // Selection helpers.
  const addSchool = (s: CatalogSchool) => {
    if (selected.some((x) => x.schoolId === s.schoolId)) return;
    setSelected([...selected, s]);
  };
  const removeSchool = (id: string) => setSelected(selected.filter((s) => s.schoolId !== id));
  const reset = () => {
    setSelected([SCHOOL_CATALOG[0]]);
    setDays(1);
    setOverrideDistrict(null);
    setMode("staff");
  };

  const availableSchools = SCHOOL_CATALOG.filter(
    (s) => !selected.some((x) => x.schoolId === s.schoolId),
  );
  const isSecondary = districtType === "secondary";

  return (
    <section
      aria-labelledby="district-gateway-title"
      className={cn(
        "card-elevated rounded-2xl overflow-hidden",
        isSecondary ? "card-rail-amber" : "card-rail-emerald",
      )}
    >
      <div className="p-4 sm:p-5 space-y-4">
        {/* Header */}
        <header className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0 flex-1">
            <div className="text-caption font-extrabold uppercase tracking-wider text-[var(--color-edify-primary)] inline-flex items-center gap-1.5">
              <MapPin size={11} />
              Step 1 · District gateway
            </div>
            <h2 id="district-gateway-title" className="mt-1 text-[17px] font-extrabold tracking-tight leading-tight">
              Where is this visit?
            </h2>
            <p className="text-body muted mt-1 leading-snug max-w-[640px]">
              Pick the schools you're planning to visit. The cost engine fills in transport,
              meals, and (for secondary district trips) accommodation — using the rates the
              Country Director has set.
            </p>
          </div>
          <button
            type="button"
            onClick={reset}
            className="text-[11px] muted font-semibold hover:text-[var(--color-edify-text)] underline-offset-4 hover:underline"
          >
            Reset
          </button>
        </header>

        {/* Mode toggle — staff vs partner */}
        <div className="flex items-center gap-2 flex-wrap">
          <ModePill
            label="Staff visit"
            active={mode === "staff"}
            onClick={() => setMode("staff")}
            hint="Transport + meals + accommodation if overnight"
          />
          <ModePill
            label="Partner visit"
            active={mode === "partner"}
            onClick={() => setMode("partner")}
            hint={`Flat ${fmtUgx(rates.partnerLumpSumPerSchool)} per school`}
          />
        </div>

        {/* Home district + district-type chooser (staff only) */}
        {mode === "staff" && (
          <div className="grid sm:grid-cols-3 gap-3">
            <div className="rounded-lg border border-[var(--color-edify-border)] bg-white p-3 sm:col-span-1">
              <div className="flex items-center gap-1.5 text-caption font-bold uppercase tracking-wide muted">
                <Home size={11} className="text-[var(--color-edify-primary)]" />
                Your home base
              </div>
              <div className="text-body-lg font-extrabold mt-1">{homeDistrict}</div>
              <div className="text-[11px] muted leading-snug mt-1">
                A school in <span className="font-extrabold text-[var(--color-edify-text)]">{homeDistrict}</span> is your <span className="font-extrabold text-[var(--color-edify-text)]">primary district</span>. Any other district counts as <span className="font-extrabold text-[var(--color-edify-text)]">secondary</span>.
              </div>
            </div>
            <div className="sm:col-span-2 rounded-lg border border-[var(--color-edify-border)] bg-white p-3">
              <div className="text-caption font-bold uppercase tracking-wide muted">District type for this trip</div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <DistrictTypeChoice
                  type="primary"
                  active={districtType === "primary"}
                  autoDetected={autoDistrictType === "primary"}
                  onClick={() => setOverrideDistrict(autoDistrictType === "primary" ? null : "primary")}
                  rate={rates.staffPrimaryTransportPerSchool}
                />
                <DistrictTypeChoice
                  type="secondary"
                  active={districtType === "secondary"}
                  autoDetected={autoDistrictType === "secondary"}
                  onClick={() => setOverrideDistrict(autoDistrictType === "secondary" ? null : "secondary")}
                  rate={rates.staffSecondaryTransportPerSchool}
                />
              </div>
              {overrideDistrict && overrideDistrict !== autoDistrictType && (
                <div className="text-caption mt-2 rounded-md bg-amber-50 border border-amber-200 text-amber-900 px-2 py-1.5 leading-snug">
                  You overrode the auto-detection. Plans flagged for override require CPL sign-off before approval.
                </div>
              )}
            </div>
          </div>
        )}

        {/* Schools picker — chips */}
        <div className="space-y-2">
          <div className="flex items-baseline justify-between gap-2 flex-wrap">
            <div className="text-caption muted font-bold uppercase tracking-wide">
              Schools on this trip ({selected.length})
            </div>
            {mode === "staff" && (
              <DaysPicker days={days} setDays={setDays} />
            )}
          </div>

          {selected.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 px-3 py-3 text-[11.5px] muted text-center">
              No schools selected yet — pick from the list below to estimate cost.
            </div>
          ) : (
            <ul className="flex flex-wrap gap-2">
              {selected.map((s) => (
                <li
                  key={s.schoolId}
                  className={cn(
                    "inline-flex items-center gap-1.5 pl-2.5 pr-1 py-1 rounded-full border bg-white text-[12px]",
                    s.districtType === "secondary"
                      ? "border-amber-300 ring-1 ring-amber-100"
                      : "border-[var(--color-edify-border)]",
                  )}
                >
                  <Building2 size={11} className="text-[var(--color-edify-primary)]" />
                  <span className="font-bold">{s.schoolName}</span>
                  <span className="text-caption muted">· {s.district}</span>
                  <button
                    type="button"
                    onClick={() => removeSchool(s.schoolId)}
                    aria-label={`Remove ${s.schoolName}`}
                    className="w-5 h-5 rounded-full grid place-items-center hover:bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]"
                  >
                    <X size={11} />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {availableSchools.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-1">
              {availableSchools.map((s) => (
                <button
                  key={s.schoolId}
                  type="button"
                  onClick={() => addSchool(s)}
                  className={cn(
                    "inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[11px] font-semibold transition-colors",
                    "border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60",
                    s.districtType === "secondary" && "text-amber-800",
                  )}
                >
                  <Plus size={10} />
                  {s.schoolName}
                  <span className="text-caption muted font-medium">· {s.district}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Cost preview — the payoff */}
        <CostPreview
          totalUgx={breakdown.totalUgx}
          lines={breakdown.lines}
          mode={mode}
          isSecondary={isSecondary}
        />

        {/* Footnote — explains the rule, attributes to CD */}
        <p className="text-caption muted leading-snug pt-1">
          {mode === "partner"
            ? <>Partner visits are charged as a <span className="font-extrabold">single lump sum per school</span>, set by the Country Director. No further breakdown.</>
            : isSecondary
              ? <>Secondary-district trips include <span className="font-extrabold">transport at {fmtUgx(rates.staffSecondaryTransportPerSchool)}/school</span>, <span className="font-extrabold">lunch + dinner</span>, and <span className="font-extrabold">accommodation auto-included</span> for nights beyond day one. Rates set by the Country Director.</>
              : <>Primary-district trips include <span className="font-extrabold">transport at {fmtUgx(rates.staffPrimaryTransportPerSchool)}/school</span> and <span className="font-extrabold">lunch per day</span>. No overnight by default. Rates set by the Country Director.</>
          }
        </p>
      </div>
    </section>
  );
}

// ────────── Atoms ──────────

function ModePill({
  label,
  active,
  hint,
  onClick,
}: {
  label: string;
  active: boolean;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex flex-col items-start gap-0.5 px-3 py-2 rounded-lg border text-left transition-colors",
        active
          ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-soft)] ring-2 ring-[var(--color-edify-soft)]"
          : "border-[var(--color-edify-border)] bg-white hover:border-[var(--color-edify-primary)]/60",
      )}
      aria-pressed={active}
    >
      <span className="text-body font-extrabold tracking-tight">{label}</span>
      <span className="text-caption muted leading-tight">{hint}</span>
    </button>
  );
}

function DistrictTypeChoice({
  type,
  active,
  autoDetected,
  onClick,
  rate,
}: {
  type: DistrictType;
  active: boolean;
  autoDetected: boolean;
  onClick: () => void;
  rate: number;
}) {
  const title = type === "primary" ? "Primary district" : "Secondary district";
  const sub = type === "primary"
    ? "Day-trip · lunch only"
    : "Overnight · dinner + accommodation included";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex flex-col items-start gap-1 p-2.5 rounded-lg border text-left transition-colors",
        active
          ? type === "primary"
            ? "border-emerald-400 bg-emerald-50/70 ring-2 ring-emerald-100"
            : "border-amber-400 bg-amber-50/70 ring-2 ring-amber-100"
          : "border-[var(--color-edify-border)] bg-white hover:border-[var(--color-edify-primary)]/60",
      )}
    >
      <div className="flex items-baseline justify-between gap-2 w-full">
        <span className="text-body font-extrabold">{title}</span>
        {autoDetected && (
          <span className="text-[9.5px] font-bold uppercase tracking-wide px-1.5 py-[1.5px] rounded bg-[var(--color-edify-dark)] text-white">
            Auto
          </span>
        )}
      </div>
      <div className="text-caption muted leading-tight">{sub}</div>
      <div className="text-caption muted font-semibold tabular">{fmtUgx(rate)}/school transport</div>
    </button>
  );
}

function DaysPicker({ days, setDays }: { days: number; setDays: (n: number) => void }) {
  return (
    <div className="inline-flex items-center gap-1 text-[11px]">
      <span className="muted font-semibold">Days:</span>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          onClick={() => setDays(n)}
          aria-pressed={days === n}
          className={cn(
            "w-6 h-6 rounded-md border text-[11px] font-bold tabular",
            days === n
              ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-soft)] text-[var(--color-edify-dark)]"
              : "border-[var(--color-edify-border)] bg-white text-[var(--color-edify-muted)] hover:border-[var(--color-edify-primary)]/60",
          )}
        >
          {n}
        </button>
      ))}
    </div>
  );
}

function CostPreview({
  totalUgx,
  lines,
  mode,
  isSecondary,
}: {
  totalUgx: number;
  lines: { label: string; amountUgx: number; note?: string }[];
  mode: VisitMode;
  isSecondary: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-3 sm:p-4",
        isSecondary && mode === "staff"
          ? "border-amber-200 bg-amber-50/40"
          : "border-emerald-200 bg-emerald-50/40",
      )}
    >
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <div>
          <div className="text-caption muted font-bold uppercase tracking-wide flex items-center gap-1.5">
            <TrendingUp size={11} />
            Estimated cost
          </div>
          <div className="text-caption muted mt-0.5">
            Auto-populated from the Country Director's rates · click schools above to update
          </div>
        </div>
        <div className="text-[28px] sm:text-[32px] font-extrabold tabular num-hero">
          {fmtUgx(totalUgx)}
        </div>
      </div>

      {lines.length > 0 && (
        <ul className="mt-3 space-y-1">
          {lines.map((line, i) => (
            <li
              key={i}
              className="flex items-baseline justify-between gap-2 text-[12px] py-1 border-b border-[var(--color-edify-divider)] last:border-b-0"
            >
              <span className="min-w-0">
                <span className="font-semibold text-[var(--color-edify-text)]">{line.label}</span>
                {line.note && (
                  <span className="ml-2 text-caption italic muted">— {line.note}</span>
                )}
              </span>
              <span className="tabular font-extrabold text-[var(--color-edify-text)] shrink-0">
                {fmtUgx(line.amountUgx)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
