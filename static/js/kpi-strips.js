/* One responsive, progressively enhanced KPI strip, including HTMX fragments. */
(() => {
  'use strict';
  const instances = new WeakMap();
  function mount(root) {
    if (!root?.querySelectorAll) return;
    const sections = [...root.querySelectorAll('[data-context-metrics]')];
    if (root.matches?.('[data-context-metrics]')) sections.unshift(root);
    sections.forEach(section => {
      if (instances.has(section)) return;
      const rail = section.querySelector('.context-metrics__sentence');
      const navigation = section.querySelector('.context-metrics__navigation');
      const facts = [...rail.children];
      const next = section.querySelector('.context-metrics__next');
      let frame;
      function update() {
        const width = rail.clientWidth;
        if (!width || !facts.length) return;
        const overflow = rail.scrollWidth > width + 2;
        navigation.hidden = !overflow;
        rail.tabIndex = overflow ? 0 : -1;
        const cell = facts[0].getBoundingClientRect().width;
        const start = Math.min(facts.length, Math.round(Math.abs(rail.scrollLeft) / cell) + 1);
        const end = Math.min(facts.length, start + Math.round(width / cell) - 1);
        section.querySelector('.context-metrics__range').textContent = `${start}–${end} of ${facts.length}`;
        const thumb = section.querySelector('.context-metrics__thumb');
        thumb.style.width = `${width / rail.scrollWidth * 100}%`;
        thumb.style.transform = `translateX(${Math.abs(rail.scrollLeft) / width * 100}%)`;
        next.innerHTML = end === facts.length ? 'Back to start <span aria-hidden="true">←</span>' : 'Swipe for more <span aria-hidden="true">→</span>';
        next.setAttribute('aria-label', end === facts.length ? 'Show first metrics' : 'Show next metrics');
      }
      function schedule() { cancelAnimationFrame(frame); frame = requestAnimationFrame(update); }
      function advance() {
        const end = Math.abs(rail.scrollLeft) + rail.clientWidth >= rail.scrollWidth - 2;
        rail.scrollTo({ left: end ? 0 : rail.scrollLeft + rail.clientWidth, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
      }
      next.addEventListener('click', advance);
      rail.addEventListener('scroll', schedule, { passive: true });
      const resize = new ResizeObserver(schedule);
      resize.observe(rail);
      section.setAttribute('data-kpi-ready', '');
      instances.set(section, () => { resize.disconnect(); cancelAnimationFrame(frame); rail.removeEventListener('scroll', schedule); next.removeEventListener('click', advance); instances.delete(section); });
      update();
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => mount(document));
  else mount(document);
  document.addEventListener('htmx:load', event => mount(event.detail.elt));
  document.addEventListener('htmx:beforeCleanupElement', event => {
    const root = event.detail.elt;
    instances.get(root)?.();
    root.querySelectorAll?.('[data-context-metrics]').forEach(section => instances.get(section)?.());
  });
})();
