'use client';

/*
 * Tells the server which reading this screen wants (lib/viewport): it
 * measures the screen against the existing web's phone line, keeps the
 * answer in a cookie, and redraws the page when it changes (the first visit
 * of a device the hints guessed wrong for, or a window dragged across the
 * line). Draws nothing.
 */
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { PHONE_QUERY, VIEW_COOKIE } from '@/lib/viewport';
import type { View } from '@/lib/viewport';

const A_YEAR = 60 * 60 * 24 * 365;

export function ViewportSync({ served }: { served: View }) {
  const router = useRouter();
  useEffect(() => {
    const query = window.matchMedia(PHONE_QUERY);
    let current: View = served;
    const sync = () => {
      const wanted: View = query.matches ? 'phone' : 'desktop';
      document.cookie = `${VIEW_COOKIE}=${wanted}; path=/; max-age=${A_YEAR}; samesite=lax`;
      if (wanted !== current) {
        current = wanted;
        router.refresh();
      }
    };
    sync();
    query.addEventListener('change', sync);
    return () => query.removeEventListener('change', sync);
  }, [router, served]);
  return null;
}
