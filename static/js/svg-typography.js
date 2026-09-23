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

  let _cachedPixels = null;
  function typographyPixels() {
    if (_cachedPixels) return _cachedPixels;
    // Tokens are CSS lengths (currently rem), not pixel numbers. Let the
    // browser resolve their units and var()/calc() expressions before
    // converting the result into viewBox units.
    const probe = document.createElement('span');
    probe.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none';
    probe.setAttribute('aria-hidden', 'true');
    document.documentElement.appendChild(probe);
    _cachedPixels = {};
    Object.entries(tokenNames).forEach(([tier, name]) => {
      probe.style.fontSize = `var(${name}, ${fallbacks[tier]}px)`;
      _cachedPixels[tier] = parseFloat(getComputedStyle(probe).fontSize) || fallbacks[tier];
    });
    probe.remove();
    return _cachedPixels;
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
    const scaleStr = scale.toFixed(4);
    if (svg.dataset.edifySvgScale === scaleStr) return;
    svg.dataset.edifySvgScale = scaleStr;
    Object.entries(pixels).forEach(([tier, size]) => {
      svg.style.setProperty(`--edify-svg-text-${tier}`, `${size / scale}px`);
    });
    svg.dispatchEvent(new CustomEvent('edify-svg-typography', {bubbles: true}));
  }

  const observer = typeof ResizeObserver === 'function'
    ? new ResizeObserver(entries => {
        const pixels = typographyPixels();
        entries.forEach(entry => {
          // A ResizeObserver holds its targets strongly. Removal is itself a
          // size change, so this is where a swapped-out SVG is let go of;
          // otherwise every chart and map ever shown stayed in memory.
          if (!entry.target.isConnected) {
            observer.unobserve(entry.target);
            observed.delete(entry.target);
            return;
          }
          sync(entry.target, pixels);
        });
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
