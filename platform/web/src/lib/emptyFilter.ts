/**
 * The existing web hides a filter that offers nothing to choose
 * (static/js/micro-ux.js `hideEmptyFilters`): fewer than two options and no
 * value applied ('', 'all' or 'All' is none). It still sends its value.
 */
export function isEmptyFilter(filter: { readonly value: string; readonly options: readonly unknown[] }): boolean {
  const applied = Boolean(filter.value) && filter.value !== 'all' && filter.value !== 'All';
  return filter.options.length < 2 && !applied;
}
