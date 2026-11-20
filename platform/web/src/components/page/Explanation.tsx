/*
 * A table's explanation (its footnote: how a figure is worked out, what a
 * target means) folded under a chevron, closed until it is opened (owner,
 * 2026-11-20: "hide all the explanations ... using a chevron. they should by
 * default be hidden and only opened by tapping the unhide icon/chevron").
 * A native <details>: it opens by click, tap, Enter or Space and needs no
 * script. `phone` is the phone layer's markup (data-ph, phone.css); the app
 * draws the same fold (PageTableView.tsx).
 */
import { ChevronDown } from 'lucide-react';

import { Icon } from '../shell/icons';

/** What the closed fold says. */
export const EXPLANATION_LABEL = 'Explanation';

interface ExplanationProps {
  readonly text: string;
  /** The phone layer's markup. */
  readonly phone?: boolean;
  /** On a card of its own (a note sent after its table, lib/tableNote): no
   *  line above it. */
  readonly bare?: boolean;
}

export function Explanation({ text, phone = false, bare = false }: ExplanationProps) {
  if (phone) {
    return (
      <details data-ph="explain" data-bare={bare || undefined}>
        <summary data-ph="explain-toggle">
          <ChevronDown aria-hidden="true" size={16} data-ph="explain-chevron" />
          <span>{EXPLANATION_LABEL}</span>
        </summary>
        <p data-ph="footnote">{text}</p>
      </details>
    );
  }
  return (
    <details className={bare ? 'group' : 'group border-t edify-border-top'} data-explanation>
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1.5 px-4 py-2.5 edify-text-caption font-semibold edify-primary-text [&::-webkit-details-marker]:hidden">
        <Icon name="chevronDown" className="h-4 w-4 transition-transform group-open:rotate-180" />
        <span>{EXPLANATION_LABEL}</span>
      </summary>
      <p className="px-4 pb-3 edify-text-caption edify-text-muted">{text}</p>
    </details>
  );
}
