"use client";

// MySchoolsList — every assigned school in one scrollable list so the
// partner can act on any of them without paging through cards. Each
// row shows the school + district + SSA band, the weak area being
// supported, when the school was last supported, and what's next on
// the schedule. The action column flips between "Schedule" (when
// nothing is on the books) and "View schedule" (when a date is set).

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  School, MapPin, Calendar, ArrowRight, Filter,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PartnerScheduleDrawer, type ScheduleOutcome } from "@/components/partner/PartnerScheduleDrawer";

type SchoolBand = "Critical" | "At Risk" | "On Track";

type PartnerSchoolRow = {
  id: string;
  name: string;
  district: "Mukono" | "Kayunga";
  subCounty: string;
  ssaScore: number;            // 0-10
  weakArea: string;
  activitiesDone: number;
  activitiesPending: number;
  lastSupport: string;
  scheduledOn?: string;        // e.g. "Wk 23 · May 19"
  scheduledActivity?: string;  // e.g. "Coaching visit"
};

// Full 24-school portfolio (matches the BFEP "24 schools assigned"
// stat on the dashboard hero). Mix of bands so the partner can see
// urgency at a glance.
const SCHOOLS: PartnerSchoolRow[] = [
  { id: "SCH-HOPE",     name: "Hope Primary School",       district: "Mukono",  subCounty: "Ntenjeru",        ssaScore: 4.2, weakArea: "Teaching & Learning", activitiesDone: 6, activitiesPending: 2, lastSupport: "May 13, 2026", scheduledOn: "Wk 24 · May 25",    scheduledActivity: "Follow-Up coaching visit" },
  { id: "SCH-GRACE",    name: "Grace Primary School",      district: "Mukono",  subCounty: "Nsumba",          ssaScore: 5.8, weakArea: "Numeracy",            activitiesDone: 4, activitiesPending: 1, lastSupport: "May 12, 2026", scheduledOn: "Wk 24 · May 27",    scheduledActivity: "In-School numeracy training" },
  { id: "SCH-KIREKA",   name: "Kireka Primary School",     district: "Mukono",  subCounty: "Kireka",          ssaScore: 6.4, weakArea: "Leadership",          activitiesDone: 8, activitiesPending: 1, lastSupport: "May 10, 2026", scheduledOn: "Wk 24 · May 16",    scheduledActivity: "Teacher training debrief" },
  { id: "SCH-STMARY",   name: "St. Mary's Primary",        district: "Kayunga", subCounty: "Kayunga Central", ssaScore: 5.1, weakArea: "Leadership",          activitiesDone: 5, activitiesPending: 1, lastSupport: "May 09, 2026", scheduledOn: "Wk 24 · May 17",    scheduledActivity: "Leadership support visit" },
  { id: "SCH-NAMI",     name: "Namilyango Primary",        district: "Mukono",  subCounty: "Namilyango",      ssaScore: 7.1, weakArea: "Resources",           activitiesDone: 7, activitiesPending: 0, lastSupport: "May 06, 2026", scheduledOn: "Wk 24 · May 20",    scheduledActivity: "Resource delivery" },
  { id: "SCH-MAPLE",    name: "Maple Grove Primary",       district: "Kayunga", subCounty: "Bbaale",          ssaScore: 3.6, weakArea: "Teaching & Learning", activitiesDone: 2, activitiesPending: 1, lastSupport: "Apr 22, 2026" },
  { id: "SCH-EDEN",     name: "Eden Foundation School",    district: "Mukono",  subCounty: "Nakifuma",        ssaScore: 5.9, weakArea: "Numeracy",            activitiesDone: 3, activitiesPending: 1, lastSupport: "Apr 30, 2026", scheduledOn: "Wk 25 · Jun 02",    scheduledActivity: "Classroom observation" },
  { id: "SCH-CLOVER",   name: "Clover Primary School",     district: "Kayunga", subCounty: "Galiraaya",       ssaScore: 6.8, weakArea: "Leadership",          activitiesDone: 4, activitiesPending: 0, lastSupport: "Apr 28, 2026", scheduledOn: "Wk 25 · Jun 03",    scheduledActivity: "Follow-Up visit" },
  { id: "SCH-SUNRISE",  name: "Sunrise Junior School",     district: "Mukono",  subCounty: "Mukono Central",  ssaScore: 4.8, weakArea: "Reading Fluency",     activitiesDone: 5, activitiesPending: 1, lastSupport: "Apr 26, 2026" },
  { id: "SCH-BRIGHT",   name: "Bright Future PS",          district: "Mukono",  subCounty: "Bukoto",          ssaScore: 6.2, weakArea: "Numeracy",            activitiesDone: 6, activitiesPending: 1, lastSupport: "Apr 24, 2026", scheduledOn: "Wk 24 · May 21",    scheduledActivity: "Resource delivery" },
  { id: "SCH-LAKE",     name: "Lakeview Primary",          district: "Kayunga", subCounty: "Galiraaya",       ssaScore: 5.4, weakArea: "Teacher Training",    activitiesDone: 3, activitiesPending: 2, lastSupport: "Apr 22, 2026", scheduledOn: "Wk 24 · May 22",    scheduledActivity: "Teacher training" },
  { id: "SCH-RIVER",    name: "Riverside Primary",         district: "Mukono",  subCounty: "Mukono Central",  ssaScore: 6.0, weakArea: "Numeracy",            activitiesDone: 4, activitiesPending: 1, lastSupport: "Apr 20, 2026", scheduledOn: "Wk 24 · May 23",    scheduledActivity: "Coaching visit" },
  { id: "SCH-HILL",     name: "Hilltop Basic School",      district: "Mukono",  subCounty: "Kireka",          ssaScore: 3.9, weakArea: "Phonics",             activitiesDone: 2, activitiesPending: 2, lastSupport: "Apr 18, 2026" },
  { id: "SCH-EAST",     name: "Eastview Junior",           district: "Mukono",  subCounty: "Nakifuma",        ssaScore: 7.4, weakArea: "Leadership",          activitiesDone: 9, activitiesPending: 0, lastSupport: "Apr 15, 2026", scheduledOn: "Wk 24 · May 25",    scheduledActivity: "Follow-Up visit" },
  { id: "SCH-MUKONO",   name: "Mukono Central PS",         district: "Mukono",  subCounty: "Mukono Central",  ssaScore: 5.6, weakArea: "Numeracy",            activitiesDone: 5, activitiesPending: 1, lastSupport: "Apr 14, 2026", scheduledOn: "Wk 24 · May 26",    scheduledActivity: "Classroom observation" },
  { id: "SCH-KHILL",    name: "Kayunga Hill School",       district: "Kayunga", subCounty: "Bbaale",          ssaScore: 4.5, weakArea: "Reading Comprehension",activitiesDone: 3, activitiesPending: 2, lastSupport: "Apr 12, 2026" },
  { id: "SCH-POPE",     name: "Pope John PS",              district: "Mukono",  subCounty: "Nakifuma",        ssaScore: 6.3, weakArea: "Lesson Planning",     activitiesDone: 4, activitiesPending: 1, lastSupport: "Apr 10, 2026", scheduledOn: "Wk 25 · May 28",    scheduledActivity: "Teacher training" },
  { id: "SCH-BBAALE",   name: "Bbaale Primary",            district: "Kayunga", subCounty: "Bbaale",          ssaScore: 5.7, weakArea: "Resources",           activitiesDone: 3, activitiesPending: 1, lastSupport: "Apr 09, 2026", scheduledOn: "Wk 25 · May 29",    scheduledActivity: "Resource delivery" },
  { id: "SCH-GALIRA",   name: "Galiraaya Primary",         district: "Kayunga", subCounty: "Galiraaya",       ssaScore: 3.2, weakArea: "Critical · multiple", activitiesDone: 1, activitiesPending: 3, lastSupport: "Apr 06, 2026" },
  { id: "SCH-NTENJERU", name: "Ntenjeru Primary",          district: "Mukono",  subCounty: "Ntenjeru",        ssaScore: 5.9, weakArea: "Classroom Management",activitiesDone: 4, activitiesPending: 1, lastSupport: "Apr 04, 2026", scheduledOn: "Wk 25 · Jun 02",    scheduledActivity: "In-School training" },
  { id: "SCH-KIRH",     name: "Kireka Hills PS",           district: "Mukono",  subCounty: "Kireka",          ssaScore: 5.0, weakArea: "Leadership",          activitiesDone: 3, activitiesPending: 1, lastSupport: "Apr 02, 2026" },
  { id: "SCH-KTRUST",   name: "Kayunga Trust School",      district: "Kayunga", subCounty: "Kayunga Central", ssaScore: 7.0, weakArea: "Library",             activitiesDone: 6, activitiesPending: 0, lastSupport: "Mar 31, 2026", scheduledOn: "Wk 25 · Jun 04",    scheduledActivity: "Resource delivery" },
  { id: "SCH-NSUMBA",   name: "Nsumba Primary",            district: "Mukono",  subCounty: "Nsumba",          ssaScore: 4.0, weakArea: "Early Numeracy",      activitiesDone: 2, activitiesPending: 2, lastSupport: "Mar 28, 2026" },
  { id: "SCH-NAKIF",    name: "Nakifuma Basic",            district: "Mukono",  subCounty: "Nakifuma",        ssaScore: 6.1, weakArea: "Early Reading",       activitiesDone: 4, activitiesPending: 1, lastSupport: "Mar 25, 2026", scheduledOn: "Wk 25 · Jun 06",    scheduledActivity: "Classroom observation" },
];

