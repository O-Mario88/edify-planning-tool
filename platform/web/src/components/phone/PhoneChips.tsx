'use client';

/*
 * A chip filter on a phone (To-Do's categories and priorities; inside the
 * Dashboard's This Week card its kinds of plan), as the app draws chips
 * (PageChipsView.tsx): a rail that never scrolls, with the first chip and
 * the chosen one on it and the rest under "More n". It filters as FeedChips
 * does.
 */
import type { PageChip, PageChips } from '@/gen/edify/screens/v1/page_pb';
import { useChipFilter } from '@/components/page/FeedChips';

import { MorePanel } from './MorePanel';

/** The chips a phone's rail shows: the first and the chosen one (or the second). */
export function railChips(chips: readonly PageChip[], chosen: string): { shown: PageChip[]; rest: PageChip[] } {
  const open = chips.findIndex((chip) => chip.value === chosen);
  const keep = new Set([0, open > 0 ? open : 1]);
  return { shown: chips.filter((_, i) => keep.has(i)), rest: chips.filter((_, i) => !keep.has(i)) };
}

export function PhoneChips({ chips }: { chips: PageChips }) {
  const { value, setValue, rail } = useChipFilter(chips);
  const { shown, rest } = railChips(chips.chips, value);
  return (
    <div ref={rail} data-ph="chips-area" data-block="chips">
      <div data-ph="rail" role="group" aria-label={chips.label || 'Filter'}>
        {shown.map((chip) => (
          <button key={chip.value} type="button" data-ph="seg" aria-pressed={chip.value === value} onClick={() => setValue(chip.value)}>
            {chip.label}
            {chip.count ? ` ${chip.count}` : ''}
          </button>
        ))}
        {rest.length > 0 ? (
          // Keyed by the choice, so choosing from the menu closes it.
          <MorePanel
            key={value}
            look="seg"
            label={`More ${rest.length}, ${chips.label || 'choices'}`}
            words={
              <>
                More <span data-ph="count">{rest.length}</span>
              </>
            }
          >
            {rest.map((chip) => (
              <button key={chip.value} type="button" data-ph="menu-item" role="menuitem" onClick={() => setValue(chip.value)}>
                {chip.label}
                {chip.count ? ` ${chip.count}` : ''}
              </button>
            ))}
          </MorePanel>
        ) : null}
      </div>
    </div>
  );
}
