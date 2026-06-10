import Link from "next/link";
import { AlertOctagon, ClipboardList, CalendarCheck } from "lucide-react";
import { directoryRecords } from "@/lib/school-directory/directory";
import {
  recommendInterventionsForSchool,
  type InterventionRecommendation,
} from "@/lib/planning/intervention-recommendation";
import type { EdifyRole } from "@/lib/auth-public";

// CoachingRadar — the CCEO dashboard's "which school, why, what next"
// sections (spec §5 B–D): Red Alert Schools, Schools Needing SSA, and
// Recommended Visits & Trainings. Every row is an action card: plain
// title, school name, the reason, and ONE main button. All three cards
// read the same truth — the viewer's directory portfolio ranked by the
// canonical SSA recommendation engine — so the dashboard, directory,
// and planner can never disagree about who needs support.

type RadarRow = {
  schoolId: string;
  schoolName: string;
  district: string;
  rec: InterventionRecommendation;
};

function radarData(staffId: string, role: EdifyRole) {
  const portfolio = directoryRecords(staffId, role);

  const missingSsa: { schoolId: string; schoolName: string; district: string; planningLocked: boolean }[] = [];
  const redAlerts: RadarRow[] = [];
  const recommended: RadarRow[] = [];

  for (const s of portfolio) {
    const r = recommendInterventionsForSchool(s.schoolId);
    if (!r.hasSsa) {
      missingSsa.push({
        schoolId: s.schoolId,
        schoolName: s.schoolName,
        district: s.district,
        planningLocked: s.planningLocked,
      });
      continue;
    }
    const weakest = r.all[0];
    if (!weakest) continue;
    const row = { schoolId: s.schoolId, schoolName: s.schoolName, district: s.district, rec: weakest };
    if (weakest.severity === "Critical") redAlerts.push(row);
    else if (weakest.severity === "Needs Support") recommended.push(row);
  }

  redAlerts.sort((a, b) => a.rec.score - b.rec.score);
  recommended.sort((a, b) => a.rec.score - b.rec.score);
  return { missingSsa, redAlerts, recommended };
}

function ActionRow({
  title,
  reason,
  cta,
  href,
}: {
  title: string;
  reason: string;
  cta: string;
  href: string;
}) {
  return (
    <li className="flex items-start justify-between gap-3 rounded-xl border border-[var(--color-edify-border)] px-3 py-2.5">
      <div className="min-w-0">
        <div className="text-[13px] font-bold text-[var(--color-edify-text)] leading-snug">{title}</div>
        <div className="muted text-[11.5px] mt-0.5 leading-snug">{reason}</div>
      </div>
      <Link
        href={href}
        className="shrink-0 inline-flex items-center h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold hover:opacity-90 transition-opacity"
      >
        {cta}
      </Link>
    </li>
  );
}

function RadarCard({
  title,
  Icon,
  iconClass,
  countLabel,
  children,
  viewAllHref,
  viewAllLabel,
}: {
  title: string;
  Icon: typeof AlertOctagon;
  iconClass: string;
  countLabel: string;
  children: React.ReactNode;
  viewAllHref: string;
  viewAllLabel: string;
}) {
  return (
    <div className="card rounded-2xl p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)] flex items-center gap-2">
          <Icon className={`h-4 w-4 ${iconClass}`} />
          {title}
        </h3>
        <span className="muted text-[11.5px] font-semibold">{countLabel}</span>
      </div>
      {children}
      <Link
        href={viewAllHref}
        className="block text-[12px] font-bold text-[var(--color-edify-primary)] hover:underline"
      >
        {viewAllLabel} →
      </Link>
    </div>
  );
}

