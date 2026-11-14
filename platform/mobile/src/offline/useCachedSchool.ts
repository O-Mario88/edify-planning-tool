/**
 * A school as the phone holds it, re-read whenever the offline store
 * changes; null while loading or when it is not among the person's schools.
 */
import { useEffect, useState } from 'react';

import { useOffline } from './OfflineContext';
import type { CachedSchool } from './store';

export function useCachedSchool(ref: string): CachedSchool | null {
  const { store, account, revision } = useOffline();
  const [school, setSchool] = useState<CachedSchool | null>(null);
  useEffect(() => {
    if (!store || !account || !ref) return;
    let isCurrent = true;
    void store.school(account.userId, ref).then((found) => {
      if (isCurrent) setSchool(found);
    });
    return () => {
      isCurrent = false;
    };
  }, [store, account, revision, ref]);
  return school;
}
