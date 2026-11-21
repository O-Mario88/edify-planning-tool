'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useTransition } from 'react';

export function RefreshInbox() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  useEffect(() => {
    if (pending) return;
    const refresh = () => {
      if (document.visibilityState === 'visible') startTransition(() => router.refresh());
    };
    const timer = window.setInterval(refresh, 10000);
    document.addEventListener('visibilitychange', refresh);
    window.addEventListener('online', refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
      window.removeEventListener('online', refresh);
    };
  }, [pending, router]);
  return null;
}