/** Section B — schools whose weakest intervention is Critical. */
export function RedAlertSchoolsCard({ staffId, role }: { staffId: string; role: EdifyRole }) {
  const { redAlerts } = radarData(staffId, role);
  if (redAlerts.length === 0) {
    return (
      <div className="card rounded-2xl p-4">
        <h3 className="text-[16px] font-extrabold tracking-tight flex items-center gap-2">
          <AlertOctagon className="h-4 w-4 text-emerald-500" />
          Red alert schools
        </h3>
        <p className="muted text-[12px] mt-2">
          No school in your portfolio is on red alert. Keep coaching — the radar updates with every SSA.
        </p>
      </div>
    );
  }
  return (
    <RadarCard
      title="Red alert schools"
      Icon={AlertOctagon}
      iconClass="text-rose-500"
      countLabel={`${redAlerts.length} need urgent support`}
      viewAllHref="/schools"
      viewAllLabel="All schools"
    >
      <ul className="space-y-2">
        {redAlerts.slice(0, 4).map((r) => (
          <ActionRow
            key={r.schoolId}
            title={`${r.schoolName} needs ${r.rec.recommendedActivity.toLowerCase()} support`}
            reason={`${r.rec.intervention} is ${r.rec.score.toFixed(1)}/10 (${r.rec.severity}). ${r.rec.reason}`}
            cta={r.rec.delivery === "partner" ? "Assign support" : `Schedule ${r.rec.recommendedActivity}`}
            href={`/schools/${encodeURIComponent(r.schoolId)}?view=plan`}
          />
        ))}
      </ul>
    </RadarCard>
  );
}

/** Section C — schools with no scored SSA this cycle (planning locked). */
export function SsaNeededCard({ staffId, role }: { staffId: string; role: EdifyRole }) {
  const { missingSsa } = radarData(staffId, role);
  if (missingSsa.length === 0) {
    return (
      <div className="card rounded-2xl p-4">
        <h3 className="text-[16px] font-extrabold tracking-tight flex items-center gap-2">
          <ClipboardList className="h-4 w-4 text-emerald-500" />
          Schools needing SSA
        </h3>
        <p className="muted text-[12px] mt-2">
          Every school in your portfolio has a current-cycle SSA. Recommendations are live.
        </p>
      </div>
    );
  }
  return (
    <RadarCard
      title="Schools needing SSA"
      Icon={ClipboardList}
      iconClass="text-amber-500"
      countLabel={`${missingSsa.length} missing this cycle`}
      viewAllHref="/planning"
      viewAllLabel="Open planning"
    >
      <ul className="space-y-2">
        {missingSsa.slice(0, 4).map((s) => (
          <ActionRow
            key={s.schoolId}
            title={`${s.schoolName} has no current SSA`}
            reason={`${s.district} · without a scored SSA this school stays planning-locked and gets no recommendations.`}
            cta="Schedule SSA"
            href={`/schools/${encodeURIComponent(s.schoolId)}?view=plan`}
          />
        ))}
      </ul>
    </RadarCard>
  );
}

/** Section D — the next visits & trainings the SSA engine recommends. */
export function RecommendedActionsCard({ staffId, role }: { staffId: string; role: EdifyRole }) {
  const { recommended } = radarData(staffId, role);
  if (recommended.length === 0) {
    return (
      <div className="card rounded-2xl p-4">
        <h3 className="text-[16px] font-extrabold tracking-tight flex items-center gap-2">
          <CalendarCheck className="h-4 w-4 text-emerald-500" />
          Recommended visits & trainings
        </h3>
        <p className="muted text-[12px] mt-2">
          Nothing outstanding — schools below Good surface here with a ready-to-schedule recommendation.
        </p>
      </div>
    );
  }
  return (
    <RadarCard
      title="Recommended visits & trainings"
      Icon={CalendarCheck}
      iconClass="text-[var(--color-edify-primary)]"
      countLabel={`${recommended.length} ready to schedule`}
      viewAllHref="/planning"
      viewAllLabel="Plan all in Planning"
    >
      <ul className="space-y-2">
        {recommended.slice(0, 4).map((r) => (
          <ActionRow
            key={r.schoolId}
            title={`${r.rec.recommendedActivity} — ${r.schoolName}`}
            reason={`${r.rec.intervention} at ${r.rec.score.toFixed(1)}/10 · ${
              r.rec.delivery === "partner"
                ? `best delivered by a partner${r.rec.partnerType ? ` (${r.rec.partnerType})` : ""}`
                : "best delivered by you"
            }.`}
            cta="Schedule"
            href={`/schools/${encodeURIComponent(r.schoolId)}?view=plan`}
          />
        ))}
      </ul>
    </RadarCard>
  );
}
