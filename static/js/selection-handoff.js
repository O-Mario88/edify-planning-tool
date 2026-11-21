document.addEventListener('DOMContentLoaded', function () {
  const selection = new URLSearchParams(location.hash.slice(1)).get('selection');
  if (!selection) return;
  const preview = new URL(selection, location.origin);
  const fields = new Map([
    ['/activity-selection/reschedule', 'ids'],
    ['/activity-selection/cancel', 'ids'],
    ['/planning/bulk-assign-partner-drawer', 'school_ids'],
    ['/planning/bulk-schedule-drawer', 'school_ids'],
    ['/schools/bulk-assign-project-drawer', 'school_ids'],
    ['/partner-oversight/withdraw/bulk', 'assignment_ids'],
  ]);
  const field = fields.get(preview.pathname);
  if (preview.origin !== location.origin || !field || !preview.searchParams.get(field) ||
      [...preview.searchParams.keys()].some(key => key !== field)) return;
  window.htmx.ajax('GET', preview.pathname + preview.search, {
    target: '#drawer-container', swap: 'innerHTML',
  });
});
