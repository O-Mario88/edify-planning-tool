/*
 * Shared 3-column SSA intervention breakdown matching the Edify SSA detail
 * presentation:
 *   - Eyebrow: "SSA DETAIL"
 *   - Heading: "Intervention scores" (left) + assessment/FY caption (right)
 *   - 3 underlined columns on wide viewports (stacked on phone):
 *       1. SSA interventions needing urgent attention (red, < 5.0)
 *       2. SSA interventions performing well (green, >= 7.0)
 *       3. SSA interventions to watch (amber, 5.0..6.9)
 * Preserves real zero scores (0/10) and renders a clear empty state when no
 * confirmed SSA assessment exists for the record.
 */
import type { DirectorySsaGroup } from '@/gen/edify/screens/v1/school_directory_pb';
import type { PagePanel } from '@/gen/edify/screens/v1/page_pb';

export interface SsaScoreEntry {
  readonly label: string;
  readonly scoreText: string;
}

export interface SsaGroupColumn {
  readonly key: 'urgent' | 'performing-well' | 'warning';
  readonly title: string;
  readonly items: readonly SsaScoreEntry[];
}

export interface SsaDetailModel {
  readonly eyebrow: string;
  readonly title: string;
  readonly caption: string;
  readonly hasScores: boolean;
  readonly emptyMessage: string;
  readonly columns: readonly SsaGroupColumn[];
}

const DEFAULT_COLUMNS: readonly { key: SsaGroupColumn['key']; title: string }[] = [
  { key: 'urgent', title: 'SSA interventions needing urgent attention' },
  { key: 'performing-well', title: 'SSA interventions performing well' },
  { key: 'warning', title: 'SSA interventions to watch' },
];

const EMPTY_GROUP_LINE = 'No confirmed scores in this group.';
const EMPTY_RECORD_LINE = 'No confirmed SSA scores are available yet.';

function formatScore(score: number): string {
  const fixed = score.toFixed(1);
  return fixed.endsWith('.0') ? fixed.slice(0, -2) : fixed;
}

function classifyHeading(heading: string): SsaGroupColumn['key'] {
  const lower = heading.toLowerCase();
  if (lower.includes('urgent') || lower.includes('critical')) return 'urgent';
  if (lower.includes('performing-well') || lower.includes('performing well') || lower.includes('strong')) return 'performing-well';
  return 'warning';
}

function parseEntryLine(raw: string): SsaScoreEntry | null {
  const text = raw.trim();
  if (!text || text.toLowerCase() === EMPTY_GROUP_LINE.toLowerCase()) return null;
  const match = /^(.*?)(\s*\([^)]+\))$/.exec(text);
  if (match && match[1] !== undefined && match[2] !== undefined) {
    return { label: match[1].trim(), scoreText: match[2].trim() };
  }
  return { label: text, scoreText: '' };
}

/** Detect whether a PagePanel carries SSA intervention scores (from clusterpage, planningpage, coreschools, etc.). */
export function isSsaDetailPanel(panel: PagePanel): boolean {
  const sub = panel.subtitle.trim().toLowerCase();
  const title = panel.title.trim().toLowerCase();
  return sub === 'ssa detail' || title === 'intervention scores';
}

/** Parse a Go PagePanel into the shared 3-column SSA detail model. */
export function ssaModelFromPanel(panel: PagePanel): SsaDetailModel {
  let caption = '';
  let emptyMessage = EMPTY_RECORD_LINE;
  const byKey = new Map<SsaGroupColumn['key'], { title: string; items: SsaScoreEntry[] }>();
  let currentKey: SsaGroupColumn['key'] | null = null;
  let sawAnyHeading = false;

  for (const item of panel.items) {
    if (item.kind.case === 'text') {
      const value = item.kind.value.trim();
      if (!value) continue;
      if (value.toLowerCase().includes('no confirmed ssa')) {
        emptyMessage = value;
      } else if (!caption) {
        caption = value;
      }
    } else if (item.kind.case === 'heading') {
      sawAnyHeading = true;
      const key = classifyHeading(item.kind.value);
      currentKey = key;
      byKey.set(key, { title: item.kind.value, items: [] });
    } else if (item.kind.case === 'links' && currentKey) {
      const bucket = byKey.get(currentKey);
      if (!bucket) continue;
      for (const link of item.kind.value.links) {
        const parsed = parseEntryLine(link.text);
        if (parsed) bucket.items.push(parsed);
      }
    }
  }

  const columns: SsaGroupColumn[] = DEFAULT_COLUMNS.map((col) => {
    const found = byKey.get(col.key);
    return {
      key: col.key,
      title: found?.title || col.title,
      items: found?.items ?? [],
    };
  });
  const totalItems = columns.reduce((acc, c) => acc + c.items.length, 0);
  return {
    eyebrow: (panel.subtitle || 'SSA detail').toUpperCase(),
    title: panel.title || 'Intervention scores',
    caption,
    hasScores: sawAnyHeading && totalItems > 0,
    emptyMessage,
    columns,
  };
}

