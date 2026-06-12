"use client";

// Online/offline detection (spec layer #9). Field staff in Uganda work on weak
// connections — this hook lets any component react to losing/regaining the
// network without each one re-implementing the listeners.

import { useEffect, useState } from "react";

export function useOnline(): boolean {
  // Default true so SSR/first paint doesn't flash an offline banner.
  const [online, setOnline] = useState(true);

  useEffect(() => {
    setOnline(navigator.onLine);
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return online;
}
