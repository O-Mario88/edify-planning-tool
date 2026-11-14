/*
 * The Smart Route Planner's cards, drawn from the routes contract. Every
 * figure says what it is: a road figure is the provider's; a straight line
 * is labelled so.
 */
import type { ReactNode } from 'react';

import type { Itinerary, ItineraryStop, SchoolPin, Suggestion } from '@/gen/edify/routes/v1/routes_pb';
import { fieldSeconds, hoursMinutes, km, legFigures, measureLabel, pinTone, totalFigures } from '@/lib/routePlanner';

import { TONES } from './RouteMap';
import { RouteIcon } from './RouteIcons';
import type { RouteIconName } from './RouteIcons';

const card = 'rounded-[16px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] shadow-[0_1px_2px_rgba(15,23,42,0.04)]';

function Kpi({ icon, tint, value, label, aside }: { icon: RouteIconName; tint: string; value: string; label: string; aside?: ReactNode }) {
  return (
    <div className={`${card} flex items-center gap-3 px-3 py-3 sm:gap-4 sm:px-5 sm:py-4`}>
      <span className="hidden h-12 w-12 shrink-0 place-items-center rounded-[12px] sm:grid" style={{ background: `${tint}1a`, color: tint }}>
        <RouteIcon name={icon} className="h-7 w-7" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="whitespace-nowrap text-[18px] font-bold leading-tight text-[var(--edify-text)] sm:text-[22px]">{value}</p>
        <p className="text-[13px] text-[var(--edify-text-muted)] sm:text-[14px]">{label}</p>
      </div>
      {aside}
    </div>
  );
}

function InfoDot({ text }: { text: string }) {
  return (
    <span className="cursor-help text-slate-400" title={text} aria-label={text} role="img">
      <RouteIcon name="info" className="h-5 w-5" />
    </span>
  );
}

/** The four figures over the page. */
export function KpiRow({ itinerary }: { itinerary: Itinerary | undefined }) {
  const total = totalFigures(itinerary?.totals);
  const schools = itinerary?.totals?.selected ?? 0;
  const fits = (itinerary?.conflicts.length ?? 0) === 0 && schools > 0;
  const measure = measureLabel(total.measure);
  return (
    <section className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4" aria-label="Field day figures">
      <Kpi
        icon="school"
        tint="#1d6fe0"
        value={`${schools} School${schools === 1 ? '' : 's'}`}
        label="Selected for today"
        aside={fits ? <RouteIcon name="check" className="h-7 w-7 rounded-full bg-green-600 p-1 text-white" /> : null}
      />
      <Kpi icon="route" tint="#1d6fe0" value={km(total.meters)} label="Total Distance" aside={<InfoDot text={measure} />} />
      <Kpi
        icon="clock"
        tint="#1d6fe0"
        value={hoursMinutes(total.seconds)}
        label="Total Travel Time"
        aside={<InfoDot text={total.measure === 'road' ? 'Estimated road travel time' : 'Planning estimate over straight lines; road times are unavailable'} />}
      />
      <Kpi
        icon="calendarCheck"
        tint="#16a34a"
        value={hoursMinutes(fieldSeconds(itinerary))}
        label="Total Field Time"
        aside={<InfoDot text="Travel plus the time at each school" />}
      />
    </section>
  );
}

function stopFigures(stop: ItineraryStop): string {
  const f = legFigures(stop.leg);
  if (!f) return 'First stop';
  return `${km(f.meters)} • ${hoursMinutes(f.seconds)}${f.measure === 'straight_line' ? ' (straight line)' : ''}`;
}

function StopNumber({ stop }: { stop: ItineraryStop }) {
  const tone = pinTone(stop.school!, stop.kind);
  return (
    <span className="relative z-10 grid h-9 w-9 shrink-0 place-items-center rounded-full text-[14px] font-bold text-white ring-4 ring-[var(--edify-card-surface)]" style={{ background: TONES[tone] }}>
      {stop.order}
    </span>
  );
}

