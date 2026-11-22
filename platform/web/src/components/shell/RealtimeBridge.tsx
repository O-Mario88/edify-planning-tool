'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useRef } from 'react';

/**
 * Connects to the authenticated SSE stream (/api/realtime), dispatches
 * `edify:realtime` events for client widgets, and triggers a debounced
 * Next.js router.refresh() when committed operational updates arrive so
 * users see live changes without manual page refreshes.
 */
export function RealtimeBridge() {
  const router = useRouter();
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (typeof EventSource === 'undefined') return;
    const source = new EventSource('/api/realtime');

    const handleEvent = (raw: MessageEvent<string>) => {
      try {
        const detail = JSON.parse(raw.data) as Record<string, unknown>;
        window.dispatchEvent(new CustomEvent('edify:realtime', { detail }));
      } catch {
        // Ignore non-JSON keepalive payloads.
      }
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        router.refresh();
      }, 350);
    };

    const eventTypes = [
      'escalation.raised',
      'escalation.resolved',
      'leave.requested',
      'leave.decided',
      'finance.weekly_request.submit',
      'finance.weekly_request.disburse',
      'finance.advance.disburse',
      'message.sent',
      'activity.updated',
    ];
    for (const t of eventTypes) {
      source.addEventListener(t, handleEvent as EventListener);
    }

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      source.close();
    };
  }, [router]);

  return null;
}
