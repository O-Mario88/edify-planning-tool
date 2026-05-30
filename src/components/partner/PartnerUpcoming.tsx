// PartnerUpcoming — the calendar-grouped activity strip under
// "Upcoming Trainings & Visits". Four columns (Today / Tomorrow /
// This Week / Later) each render the upcoming items in that window
// with a primary CTA per card.

import Link from "next/link";
import { ArrowRight, Calendar, GraduationCap, Footprints, FileText, Truck } from "lucide-react";
import type {
  PartnerUpcomingItem,
  UpcomingBucketKey,
} from "@/lib/partner/partner-dashboard-mock";

const BUCKETS: UpcomingBucketKey[] = ["today", "tomorrow", "thisWeek", "later"];

const BUCKET_LABEL: Record<UpcomingBucketKey, string> = {
  today:    "Today",
  tomorrow: "Tomorrow",
  thisWeek: "This Week",
  later:    "Later",
};

// Activity → icon element. Returning JSX directly (rather than the
// component reference) keeps the React Compiler happy: assigning a
// component to a capitalized local and rendering it as JSX flags
// `cannot-create-components-during-render`.
function iconForActivity(activity: string, size = 14) {
  if (/training|debrief/i.test(activity))  return <GraduationCap size={size} />;
  if (/visit/i.test(activity))             return <Footprints size={size} />;
  if (/report/i.test(activity))            return <FileText size={size} />;
  if (/delivery|resource/i.test(activity)) return <Truck size={size} />;
  return <Calendar size={size} />;
}

export function PartnerUpcoming({ items }: { items: PartnerUpcomingItem[] }) {
  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-[15px] font-extrabold tracking-tight">Upcoming Trainings & Visits</h2>
          <p className="text-[12px] muted mt-0.5">Your upcoming partner activities from the Planning Tool.</p>
        </div>
        <Link
          href="#calendar"
          className="text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline inline-flex items-center gap-1"
        >
          View Full Calendar <ArrowRight size={11} />
        </Link>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {BUCKETS.map((bucket) => {
          const bucketItems = items.filter((i) => i.bucket === bucket);
          const headerLabel = bucketItems[0]?.bucketLabel ?? BUCKET_LABEL[bucket];
          return (
            <div key={bucket} className="flex flex-col gap-2.5">
              <div className="text-[11.5px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
                {headerLabel}
              </div>
              {bucketItems.length === 0 ? (
                <div className="card p-3.5 text-center text-[11.5px] muted italic">
                  Nothing scheduled.
                </div>
              ) : (
                bucketItems.map((item) => <UpcomingCard key={item.id} item={item} />)
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function UpcomingCard({ item }: { item: PartnerUpcomingItem }) {
  return (
    <article className="card p-3.5">
      <header className="flex items-start gap-2.5">
        <span className="grid place-items-center h-8 w-8 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          {iconForActivity(item.activity)}
        </span>
        <div className="min-w-0">
          <h3 className="text-body font-extrabold tracking-tight leading-tight">{item.activity}</h3>
          <p className="text-[11px] muted leading-tight mt-0.5">{item.activitySub}</p>
        </div>
      </header>

      <div className="mt-2.5 space-y-0.5 text-[11.5px]">
        <div className="font-semibold text-[var(--color-edify-text)]">{item.school}</div>
        {item.district && <div className="muted">{item.district}</div>}
        <div className="muted">Time: {item.time}</div>
        <div className="muted">Facilitator: {item.facilitator}</div>
      </div>

      <button
        type="button"
        className="mt-3 w-full inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60 transition-colors"
      >
        {item.ctaLabel}
      </button>
    </article>
  );
}
