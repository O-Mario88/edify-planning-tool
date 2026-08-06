/* Keep text inside responsive SVGs on the same on-screen type scale as HTML.
 *
 * CSS font sizes on an SVG with a viewBox are measured in viewBox units. A
 * nominal 12px label therefore grows or shrinks with the drawing. These
 * variables counter the SVG's outer scale so authored charts can use the
 * platform typography tokens without changing their rendered pixel size.
 */
(function () {
  'use strict';

  const selector = 'svg[data-edify-svg-typography]';
  const observed = new WeakSet();
  const tokenNames = Object.freeze({
    micro: '--edify-text-micro-size',
    label: '--edify-text-label-size',
    body: '--edify-text-body-size',
    title: '--edify-text-title-size',
  });
  const fallbacks = Object.freeze({micro: 12, label: 14, body: 15, title: 16});

  function tokenPixels(token, fallback) {
    const probe = document.createElement('span');
    probe.setAttribute('aria-hidden', 'true');
    probe.style.cssText =
      'position:fixed;visibility:hidden;pointer-events:none;' +
      `font-size:var(${token},${fallback}px)`;
    document.body.appendChild(probe);
    const pixels = parseFloat(getComputedStyle(probe).fontSize);
    probe.remove();
    return Number.isFinite(pixels) ? pixels : fallback;
  }

  function typographyPixels() {
    return Object.fromEntries(
      Object.entries(tokenNames).map(([tier, token]) => [
        tier,
        tokenPixels(token, fallbacks[tier]),
      ]),
    );
  }

  function outerScale(svg) {
    const viewBox = svg.viewBox && svg.viewBox.baseVal;
    const rect = svg.getBoundingClientRect();
    if (!viewBox || !viewBox.width || !viewBox.height || !rect.width || !rect.height) {
      return 0;
    }
    return Math.min(rect.width / viewBox.width, rect.height / viewBox.height);
  }

  function sync(svg, pixels) {
    const scale = outerScale(svg);
    if (!scale) return;
    Object.entries(pixels).forEach(([tier, size]) => {
      svg.style.setProperty(`--edify-svg-text-${tier}`, `${size / scale}px`);
    });
    svg.dispatchEvent(new CustomEvent('edify-svg-typography', {bubbles: true}));
  }

  const observer = typeof ResizeObserver === 'function'
    ? new ResizeObserver(entries => {
        const pixels = typographyPixels();
        entries.forEach(entry => sync(entry.target, pixels));
      })
    : null;

  function register(root) {
    const svgs = [];
    if (root.matches && root.matches(selector)) svgs.push(root);
    if (root.querySelectorAll) svgs.push(...root.querySelectorAll(selector));
    if (!svgs.length) return;

    const pixels = typographyPixels();
    svgs.forEach(svg => {
      sync(svg, pixels);
      if (observer && !observed.has(svg)) {
        observed.add(svg);
        observer.observe(svg);
      }
    });
  }

  register(document);
  document.addEventListener('htmx:afterSwap', event => register(event.target));
  window.addEventListener('resize', () => register(document), {passive: true});
})();
