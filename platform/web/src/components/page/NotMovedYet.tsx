/*
 * A page (or a reader's version of a page) that has not moved to this web
 * app yet says so and opens the same page of the existing web, rather than
 * drawing something that looks finished and is not.
 */
export function NotMovedYet({ href }: { href: string }) {
  return (
    <div className="mx-auto max-w-[1500px] px-4 pt-5 sm:px-6" data-block="not-moved">
      <div className="rounded-[10px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] p-6">
        <h1 className="text-[length:var(--edify-text-title-size)] font-bold">This page has not moved to the new web app yet</h1>
        <p className="mt-1 text-[var(--edify-text-muted)]">It still opens in the existing web app, with the same workflow.</p>
        <a href={href} className="mt-4 inline-flex h-10 items-center rounded-[var(--radius-control)] bg-[var(--edify-accent)] px-4 font-semibold text-white">
          Open it in the existing web app
        </a>
      </div>
    </div>
  );
}
