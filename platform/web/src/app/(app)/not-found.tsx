/*
 * A page that does not exist, or one this account cannot open, inside the
 * shell: what happened in plain words and the way back, never the
 * framework's bare 404 (design pass 2026-11-20: empty and error states).
 */
import { Compass } from 'lucide-react';
import Link from 'next/link';

import { BUTTON_OUTLINE, BUTTON_PRIMARY } from '@/components/blocks/buttons';

export default function NotFound() {
  return (
    <div className="mx-auto max-w-[1500px] px-4 pt-5 sm:px-6" data-block="not-found">
      <section className="card mx-auto flex max-w-xl flex-col items-center gap-3 px-6 py-10 text-center">
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--edify-surface-muted)] text-[var(--brand-primary-text)]">
          <Compass className="h-5 w-5" aria-hidden="true" />
        </span>
        <h1 className="text-[length:var(--edify-text-title-size)] font-bold">This page is not here</h1>
        <p className="edify-text-caption edify-text-muted">
          The link may be old, or the page may not be open to your role. Search, or start again from Home.
        </p>
        <div className="mt-1 flex flex-wrap justify-center gap-2">
          <Link href="/home" className={BUTTON_PRIMARY}>
            Go to Home
          </Link>
          <Link href="/schools" className={BUTTON_OUTLINE}>
            Find a school
          </Link>
        </div>
      </section>
    </div>
  );
}