/** Recommended Route: the stops in order with their legs and arrival times. */
export function RouteList({ itinerary, onFocus }: { itinerary: Itinerary | undefined; onFocus: (pin: SchoolPin) => void }) {
  const stops = itinerary?.stops ?? [];
  if (stops.length === 0) {
    return <p className="px-6 py-8 text-center text-[var(--edify-text-muted)]">No school visits are planned on this day. Choose another date, or add a nearby school.</p>;
  }
  return (
    <ol className="relative px-5" aria-label="Visit order">
      <span className="absolute bottom-8 left-[37px] top-8 w-0.5 bg-[var(--edify-border)]" aria-hidden="true" />
      {stops.map((stop) => (
        <li key={stop.school?.schoolId} className="relative flex items-start gap-4 border-b border-[var(--edify-border)] py-3.5 last:border-b-0">
          <StopNumber stop={stop} />
          <button type="button" onClick={() => stop.school && onFocus(stop.school)} className="min-w-0 flex-1 text-left">
            <span className="flex flex-wrap items-center gap-x-2 text-[16px] font-semibold leading-snug text-[var(--edify-text)]">
              {stop.school?.name}
              {stop.kind === 'recommended' ? <span className="rounded-full bg-sky-50 px-2 py-0.5 text-[12px] font-semibold text-sky-700">Suggested</span> : null}
              {stop.school?.status === 'completed' ? <span className="rounded-full bg-green-600 px-2 py-0.5 text-[12px] font-semibold text-white">Completed</span> : null}
            </span>
            <span className="mt-0.5 block text-[14px] text-[var(--edify-text-muted)]">
              {stopFigures(stop)}
              <span className="ml-2 text-[13px]">ID {stop.school?.code}</span>
            </span>
            {stop.conflict ? <span className="mt-1 block text-[14px] font-medium text-[var(--edify-danger-text)]">{stop.conflict}</span> : null}
          </button>
          <span className="shrink-0 pt-1 text-[14px] text-[var(--edify-text)]">Arr. {stop.arrival}</span>
        </li>
      ))}
    </ol>
  );
}

function SummaryFigure({ icon, value, label }: { icon: RouteIconName; value: string; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <RouteIcon name={icon} className="h-8 w-8 text-slate-700" />
      <div>
        <p className="text-[16px] font-semibold text-[var(--edify-text)]">{value}</p>
        <p className="text-[13px] text-[var(--edify-text-muted)] sm:text-[14px]">{label}</p>
      </div>
    </div>
  );
}

/** Route Summary: distance, travel and the whole field day. */
export function RouteSummary({ itinerary }: { itinerary: Itinerary | undefined }) {
  const total = totalFigures(itinerary?.totals);
  return (
    <div className="border-t border-[var(--edify-border)] px-6 pt-5">
      <h3 className="text-[17px] font-semibold text-[var(--edify-text)]">Route Summary</h3>
      <div className="mt-4 grid grid-cols-3 gap-2">
        <SummaryFigure icon="road" value={km(total.meters)} label="Total Distance" />
        <SummaryFigure icon="clock" value={hoursMinutes(total.seconds)} label="Travel Time" />
        <SummaryFigure icon="hourglass" value={hoursMinutes(fieldSeconds(itinerary))} label="Total Time" />
      </div>
      <p className="mt-3 text-[13px] text-[var(--edify-text-muted)]">
        {measureLabel(total.measure)}
        {itinerary?.explanation ? ` · ${itinerary.explanation}` : ''}
      </p>
    </div>
  );
}

