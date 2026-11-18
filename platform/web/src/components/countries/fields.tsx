/*
 * The country Admin forms' fields and their one line of feedback: a problem
 * in the danger tone (announced), a done notice in the success tone.
 */
export const LABEL = 'flex flex-col text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)]';
export const FIELD =
  'mt-1 h-10 w-full rounded-[var(--radius-control)] border border-[var(--edify-border)] bg-[var(--edify-surface)] px-3 text-[14px] font-medium text-[var(--edify-text)] focus:border-[var(--brand-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary-soft)] [&:is(textarea)]:h-auto [&:is(textarea)]:py-2';
export const HINT = 'mt-1 text-[12.5px] font-medium text-[var(--edify-text-muted)]';

export function NoticeLine({ problem, notice }: { problem: string; notice: string }) {
  if (problem) {
    return (
      <p role="alert" className="whitespace-pre-line text-[13px] font-semibold text-[#be123c] dark:text-[var(--edify-danger)]">
        {problem}
      </p>
    );
  }
  if (notice) {
    return (
      <p role="status" className="text-[13px] font-semibold text-[#047857] dark:text-[var(--edify-success)]">
        {notice}
      </p>
    );
  }
  return null;
}
