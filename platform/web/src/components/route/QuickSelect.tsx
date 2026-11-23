'use client';

/*
 * A phone's small district or cluster field. The native select lies invisibly
 * over the short label, keeping the 16px text that stops a phone zooming in.
 */
import { ChevronDown } from 'lucide-react';

interface QuickSelectProps {
  readonly label: string;
  readonly value: string;
  readonly allWords: string;
  readonly options: readonly { readonly value: string; readonly label: string }[];
  readonly onChange: (value: string) => void;
}

export function QuickSelect({ label, value, allWords, options, onChange }: QuickSelectProps) {
  const shown = options.find((option) => option.value === value)?.label ?? allWords;
  return (
    <span className="sr-quick-select" title={shown}>
      <span aria-hidden="true">{shown}</span>
      <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{allWords}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </span>
  );
}