/** Schools Near Your Route: eligible schools, what each adds, and why. */
export function NearbyCard({
  suggestions,
  onAdd,
  onFocus,
  onViewAll,
  showAll,
  inRoute,
  around,
}: {
  suggestions: readonly Suggestion[];
  onAdd: (s: Suggestion) => string;
  onFocus: (pin: SchoolPin) => void;
  onViewAll: () => void;
  showAll: boolean;
  /** Schools already in the shown route (a suggestion only, until scheduled). */
  inRoute: ReadonlySet<string>;
  /** The school the list is around (Find Nearby Schools), if any. */
  around?: SchoolPin;
}) {
  const shown = showAll ? suggestions : suggestions.slice(0, 1);
  return (
    <section className={`${card} p-5`} aria-labelledby="near-route-title">
      <header className="flex items-center justify-between gap-3">
        <h2 id="near-route-title" className="flex items-center gap-3 text-[19px] font-semibold text-[var(--edify-text)]">
          <RouteIcon name="bulb" className="h-7 w-7 text-amber-400" />
          {around ? `Schools Near ${around.name}` : 'Schools Near Your Route'}
        </h2>
        {suggestions.length > 1 ? (
          <button type="button" onClick={onViewAll} className="flex items-center gap-2 text-[15px] font-semibold text-[#1d6fe0]">
            {showAll ? 'Show fewer' : 'View All'} <RouteIcon name="arrowRight" className="h-5 w-5" />
          </button>
        ) : null}
      </header>
      {shown.length === 0 ? (
        <p className="mt-4 text-[var(--edify-text-muted)]">{around ? 'No eligible schools near this school.' : 'No eligible schools near this route.'}</p>
      ) : (
        <ul className="mt-4 space-y-3">
          {shown.map((s) => (
            <li key={s.school?.schoolId} className="flex flex-wrap items-center gap-4 rounded-[14px] border border-[var(--edify-border)] p-3">
              <button
                type="button"
                onClick={() => s.school && onFocus(s.school)}
                className="grid h-[84px] w-[132px] shrink-0 place-items-center rounded-[10px] bg-gradient-to-br from-blue-100 to-sky-100 text-[#1d6fe0]"
                aria-label={`Show ${s.school?.name} on the map`}
              >
                <RouteIcon name="school" className="h-10 w-10" />
              </button>
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 text-[16px] font-semibold text-[var(--edify-text)]">
                  {s.school?.name}
                  <span className="text-[13px] font-normal text-[var(--edify-text-muted)]">ID {s.school?.code}</span>
                  <span className={`rounded-full px-3 py-0.5 text-[13px] font-semibold ${s.label === 'High Priority' ? 'bg-violet-50 text-violet-700' : 'bg-green-50 text-green-700'}`}>
                    {s.label}
                  </span>
                </p>
                <p className="mt-1 text-[14px] text-[var(--edify-text-muted)]">
                  {around
                    ? `${km(s.addedMeters)} away • ${hoursMinutes(s.addedSeconds)}`
                    : `${Number(s.addedMeters) < 100 ? 'On the way' : `+${km(s.addedMeters)}`} • +${hoursMinutes(s.addedSeconds)}`}
                  {s.measure === 'straight_line' ? ' (straight line)' : ''}
                  <span className="mx-2 text-slate-300">|</span>
                  {s.label === 'High Priority' ? 'SSA Support Needed' : 'Support visit open'}
                </p>
                <p className="mt-0.5 text-[13px] text-[var(--edify-text-muted)]">
                  {s.reason}
                  {s.school && inRoute.has(s.school.schoolId) ? ' In your recommended route as a suggestion; Add to Plan schedules it.' : ''}
                </p>
              </div>
              <a
                href={onAdd(s)}
                className="inline-flex h-12 shrink-0 items-center rounded-[10px] border-2 border-[#1d6fe0] px-6 text-[15px] font-semibold text-[#1d6fe0] hover:bg-blue-50"
              >
                Add to Plan
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** "Great route!", or what does not fit. */
export function DayVerdict({ itinerary }: { itinerary: Itinerary | undefined }) {
  const stops = itinerary?.stops.length ?? 0;
  if (stops === 0) return null;
  const conflicts = itinerary?.conflicts ?? [];
  if (conflicts.length > 0) {
    return (
      <section className="rounded-[16px] border-2 border-amber-300 bg-amber-50 p-6" aria-live="polite">
        <p className="flex items-center gap-3 text-[17px] font-semibold text-amber-900">
          <RouteIcon name="alert" className="h-7 w-7" /> This day does not fit
        </p>
        <ul className="mt-2 list-disc pl-6 text-[14px] text-amber-900">
          {conflicts.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
        <p className="mt-2 text-[14px] text-amber-900">Move a visit to another day, or remove a suggested school.</p>
      </section>
    );
  }
  return (
    <section className="flex items-center gap-5 rounded-[16px] border-2 border-green-300 bg-green-50 p-6" aria-live="polite">
      <RouteIcon name="check" className="h-14 w-14 shrink-0 rounded-full bg-green-600 p-3 text-white" strokeWidth={2.6} />
      <div className="flex-1">
        <p className="text-[19px] font-semibold text-[var(--edify-text)]">Great route!</p>
        <p className="mt-1 text-[15px] text-[var(--edify-text)]">
          You can visit {stops} school{stops === 1 ? '' : 's'} efficiently in one field day.
        </p>
      </div>
      <RouteIcon name="route" className="hidden h-16 w-16 text-green-600 sm:block" />
    </section>
  );
}

/** Schools with no usable coordinates: listed, never hidden. */
export function UnplacedNote({ itinerary }: { itinerary: Itinerary | undefined }) {
  const unplaced = itinerary?.unplaced ?? [];
  if (unplaced.length === 0) return null;
  return (
    <p className="rounded-[12px] border border-amber-300 bg-amber-50 px-4 py-3 text-[14px] text-amber-900" role="status">
      <strong>{unplaced.length} planned school{unplaced.length === 1 ? ' has' : 's have'} no usable coordinates</strong> and
      {unplaced.length === 1 ? ' is' : ' are'} not on the map: {unplaced.map((p) => `${p.name} (${p.locationStatus === 'invalid' ? 'location looks wrong' : 'no location'})`).join(', ')}.
      They stay on your plan.
    </p>
  );
}