function bandFor(score: number): SchoolBand {
  if (score < 4.0) return "Critical";
  if (score < 6.0) return "At Risk";
  return "On Track";
}

const BAND_TONE: Record<SchoolBand, { chip: string; ring: string }> = {
  "Critical": { chip: "bg-rose-50 text-rose-700",       ring: "ring-rose-200"    },
  "At Risk":  { chip: "bg-amber-50 text-amber-700",     ring: "ring-amber-200"   },
  "On Track": { chip: "bg-emerald-50 text-emerald-700", ring: "ring-emerald-200" },
};

export function MySchoolsGrid() {
  const [districtFilter, setDistrictFilter] = useState<"all" | "Mukono" | "Kayunga">("all");
  const [bandFilter, setBandFilter] = useState<"all" | SchoolBand>("all");
  const [scheduling, setScheduling] = useState<PartnerSchoolRow | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const rows = useMemo(() => {
    return SCHOOLS.filter((s) => {
      if (districtFilter !== "all" && s.district !== districtFilter) return false;
      if (bandFilter !== "all" && bandFor(s.ssaScore) !== bandFilter) return false;
      return true;
    });
  }, [districtFilter, bandFilter]);

  function handleScheduleSubmit(outcome: ScheduleOutcome) {
    if (outcome.kind === "scheduled") {
      setToast(`Scheduled — your CCEO now sees this in their monitoring queue.`);
    } else if (outcome.kind === "request_change") {
      setToast(`Date-change request sent to your CCEO.`);
    } else {
      setToast(`Returned to CCEO for reassignment.`);
    }
    setTimeout(() => setToast(null), 4000);
  }

  return (
    <section className="card p-3.5">
      {/* Filter strip */}
      <header className="flex items-center justify-between gap-3 flex-wrap mb-3">
        <div className="flex items-center gap-1 flex-wrap">
          {(["all", "Mukono", "Kayunga"] as const).map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDistrictFilter(d)}
              className={cn(
                "inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-[11.5px] font-semibold transition-colors",
                districtFilter === d
                  ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
                  : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
              )}
            >
              {d === "all" ? "All districts" : d}
              <span className={cn(
                "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded-md text-[9.5px] font-extrabold",
                districtFilter === d ? "bg-[var(--color-edify-primary)] text-white" : "bg-slate-100 text-slate-700",
              )}>
                {d === "all" ? SCHOOLS.length : SCHOOLS.filter((s) => s.district === d).length}
              </span>
            </button>
          ))}
          <span className="mx-2 h-5 w-px bg-[var(--color-edify-divider)]" />
          {(["all", "Critical", "At Risk", "On Track"] as const).map((b) => (
            <button
              key={b}
              type="button"
              onClick={() => setBandFilter(b)}
              className={cn(
                "inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-[11.5px] font-semibold transition-colors",
                bandFilter === b
                  ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
                  : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
              )}
            >
              {b === "all" ? "All bands" : b}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
        >
          <Filter size={12} /> More filters
        </button>
      </header>

      {/* Table */}
      <div className="overflow-x-auto scrollbar -mx-1 px-1 rounded-md">
        <table className="w-full dtable">
          <thead className="bg-white">
            <tr>
              <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">School</th>
              {/* District + Last support hidden below lg so the school
                  name column breathes at tablet. Both available at lg+
                  and in the per-school detail page. */}
              <th className="hidden lg:table-cell text-left text-[10px] uppercase tracking-wide font-bold muted">District</th>
              <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">SSA</th>
              <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Weak area</th>
              <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Pending</th>
              <th className="hidden lg:table-cell text-left text-[10px] uppercase tracking-wide font-bold muted">Last support</th>
              <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Scheduled</th>
              <th className="text-right text-[10px] uppercase tracking-wide font-bold muted">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => <SchoolRow key={s.id} school={s} onSchedule={() => setScheduling(s)} />)}
          </tbody>
        </table>
      </div>

      {/* Footer count */}
      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[12px] muted">
        Showing <span className="font-semibold text-[var(--color-edify-text)]">{rows.length}</span>{" "}
        of <span className="font-semibold text-[var(--color-edify-text)]">{SCHOOLS.length}</span> assigned schools
      </div>

      {/* Schedule drawer */}
      <PartnerScheduleDrawer
        open={!!scheduling}
        activityLabel={
          scheduling
            ? `New ${scheduling.weakArea} support — ${scheduling.name}`
            : ""
        }
        schoolName={scheduling?.name ?? ""}
        urgency={
          scheduling
            ? (bandFor(scheduling.ssaScore) === "Critical" ? "Critical" :
               bandFor(scheduling.ssaScore) === "At Risk"  ? "High"     : "Medium")
            : "Medium"
        }
        onClose={() => setScheduling(null)}
        onSubmit={handleScheduleSubmit}
      />

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-body font-semibold px-4 py-3 max-w-[360px]">
          {toast}
        </div>
      )}
    </section>
  );
}

