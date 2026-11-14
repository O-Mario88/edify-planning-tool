/**
 * The web build keeps no offline store: a browser tab is not a field
 * device, and nothing here survives a reload. Captures sync at once.
 */
import { memoryStore } from './memoryStore';
import type { OfflineStore } from './store';

export async function openSqliteStore(): Promise<OfflineStore> {
  return memoryStore();
}
