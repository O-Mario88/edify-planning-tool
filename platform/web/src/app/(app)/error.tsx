'use client';

/*
 * What a page shows when it could not be drawn (the gateway did not answer,
 * or a part of the page failed): a quiet card in the page's place, inside the
 * shell, saying what happened in plain words, with Try again and Home, and the
 * reference support can look up. Never the framework's bare error screen
 * (design pass 2026-11-20: empty and error states).
 */
import { AlertTriangle } from 'lucide-react';
import Link from 'next/link';
import { useEffect } from 'react';

import { BUTTON_OUTLINE, BUTTON_PRIMARY } from '@/components/blocks/buttons';

export default function PageError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // The server logged the cause under the digest; the browser keeps a note for support.
    console.error('page failed', error.digest ?? error.message);
  }, [error]);
  return (
    <div className="mx-auto max-w-[1500px] px-4 pt-5 sm:px-6" data-block="page-error">
      <section role="alert" className="card mx-auto flex max-w-xl flex-col items-center gap-3 px-6 py-10 text-center">
        <span className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--edify-warning-soft,var(--edify-surface-muted))] text-[var(--edify-warning-text)]">
          <AlertTriangle className="h-5 w-5" aria-hidden="true" />
        </span>
        <h1 className="text-[length:var(--edify-text-title-size)] font-bold">This page could not be loaded</h1>
        <p className="edify-text-caption edify-text-muted">
          Nothing you entered was lost. Try again in a moment; if it keeps happening, report it with the reference below.
        </p>
        <div className="mt-1 flex flex-wrap justify-center gap-2">
          <button type="button" className={BUTTON_PRIMARY} onClick={() => reset()}>
            Try again
          </button>
          <Link href="/home" className={BUTTON_OUTLINE}>
            Go to Home
          </Link>
        </div>
        {error.digest ? <p className="edify-text-caption edify-text-muted">Reference: {error.digest}</p> : null}
      </section>
    </div>
  );
}
