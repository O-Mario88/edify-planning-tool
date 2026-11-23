/*
 * The profile pages' tab strip, as the designs draw it: an icon and a word in
 * each segment, straight dividers, curved ends, the open tab filled. On a
 * phone the first tabs stay in the rail and the rest open from More.
 */
import { BookOpen, ChevronDown, ClipboardList, Crown, FileText, FolderKanban, GraduationCap, LayoutGrid, LayoutList, LineChart, School, Target, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';

import type { PageTab } from '@/gen/edify/screens/v1/page_pb';
import { profileTabs } from '@/lib/schoolProfile';

const ICONS: Readonly<Record<string, LucideIcon>> = {
  overview: LayoutGrid,
  ssa: Target,
  activities: ClipboardList,
  academic: GraduationCap,
  stories: BookOpen,
  projects: FolderKanban,
  core: Crown,
  details: FileText,
  schools: School,
  attendance: Users,
  member_activities: LayoutList,
  analytics: LineChart,
};

/** How many tabs a phone keeps in the rail; the open tab always stays there. */
const PHONE_RAIL = 3;

function onPhoneRail(tabs: readonly PageTab[]): ReadonlySet<string> {
  const first = tabs.slice(0, PHONE_RAIL).map((tab) => tab.key);
  const open = tabs.find((tab) => tab.active)?.key;
  if (!open || first.includes(open)) return new Set(first);
  return new Set([...first.slice(0, PHONE_RAIL - 1), open]);
}

interface ProfileTabsProps {
  readonly tabs: readonly PageTab[];
  readonly pagePath: string;
  readonly year: string;
  readonly label: string;
}

export function ProfileTabs({ tabs, pagePath, year, label }: ProfileTabsProps) {
  const links = profileTabs(tabs, pagePath, year).tabs;
  const hrefOf = (index: number) => links[index]?.href ?? pagePath;
  const inRail = onPhoneRail(tabs);
  const openKey = tabs.find((tab) => tab.active)?.key ?? '';
  return (
    <div data-pf="tabs" data-block="tabs" tabIndex={0} role="region" aria-label={`${label}, scrolls sideways`}>
      <div data-pf="tabs-rail">
        <div role="tablist" aria-label={label} data-pf="tabs-list">
          {tabs.map((tab, index) => {
            const TabIcon = ICONS[tab.key] ?? LayoutGrid;
            return (
              <Link key={tab.key} href={hrefOf(index)} role="tab" aria-selected={tab.active} data-pf="tab" data-active={tab.active || undefined} data-phone-more={inRail.has(tab.key) ? undefined : ''}>
                <TabIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{tab.label}</span>
              </Link>
            );
          })}
        </div>
        {tabs.length > inRail.size ? (
          <details key={openKey} data-pf="tabs-more">
            <summary>
              More <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            </summary>
            <div data-pf="tabs-menu">
              {tabs.map((tab, index) => {
                if (inRail.has(tab.key)) return null;
                const TabIcon = ICONS[tab.key] ?? LayoutGrid;
                return (
                  <Link key={tab.key} href={hrefOf(index)}>
                    <TabIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
                    {tab.label}
                  </Link>
                );
              })}
            </div>
          </details>
        ) : null}
      </div>
    </div>
  );
}