/** Build the shared 3-column SSA detail model from School Directory's DirectorySsaGroup[]. */
export function ssaModelFromDirectory(
  groups: readonly DirectorySsaGroup[],
  fy: string,
  hasAssessment: boolean,
): SsaDetailModel {
  const byKey = new Map<SsaGroupColumn['key'], { title: string; items: SsaScoreEntry[] }>();
  for (const g of groups) {
    const key = classifyHeading(g.key || g.title);
    byKey.set(key, {
      title: g.title,
      items: g.items.map((item) => ({
        label: item.label,
        scoreText: `(${formatScore(item.score)}/10)`,
      })),
    });
  }
  const columns: SsaGroupColumn[] = DEFAULT_COLUMNS.map((col) => {
    const found = byKey.get(col.key);
    return {
      key: col.key,
      title: found?.title || col.title,
      items: found?.items ?? [],
    };
  });
  const totalItems = columns.reduce((acc, c) => acc + c.items.length, 0);
  return {
    eyebrow: 'SSA DETAIL',
    title: 'Intervention scores',
    caption: fy ? `Latest confirmed assessment · FY ${fy}` : 'Latest confirmed assessment',
    hasScores: hasAssessment && totalItems > 0,
    emptyMessage: EMPTY_RECORD_LINE,
    columns,
  };
}

const COLUMN_STYLES: Readonly<
  Record<SsaGroupColumn['key'], { bullet: string; label: string; score: string }>
> = {
  urgent: {
    bullet: 'text-[#dc2626] dark:text-[#f87171]',
    label: 'text-[#b91c1c] dark:text-[#fca5a5]',
    score: 'text-[#dc2626] dark:text-[#f87171]',
  },
  'performing-well': {
    bullet: 'text-[#15803d] dark:text-[#4ade80]',
    label: 'text-[#166534] dark:text-[#86efac]',
    score: 'text-[#16a34a] dark:text-[#4ade80]',
  },
  warning: {
    bullet: 'text-[#b45309] dark:text-[#fbbf24]',
    label: 'text-[#92400e] dark:text-[#fde68a]',
    score: 'text-[#d97706] dark:text-[#fbbf24]',
  },
};

export function SsaDetailPanel({ model }: { readonly model: SsaDetailModel }) {
  return (
    <section data-block="ssa-detail" aria-label={model.title} className="pt-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-[var(--edify-table-divider)] pb-2.5">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.06em] text-[var(--brand-primary-text)] dark:text-[var(--edify-accent-text)]">
            {model.eyebrow}
          </p>
          <h3 className="mt-0.5 text-[15px] font-bold text-[var(--edify-text)]">{model.title}</h3>
        </div>
        {model.caption ? (
          <p className="text-[12px] font-semibold text-[var(--edify-text-muted)]">{model.caption}</p>
        ) : null}
      </div>
      {model.hasScores ? (
        <div className="mt-3 grid grid-cols-1 gap-x-8 gap-y-4 md:grid-cols-3">
          {model.columns.map((col) => {
            const tone = COLUMN_STYLES[col.key];
            return (
              <div key={col.key} data-ssa-group={col.key} className="min-w-0">
                <h4 className="inline-block border-b-2 border-[var(--brand-primary-text)] pb-0.5 text-[13px] font-bold text-[var(--brand-primary-text)] dark:border-[var(--edify-accent-text)] dark:text-[var(--edify-accent-text)]">
                  {col.title}
                </h4>
                {col.items.length > 0 ? (
                  <ul className="mt-2 space-y-1.5">
                    {col.items.map((entry) => (
                      <li key={entry.label} className="flex items-baseline gap-1.5 text-[13px] leading-snug">
                        <span aria-hidden="true" className={`shrink-0 font-bold ${tone.bullet}`}>
                          •
                        </span>
                        <span className="min-w-0">
                          <span className={`font-bold ${tone.label}`}>{entry.label}</span>
                          {entry.scoreText ? (
                            <span className={`ml-1 font-medium tabular-nums ${tone.score}`}>{entry.scoreText}</span>
                          ) : null}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-[12px] text-[var(--edify-text-muted)]">{EMPTY_GROUP_LINE}</p>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <p data-ssa-empty="" className="mt-3 text-[13px] font-medium text-[var(--edify-text-muted)]">
          {model.emptyMessage}
        </p>
      )}
    </section>
  );
}
