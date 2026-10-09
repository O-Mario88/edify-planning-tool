/* The platform's shared chart presentation boundary. Legacy data contracts remain
 * valid while every renderer receives the same geometry and accessible values.
 *
 * Geometry is fixed rather than per-chart taste: a plot is 220px tall, a bar
 * never thicker than 22px, gridlines are one hairline a step off the surface,
 * and the value sits on the bar in muted ink. Colour follows the entity: series
 * N always wears series token N, whichever page or filter it appears on. */
(function (root) {
  'use strict';
  /* Light-theme steps of --edify-series-1..8, the fallback when no stylesheet
   * is present (node tests, a detached render). In a browser the tokens are
   * read live so dark and blue themes draw their own validated steps. */
  const palette = ['#0e5da3', '#ea580c', '#10b981', '#8b5cf6', '#14b8a6', '#f59e0b', '#ec4899', '#84cc16'];
  const MAX_SERIES = palette.length;
  const PLOT_HEIGHT = 220;
  const BAR_MAX_PX = 22;
  const BAR_MIN_PX = 10;
  const PLOT_INSET = 72;
  const number = value => value === null || value === undefined || value === '' ? null :
    (Number.isFinite(Number(value)) ? Number(value) : null);
  const valueOf = point => number(Array.isArray(point) ? point[1] : point && typeof point === 'object' ? point.y : point);
  const format = value => value == null ? 'Not measured' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  const formatMark = value => value != null && Math.abs(value) >= 10000
    ? Number(value).toLocaleString(undefined, {notation: 'compact', maximumFractionDigits: 1}) : format(value);

  function token(name, fallback) {
    if (typeof getComputedStyle !== 'function' || typeof document === 'undefined') return fallback;
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }
  const colorFor = index => token(`--edify-series-${index + 1}`, palette[index]);
  const isDark = () => typeof document !== 'undefined' && document.documentElement.classList.contains('dark');

  function panels(input, width) {
    const type = input.chart?.type;
    let series = (input.series || []).map(s => typeof s === 'object' && !Array.isArray(s) ? {...s, data: [...(s.data || [])]} : s);
    let categories = [...(input.xaxis?.categories || input.labels || [])];
    let horizontal = !!input.plotOptions?.bar?.horizontal;
    let axes = input.yaxis || {};
    if (['donut', 'pie', 'radialBar'].includes(type)) {
      categories = input.labels || series.map((_, i) => String(i + 1));
      series = [{name: type === 'radialBar' ? 'Percent' : 'Value', data: series.map(number)}];
      horizontal = true;
      axes = type === 'radialBar' ? {min: 0, max: 100, title: {text: 'Percent'}} : {min: 0};
    }
    if (type === 'scatter') {
      // Keep every observation. Converting to bars must not silently average,
      // discard duplicate x values, or imply an unapproved statistical model.
      return series.flatMap((s, i) => {
        const points = s.data || [];
        const cats = points.map((p, i) => {
          const x = Array.isArray(p) ? p[0] : p.x;
          return `${format(number(x))} · observation ${i + 1}`;
        });
        return paginate([{name: s.name, data: points.map(valueOf), colorIndex: i}], cats, true, axes,
          `${s.name} — ${input.xaxis?.title?.text || 'Exposure'} per observation`, width);
      });
    }
    if (type === 'heatmap') {
      return series.flatMap((s, i) => paginate([{name: s.name, data: s.data.map(valueOf), colorIndex: i}],
        s.data.map(p => p.x), true, {title: {text: 'Score change'}}, s.name, width).map(panel => ({...panel, family: 'geography', selectorLabel: 'District'})));
    }
    if (!categories.length) {
      categories = (series[0]?.data || []).map((p, i) => p && typeof p === 'object' ? (p.x ?? i + 1) : i + 1);
    }
    // colorIndex is the series' position in the payload, so the same person
    // or measure keeps its hue on every page and in every panel.
    series = series.map((s, i) => ({name: s.name || 'Value', data: (s.data || []).map(valueOf), colorIndex: i}));
    // Explicit per-series axes identify incompatible units in old mixed charts.
    const groups = new Map();
    series.forEach((s, i) => {
      let axis = Array.isArray(axes) ? (axes[i] || axes[0] || {}) : axes;
      if (axis.show === false) axis = axes.find(a => a.show !== false && (!axis.seriesName || a.seriesName === axis.seriesName)) || axes[0] || axis;
      const key = axis.opposite ? 'rate' : (axis.title?.text || 'values');
      if (!groups.has(key)) groups.set(key, {series: [], axis});
      groups.get(key).series.push(s);
    });
    return [...groups.values()].flatMap(group => paginate(group.series, categories, horizontal, group.axis,
      groups.size > 1 ? (group.axis.title?.text || (group.axis.opposite ? 'Achievement (%)' : 'Activities')) : '', width).map(panel => ({...panel, trend: ['line', 'area'].includes(type)})));
  }

  /* How many categories one page holds. More series per category means
   * fewer categories per page, so a bar keeps a readable width on a card
   * instead of the whole plot being squeezed or scrolled. With a measured
   * width the page is the largest natural span (a year, a half, a quarter…)
   * whose bars all clear BAR_MIN_PX; without one, the series count decides. */
  function pageSize(horizontal, seriesCount, width) {
    if (horizontal) return 10;
    if (!width) return seriesCount <= 2 ? 12 : seriesCount <= 4 ? 8 : 6;
    const fits = size => size * seriesCount * BAR_MIN_PX + PLOT_INSET <= width;
    return [12, 8, 6, 4, 3].find(fits) || 3;
  }

  function paginate(series, categories, horizontal, axis, title, width) {
    const result = [];
    // Small multiples prevent a ninth hue and keep labels legible on phones.
    for (let s = 0; s < series.length; s += MAX_SERIES) {
      const slice = series.slice(s, s + MAX_SERIES);
      const size = pageSize(horizontal, slice.length, width);
      for (let c = 0; c < Math.max(1, categories.length); c += size) {
        const last = Math.min(c + size, categories.length);
        const range = categories.length > size ? `${categories[c]} – ${categories[last - 1]}` : '';
        result.push({series: slice.map(row => ({...row, data: row.data.slice(c, c + size)})),
          categories: categories.slice(c, c + size), horizontal, axis,
          title: [title, series.length > MAX_SERIES ? slice.map(row => row.name).join(' / ') : '', range].filter(Boolean).join(' · ')});
      }
    }
    return result;
  }

  /* Bar thickness as the share of the category band, capped at BAR_MAX_PX.
   * `width` is the plot's measured width; without one the cap cannot be
   * computed and the band's default share applies. */
  function barShare(panel, width) {
    const bars = Math.max(1, panel.series.length);
    const bands = Math.max(1, panel.categories.length);
    if (!width) return '60%';
    const band = (width - PLOT_INSET) / bands;
    const share = Math.round(Math.min(60, Math.max(18, (BAR_MAX_PX * bars * 100) / band)));
    return `${share}%`;
  }

  const isPercent = panel => !!(panel.axis?.opposite || panel.axis?.title?.text?.includes('%') || panel.axis?.title?.text === 'Percent');
  const formatterFor = panel => isPercent(panel) ? value => value == null ? format(value) : `${format(value)}%` : format;

  /* ── Horizontal bars: the cut-out ────────────────────────────────────────
   * Owner, 2026-10-09, with a reference chart ("Top 10 States By Hispanic
   * Population"): "use the graph format (Horizontal Cut out bar graph) above
   * for all horizontal bar graphs ... if it is comparing for example previous
   * performance with current performance it should be formatted exactly like
   * the reference image".
   *
   * One row per category on one scale. With two series both bars start at
   * zero on the same line: the first series in the full colour, the second
   * in its tint, the shorter of the two on top — so a part reads against its
   * whole, and last year against this year, as one bar with a piece cut out
   * of it. The shorter bar's value sits inside its end, the longer one's
   * after the bar; when the shorter bar has no room for a number both are
   * written after the bar with their names ("1.6 Hispanic, 8.8 Total"). The
   * legend is a ruled box, the axis one rule with its unit under it.
   *
   * Drawn in the page, not by the chart library: two bars on one line is not
   * a form the library has, and marks made of elements take the theme from
   * the stylesheet with nothing to redraw. */
  const CUT_OUT_LABEL_PX = 34;
  const cutsOut = panel => panel.horizontal && !panel.trend && panel.series.length <= 2
    && panel.series.some(s => s.data.some(v => v != null)) && panel.series.every(s => s.data.every(v => v == null || v >= 0));

  /* A round scale end at or above the largest value, in five steps at most. */
  function cutOutScale(panel) {
    const top = Math.max(0, ...panel.series.flatMap(s => s.data).filter(v => v != null));
    const fixed = number(panel.axis?.max);
    if (fixed != null && fixed >= top) return {max: fixed, step: fixed / (fixed % 5 === 0 ? 5 : 4)};
    if (!top) return {max: 1, step: 1};
    const rough = top / 4;
    const power = 10 ** Math.floor(Math.log10(rough));
    const step = [1, 2, 2.5, 5, 10].map(m => m * power).find(m => m >= rough);
    return {max: Math.ceil(top / step) * step, step};
  }

  function cutOut(slot, panel) {
    const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text != null) node.textContent = text; return node; };
    const say = formatterFor(panel);
    const mark = value => value == null ? format(value) : say === format ? formatMark(value) : say(value);
    const scale = cutOutScale(panel);
    const share = value => `${Math.min(100, (value / scale.max) * 100)}%`;
    const pair = panel.series.length === 2;
    // A series with no value anywhere (this year, in its first weeks) says so
    // once, in the legend, instead of "Not measured" on every row.
    const unmeasured = pair ? panel.series.findIndex(series => series.data.every(v => v == null)) : -1;
    const root = el('div', 'edify-cutout');
    root.dataset.series = String(panel.series.length);
    if (pair) {
      const legend = el('ul', 'edify-cutout__legend');
      panel.series.forEach((series, i) => { const item = el('li', '', unmeasured === i ? `${series.name} · not measured` : series.name); item.prepend(el('i', `edify-cutout__key edify-cutout__key--${i ? 'second' : 'first'}`)); legend.appendChild(item); });
      root.appendChild(legend);
    }
    const rows = el('ol', 'edify-cutout__rows');
    const fit = [];
    panel.categories.forEach((category, index) => {
      const row = el('li', 'edify-cutout__row');
      const name = el('span', 'edify-cutout__name', String(category)); name.title = String(category); row.appendChild(name);
      const track = el('span', 'edify-cutout__track');
      const values = panel.series.map(series => series.data[index]);
      const measured = values.filter(v => v != null);
      const longest = measured.length ? Math.max(...measured) : null;
      const end = el('span', 'edify-cutout__end');
      // Drawn longest first, so the shorter bar lies on top of it.
      values.map((value, i) => ({value, i})).filter(bar => bar.value != null).sort((a, b) => b.value - a.value || a.i - b.i)
        .forEach((bar, order, drawn) => {
          const node = el('span', `edify-cutout__bar edify-cutout__bar--${bar.i ? 'second' : 'first'}`);
          node.style.width = share(bar.value);
          if (order === drawn.length - 1 && drawn.length === 2) {
            const inside = el('b', '', mark(bar.value)); node.appendChild(inside);
            fit.push({node, inside, end, text: mark(longest), spelled: values.map((v, i) => `${mark(v)} ${panel.series[i].name}`).join(', ')});
          }
          track.appendChild(node);
        });
      end.style.insetInlineStart = longest == null ? '0' : share(longest);
      end.dataset.over = pair && values[1] === longest && values[0] !== longest ? 'second' : 'first';
      end.textContent = !pair ? mark(values[0])
        : measured.length === 2 ? mark(longest)
        : !measured.length ? format(null)
        : unmeasured >= 0 ? mark(measured[0])
        : values.map((v, i) => `${mark(v)} ${panel.series[i].name}`).join(', ');
      track.appendChild(end);
      row.appendChild(track);
      rows.appendChild(row);
    });
    root.appendChild(rows);
    const axis = el('div', 'edify-cutout__axis');
    axis.setAttribute('aria-hidden', 'true');
    for (let tick = 0; tick <= scale.max + scale.step / 1000; tick += scale.step) {
      const label = el('span', '', say(Number(tick.toFixed(6)))); label.style.insetInlineStart = share(tick); axis.appendChild(label);
    }
    root.appendChild(axis);
    const unit = panel.axis?.title?.text;
    if (unit) root.appendChild(el('p', 'edify-cutout__unit', unit));
    slot.appendChild(root);
    // A number goes inside its bar only where the bar holds it; a value after
    // a bar that runs off the plot is written inside the end of the bar.
    fit.forEach(row => { if (row.node.offsetWidth && row.node.offsetWidth < Math.max(CUT_OUT_LABEL_PX, row.inside.offsetWidth + 12)) { row.inside.remove(); row.end.textContent = row.spelled; } });
    const edge = root.getBoundingClientRect().right;
    rows.querySelectorAll('.edify-cutout__end').forEach(end => {
      if (edge && end.getBoundingClientRect().right > edge) end.classList.add('edify-cutout__end--inside');
    });
    return {destroy() { root.remove(); }};
  }

  function options(panel, width) {
    const ink = token('--edify-text-muted', '#5b6472');
    const axisInk = token('--edify-text-subtle', ink);
    const gridInk = token('--edify-chart-grid', 'rgba(148, 163, 184, 0.35)');
    const surface = token('--edify-surface', '#ffffff');
    const values = panel.series.flatMap(s => s.data).filter(v => v != null);
    const horizontal = panel.horizontal;
    const trend = panel.trend === true;
    const percent = isPercent(panel);
    const formatter = formatterFor(panel);
    const wholeNumbers = values.every(v => Number.isInteger(v));
    const colors = panel.series.map(s => colorFor(s.colorIndex ?? 0));
    const axis = {...panel.axis, opposite: false, show: true, seriesName: undefined, forceNiceScale: true, tickAmount: 4,
      min: Math.min(0, ...values), labels: {style: {colors: axisInk, fontSize: '12px'},
        formatter: horizontal ? value => String(value) : value => (wholeNumbers && !Number.isInteger(value) ? '' : formatter(value))}};
    if (axis.max != null && Math.max(0, ...values) > axis.max) delete axis.max;
    // A trend's first and last points sit on the plot's edges with their
    // labels centred under them, so half of each fell outside the card
    // ("stlike Behaviour"), and a label that overlapped its neighbour was
    // dropped. Every label is kept: a name too long for its share of the
    // axis breaks onto lines between words, each edge is given half its
    // label's width, and only a single word wider than its share tilts.
    const fits = trend && width ? Math.max(3, Math.floor(((width - 64) / Math.max(1, panel.categories.length) - 10) / 6.8)) : 0;
    const lines = label => String(label ?? '').split(/\s+/).reduce((rows, word) => {
      const last = rows[rows.length - 1];
      if (last !== undefined && `${last} ${word}`.length <= fits) rows[rows.length - 1] = `${last} ${word}`; else rows.push(word);
      return rows;
    }, []);
    const broken = fits ? panel.categories.map(lines) : null;
    const crowded = !!broken && broken.some(rows => rows.some(row => row.length > fits + 1));
    const labels = broken && !crowded ? broken.map(rows => rows.length > 1 ? rows : rows[0]) : panel.categories;
    const deepest = broken && !crowded ? Math.max(1, ...broken.map(rows => rows.length)) : 1;
    const edge = label => 10 + Math.min(72, Math.max(...[].concat(label ?? '').map(row => String(row).length)) * 3.3);
    const perBar = horizontal ? panel.series.length * 16 + 12 : 0;
    // The legend wraps when six names do not fit one row; each extra row is
    // paid for above the plot rather than taken out of it.
    const legendRows = panel.series.length > 1
      ? Math.ceil(panel.series.reduce((n, s) => n + String(s.name).length * 6.5 + 26, 0) / Math.max(200, (width || 720) - 16)) : 0;
    // A label stays silent when its bar has no room for it; the tooltip and
    // the data table carry the value, so nothing is lost and nothing collides.
    // "100%" needs about 36px; a two-digit count about 26px.
    const labelFits = opts => {
      const g = opts && opts.w && opts.w.globals;
      if (!g || !g.gridWidth || !g.gridHeight) return true;
      const bars = (g.labels.length || 1) * (g.series.length || 1);
      return (horizontal ? g.gridHeight : g.gridWidth) / bars >= (horizontal ? 14 : (percent ? 36 : 26));
    };
    // A missing value says "Not measured", without the axis unit, so it is
    // never read as a zero. The words are about 92px wide and side-by-side
    // bars sit at most BAR_MAX_PX apart, so among several series they stay
    // silent like any label without room: six of them over one month piled
    // into a blot on the first day of a fiscal year.
    const missingFits = opts => {
      const g = opts && opts.w && opts.w.globals;
      if (!g || !g.gridWidth || !g.gridHeight) return true;
      if (horizontal) return labelFits(opts);
      return (g.series.length || 1) === 1 && g.gridWidth / (g.labels.length || 1) >= 92;
    };
    return {
      _edifyStandard: true,
      chart: {type: trend ? 'area' : 'bar',
        height: horizontal ? Math.max(150, panel.categories.length * perBar + 56) : PLOT_HEIGHT + legendRows * 24 + (deepest - 1) * 14,
        stacked: false, toolbar: {show: false}, fontFamily: 'inherit', animations: {enabled: false}, parentHeightOffset: 0},
      series: panel.series.map(s => ({name: s.name, data: s.data})), colors,
      fill: trend ? {type: 'gradient', gradient: {shadeIntensity: 0, opacityFrom: 0.12, opacityTo: 0.015, stops: [0, 100]}} : {type: 'solid', opacity: 1},
      /* A 2px surface-coloured stroke is the gap between neighbouring bars. */
      /* A trend is a wave, not a zigzag (owner, 2026-10-09: "the line should be
         wave like"). The monotone curve bends between points without ever
         passing below the lower of two neighbours, so a line that starts at
         zero never dips under the axis the way a plain spline does. */
      stroke: trend ? {width: 2, curve: 'monotoneCubic', lineCap: 'round'} : {show: true, width: 2, colors: [surface]},
      markers: {size: trend ? 3 : 0, colors: [surface], strokeColors: colors, strokeWidth: 2, hover: {sizeOffset: 2}},
      plotOptions: {bar: {horizontal, borderRadius: 0, columnWidth: barShare(panel, width), barHeight: '64%', distributed: false,
        dataLabels: {position: 'top'}}},
      dataLabels: {enabled: !trend, offsetY: horizontal ? 0 : -16, offsetX: horizontal ? 6 : 0,
        textAnchor: horizontal ? 'start' : 'middle',
        formatter: (value, opts) => value == null ? (missingFits(opts) ? format(value) : '')
          : labelFits(opts) ? (formatter === format ? formatMark(value) : formatter(value)) : '',
        style: {fontSize: '12px', fontWeight: 500, colors: [ink]}, background: {enabled: false}},
      xaxis: {crosshairs: {show: trend, stroke: {color: colors[0], width: 1, dashArray: 0}}, categories: labels, type: 'category',
        title: horizontal ? (panel.axis?.title || {}) : {},
        labels: {trim: false, maxHeight: 72, rotate: -30, rotateAlways: crowded, hideOverlappingLabels: !trend, ...(horizontal ? {formatter} : {}),
          style: {colors: axisInk, fontSize: '12px'}},
        axisBorder: {show: true, color: gridInk}, axisTicks: {show: false}},
      // A panel already named by its title does not repeat it down the axis.
      yaxis: horizontal ? {...axis, title: {}} : (panel.title ? {...axis, title: {}} : axis),
      legend: {show: panel.series.length > 1, position: 'top', horizontalAlign: 'left', fontSize: '12px', fontWeight: 500,
        offsetY: -2, itemMargin: {horizontal: 8, vertical: 2}, labels: {colors: ink},
        markers: {width: 8, height: 8, radius: trend ? 8 : 1, offsetX: -3}},
      grid: {show: true, borderColor: gridInk, strokeDashArray: 0,
        xaxis: {lines: {show: horizontal || trend}}, yaxis: {lines: {show: !horizontal}}, padding: {top: 8, right: horizontal ? 48 : trend ? edge(labels[labels.length - 1]) : 8, bottom: 0, left: trend ? edge(labels[0]) : 4}},
      tooltip: {theme: isDark() ? 'dark' : 'light', shared: true, intersect: false, style: {fontSize: '12px'}, y: {formatter}},
      noData: {text: 'No measured data for this selection'},
    };
  }

  function render(el, input, draw) {
    el.querySelectorAll(':scope > [data-standard-charts]').forEach(node => node.remove());
    const wrap = document.createElement('div');
    wrap.dataset.standardCharts = '';
    wrap.className = 'edify-standard-charts';
    el.appendChild(wrap);
    const charts = [];
    const redraws = [];
    // Measured before the panels are cut, so a page is one the card can hold.
    const width = el.clientWidth || 0;
    const groups = panels(input, width);
    const families = new Map();
    groups.forEach(panel => {
      const key = panel.family || JSON.stringify([panel.series.map(s => s.name), panel.axis]);
      if (!families.has(key)) families.set(key, []);
      families.get(key).push(panel);
    });
    families.forEach(pages => {
      const family = document.createElement('section'); family.className = 'edify-chart-family'; wrap.appendChild(family);
      const content = document.createElement('div');
      let currentChart = null;
      let currentPanel = pages[0];
      if (pages.length > 1) {
        const label = document.createElement('label'); label.className = 'edify-chart-page-select'; label.textContent = `${pages[0].selectorLabel || 'Chart range'} `;
        const select = document.createElement('select'); select.setAttribute('aria-label', pages[0].selectorLabel || 'Chart range');
        pages.forEach((p, i) => { const option = document.createElement('option'); option.value = i; option.textContent = p.title || `Page ${i + 1}`; select.appendChild(option); });
        select.addEventListener('change', () => show(pages[Number(select.value)]));
        label.appendChild(select); family.appendChild(label);
      }
      family.appendChild(content);
      function show(panel) {
      currentChart?.destroy(); content.replaceChildren();
      currentPanel = panel;
      const wrap = content;
      if (panel.title && pages.length === 1) { const heading = document.createElement('p'); heading.className = 'edify-chart-panel-title'; heading.textContent = panel.title; wrap.appendChild(heading); }
      const viewport = document.createElement('div'); viewport.className = 'edify-chart-scroll'; viewport.tabIndex = 0;
      viewport.setAttribute('aria-label', 'Chart; scroll horizontally for all categories');
      const slot = document.createElement('div');
      // A phone gets a scrollable plot at a readable bar width, never a
      // squeezed one; a desktop card fits the whole page of categories.
      const bars = panel.categories.length * panel.series.length;
      slot.style.minWidth = `${panel.horizontal ? 300 : Math.max(300, bars * BAR_MIN_PX + PLOT_INSET)}px`;
      viewport.appendChild(slot); wrap.appendChild(viewport);
      if (cutsOut(panel)) {
        currentChart = cutOut(slot, panel);
      } else if (panel.series.some(series => series.data.some(value => value != null))) {
        const width = viewport.clientWidth || el.clientWidth || 0;
        currentChart = draw(slot, options(panel, width));
      } else {
        currentChart = null;
        const empty = document.createElement('p');
        empty.className = 'edify-chart-empty edify-text-muted';
        empty.textContent = 'No measured data for this selection';
        slot.appendChild(empty);
      }
      const details = document.createElement('details'); details.className = 'edify-chart-data';
      const toggle = document.createElement('summary'); toggle.textContent = 'View chart data'; details.appendChild(toggle);
      const table = document.createElement('table'); const head = document.createElement('thead'); const row = document.createElement('tr');
      ['Category', ...panel.series.map(s => s.name)].forEach(label => { const th = document.createElement('th'); th.scope = 'col'; th.textContent = label; row.appendChild(th); });
      head.appendChild(row); table.appendChild(head);
      const body = document.createElement('tbody');
      panel.categories.forEach((category, i) => { const tr = document.createElement('tr');
        [category, ...panel.series.map(s => format(s.data[i]))].forEach((label, index) => { const td = document.createElement(index ? 'td' : 'th'); if (!index) td.scope = 'row'; td.textContent = label; tr.appendChild(td); }); body.appendChild(tr); });
      table.appendChild(body); details.appendChild(table); wrap.appendChild(details);
      }
      const first = initialPage(pages);
      if (pages.length > 1) family.querySelector('select').value = String(first);
      show(pages[first]);
      redraws.push(() => show(currentPanel));
      charts.push({destroy() { currentChart?.destroy(); }});
    });
    if (!groups.length) { const message = document.createElement('p'); message.className = 'edify-chart-empty edify-text-muted'; message.textContent = 'No measured data for this selection'; wrap.appendChild(message); }
    // A theme switch changes the series steps and the ink, so the chart is
    // drawn again from the same panels rather than left in the old theme.
    let timer = null;
    const onTheme = () => { clearTimeout(timer); timer = setTimeout(() => { if (wrap.isConnected) redraws.forEach(fn => fn()); }, 50); };
    window.addEventListener('edify-theme-change', onTheme);
    // Safe to call twice: the page's chart sweep may reach a handle its
    // caller already destroyed.
    return {destroy() {
      window.removeEventListener('edify-theme-change', onTheme);
      clearTimeout(timer);
      charts.splice(0).forEach(chart => { try { chart?.destroy(); } catch (e) { /* already gone */ } });
      wrap.remove();
    }};
  }
  /* A paged time series opens on the latest page that holds any work, so a
   * lead sees this quarter rather than an empty first quarter; rankings and
   * everything else open on their first page. */
  function initialPage(pages) {
    if (pages.length < 2 || pages[0].horizontal) return 0;
    for (let i = pages.length - 1; i >= 0; i -= 1) {
      if (pages[i].series.some(s => s.data.some(v => v))) return i;
    }
    return 0;
  }
  /* The chart library is a deferred script after Alpine, so a chart an Alpine
   * component draws as it starts can ask before the library has run (a slow
   * first visit). It was given up silently and its card stayed empty.
   * `whenLibraryRuns` runs `draw` once the library has run, false on a page
   * without it; `late` is that for renderDetached, with a handle to destroy. */
  function whenLibraryRuns(draw) {
    if (typeof ApexCharts === 'function') { draw(); return true; }
    const library = document.querySelector('script[src*="apexcharts"]');
    if (!library) return false;
    library.addEventListener('load', () => draw(), {once: true});
    return true;
  }
  function late(system, el, options) {
    const waiting = {destroy() { waiting.cancelled = true; }};
    return whenLibraryRuns(() => {
      if (waiting.cancelled || !el.isConnected) return;
      const chart = system.renderDetached(el, options);
      waiting.destroy = () => chart?.destroy?.();
    }) ? waiting : null;
  }
  /* Cut-out bars need no chart library, so a page that loads none (a school
   * or cluster profile) still draws them; anything else waits for it. */
  const needsLibrary = input => input._edifyStandard || panels(input, 0).some(panel => !cutsOut(panel) && panel.series.some(s => s.data.some(v => v != null)));
  const api = {panels, options, render, needsLibrary, palette, pageSize, barShare, colorFor, initialPage, whenLibraryRuns, late, cutsOut, cutOutScale};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.EdifyBarStandard = api;
})(typeof window !== 'undefined' ? window : globalThis);