function SchoolRow({
  school: s, onSchedule,
}: {
  school: PartnerSchoolRow;
  onSchedule: () => void;
}) {
  const band = bandFor(s.ssaScore);
  const tone = BAND_TONE[band];
  return (
    <tr className="hover:bg-[var(--color-edify-soft)]/40 transition-colors">
      <td>
        <div className="flex items-center gap-2.5">
          <span className={cn(
            "grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0 ring-2",
            tone.ring,
          )}>
            <School size={13} />
          </span>
          <div className="min-w-0">
            <div className="text-body font-extrabold tracking-tight leading-tight">{s.name}</div>
            <div className="text-caption muted leading-tight inline-flex items-center gap-1 mt-0.5">
              <MapPin size={9} />
              {s.subCounty}
            </div>
          </div>
        </div>
      </td>
      <td className="hidden lg:table-cell text-[12px]">{s.district}</td>
      <td>
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-extrabold tabular num-hero text-[var(--color-edify-text)] leading-none">
            {s.ssaScore.toFixed(1)}
          </span>
          <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold uppercase tracking-wide whitespace-nowrap", tone.chip)}>
            {band}
          </span>
        </div>
      </td>
      <td className="text-[11.5px] font-semibold text-[var(--color-edify-text)]">{s.weakArea}</td>
      <td>
        {s.activitiesPending > 0 ? (
          <span className="text-[12px] font-extrabold tabular text-rose-700">{s.activitiesPending}</span>
        ) : (
          <span className="text-[12px] muted">—</span>
        )}
      </td>
      <td className="hidden lg:table-cell text-[11.5px] muted whitespace-nowrap">{s.lastSupport}</td>
      <td>
        {s.scheduledOn ? (
          <div className="leading-tight">
            <div className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-emerald-700 whitespace-nowrap">
              <Calendar size={10} />
              {s.scheduledOn}
            </div>
            {s.scheduledActivity && (
              <div className="text-[10px] muted leading-tight mt-0.5">{s.scheduledActivity}</div>
            )}
          </div>
        ) : (
          <span className="inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide bg-amber-50 text-amber-700">
            Not scheduled
          </span>
        )}
      </td>
      <td className="text-right">
        <div className="inline-flex items-center gap-1">
          {s.scheduledOn ? (
            <>
              <button
                type="button"
                onClick={onSchedule}
                className="inline-flex items-center justify-center h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60 whitespace-nowrap"
                title="Reschedule this activity"
              >
                Reschedule
              </button>
              <Link
                href={`/schools/sch-1`}
                className="inline-flex items-center justify-center h-8 w-8 rounded-md border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/60"
                aria-label="Open school"
              >
                <ArrowRight size={12} />
              </Link>
            </>
          ) : (
            <button
              type="button"
              onClick={onSchedule}
              className="inline-flex items-center justify-center gap-1 h-8 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[11.5px] font-extrabold hover:bg-[var(--color-edify-dark)] whitespace-nowrap"
            >
              Schedule <ArrowRight size={11} />
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
