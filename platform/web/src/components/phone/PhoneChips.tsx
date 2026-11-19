'use client';

/*
 * A chip filter inside a card that switches between parts (the Dashboard's
 * This Week: All Categories, School Visits, Trainings, Cluster Meetings),
 * drawn as the card's own segment switch so it reads as part of that card
 * rather than the existing web's tab rail. It filters as FeedChips does.
 */
import type { PageChips } from '@/gen/edify/screens/v1/page_pb';
import { useChipFilter } from '@/components/page/FeedChips';

export function PhoneChips({ chips }: { chips: PageChips }) {
  const { value, setValue, rail } = useChipFilter(chips);
  return (
    <div ref={rail} data-ph="chips-area" data-block="chips">
      <div data-ph="switch" role="group" aria-label={chips.label || 'Filter'}>
        {chips.chips.map((chip) => (
          <button key={chip.value} type="button" data-ph="seg" aria-pressed={chip.value === value} onClick={() => setValue(chip.value)}>
            {chip.label}
            {chip.count ? <span data-ph="count">{chip.count}</span> : null}
          </button>
        ))}
      </div>
    </div>
  );
}
