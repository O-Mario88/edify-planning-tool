/** Fired after a cluster is created or schools are assigned — live directory refetches. */
export const CLUSTERS_UPDATED = "edify:clusters-updated";

export function notifyClustersUpdated() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(CLUSTERS_UPDATED));
  }
}
