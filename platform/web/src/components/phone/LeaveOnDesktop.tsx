'use client';

/*
 * A phone-only page (the menu behind More) leaves when the screen widens
 * past the phone line: on a desktop the sidebar is the menu, and the page
 * would otherwise sit in the body beside it. It goes back to where the reader
 * opened it from, or Home when there is nowhere to go back to. Draws nothing.
 */
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

import { PHONE_QUERY } from '@/lib/viewport';

export function LeaveOnDesktop({ home = '/home' }: { home?: string }) {
  const router = useRouter();
  useEffect(() => {
    const query = window.matchMedia(PHONE_QUERY);
    const leave = () => {
      if (query.matches) return;
      if (window.history.length > 1) router.back();
      else router.replace(home);
    };
    leave();
    query.addEventListener('change', leave);
    return () => query.removeEventListener('change', leave);
  }, [router, home]);
  return null;
}
