/* The platform's shared chart presentation boundary. Legacy data contracts remain
 * valid while every renderer receives the same geometry and accessible values. */
(function (root) {
  'use strict';
  const palette = ['#0e5da3', '#ea580c', '#10b981', '#8b5cf6'];
  const number = value => value === null || value === undefined || value === '' ? null :
    (Number.isFinite(Number(value)) ? Number(value) : null);
  const valueOf = point => number(Array.isArray(point) ? point[1] : point && typeof point === 'object' ? point.y : point);
  const format = value => value == null ? 'Not measured' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  const formatMark = value => value != null && Math.abs(value) >= 10000
    ? Number(value).toLocaleString(undefined, {notation: 'compact', maximumFractionDigits: 1}) : format(value);

  function panels(input) {
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
      return series.flatMap(s => {
        const points = s.data || [];
        const cats = points.map((p, i) => {
          const x = Array.isArray(p) ? p[0] : p.x;
          return `${format(number(x))} · observation ${i + 1}`;
        });
        return paginate([{name: s.name, data: points.map(valueOf)}], cats, true, axes,
          `${s.name} — ${input.xaxis?.title?.text || 'Exposure'} per observation`);
      });
    }
    if (type === 'heatmap') {
      return series.flatMap(s => paginate([{name: s.name, data: s.data.map(valueOf)}],
        s.data.map(p => p.x), true, {title: {text: 'Score change'}}, s.name).map(panel => ({...panel, family: 'geography', selectorLabel: 'District'})));
    }
    if (!categories.length) {
      categories = (series[0]?.data || []).map((p, i) => p && typeof p === 'object' ? (p.x ?? i + 1) : i + 1);
    }
    series = series.map(s => ({name: s.name || 'Value', data: (s.data || []).map(valueOf)}));
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
      groups.size > 1 ? (group.axis.title?.text || (group.axis.opposite ? 'Achievement (%)' : 'Activities')) : '').map(panel => ({...panel, trend: ['line', 'area'].includes(type)})));
  }

  function paginate(series, categories, horizontal, axis, title) {
    const result = [];
    // Small multiples prevent a fifth hue and keep labels legible on phones.
    for (let s = 0; s < series.length; s += 4) {
      const slice = series.slice(s, s + 4);
      const pageSize = horizontal ? 12 : 8;
      for (let c = 0; c < Math.max(1, categories.length); c += pageSize) {
        result.push({series: slice.map(row => ({...row, data: row.data.slice(c, c + pageSize)})),
          categories: categories.slice(c, c + pageSize), horizontal, axis,
          title: [title, series.length > 4 ? slice.map(row => row.name).join(' / ') : '',
            categories.length > pageSize ? `${c + 1}–${Math.min(c + pageSize, categories.length)}` : ''].filter(Boolean).join(' · ')});
      }
    }
    return result;
  }

  function options(panel) {
    const ink = 'var(--edify-text-muted)';
    const values = panel.series.flatMap(s => s.data).filter(v => v != null);
    const horizontal = panel.horizontal;
    const trend = panel.trend === true;
    const formatter = panel.axis?.opposite || panel.axis?.title?.text?.includes('%') || panel.axis?.title?.text === 'Percent' ? value => `${format(value)}%` : format;
    const axis = {...panel.axis, opposite: false, show: true, seriesName: undefined,
      min: Math.min(0, ...values), labels: {style: {colors: ink, fontSize: '12px'}, formatter: horizontal ? value => String(value) : formatter}};
    if (axis.max != null && Math.max(0, ...values) > axis.max) delete axis.max;
    return {
      _edifyStandard: true,
      chart: {type: trend ? 'area' : 'bar', height: horizontal ? Math.max(240, panel.categories.length * panel.series.length * 24 + 90) : 300,
        stacked: false, toolbar: {show: false}, fontFamily: 'inherit', animations: {enabled: false}},
      series: panel.series, colors: palette.slice(0, panel.series.length),
      fill: trend ? {type: 'gradient', gradient: {shadeIntensity: 0, opacityFrom: 0.12, opacityTo: 0.015, stops: [0, 100]}} : {type: 'solid', opacity: 1},
      stroke: {width: trend ? 2 : 0, curve: 'straight'},
      markers: {size: trend ? 3 : 0, colors: ['var(--edify-surface)'], strokeColors: palette, strokeWidth: 2, hover: {sizeOffset: 2}},
      plotOptions: {bar: {horizontal, borderRadius: 0, columnWidth: '65%', barHeight: '65%', distributed: false,
        dataLabels: {position: 'top'}}},
      dataLabels: {enabled: !trend, offsetY: horizontal ? 0 : -18, offsetX: horizontal ? 8 : 0,
        textAnchor: horizontal ? 'start' : 'middle', formatter: value => formatter === format ? formatMark(value) : formatter(value),
        style: {fontSize: '11px', fontWeight: 500, colors: [ink]}, background: {enabled: false}},
      xaxis: {crosshairs: {show: trend, stroke: {color: palette[0], width: 1, dashArray: 0}}, categories: panel.categories, type: 'category', title: horizontal ? (panel.axis?.title || {}) : {}, labels: {trim: false, rotate: -35, ...(horizontal ? {formatter} : {}), style: {colors: ink, fontSize: '12px'}},
        axisBorder: {show: true, color: 'var(--edify-border)'}, axisTicks: {show: false}},
      yaxis: horizontal ? {...axis, title: {}} : axis,
      legend: {show: panel.series.length > 1, position: 'top', horizontalAlign: trend ? 'left' : 'center', labels: {colors: ink}, markers: {radius: trend ? 12 : 0}},
      grid: {show: true, borderColor: 'var(--edify-border)', strokeDashArray: 0,
        xaxis: {lines: {show: horizontal || trend}}, yaxis: {lines: {show: !horizontal}}, padding: {top: 20, right: horizontal ? 65 : 16}},
      tooltip: {theme: trend ? 'light' : 'dark', shared: true, intersect: false, y: {formatter}},
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
    const groups = panels(input);
    const families = new Map();
    groups.forEach(panel => {
      const key = panel.family || JSON.stringify([panel.series.map(s => s.name), panel.axis]);
      if (!families.has(key)) families.set(key, []);
      families.get(key).push(panel);
    });
    families.forEach(pages => {
      const family = document.createElement('section'); wrap.appendChild(family);
      const content = document.createElement('div');
      let currentChart = null;
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
      const wrap = content;
      if (panel.title) { const heading = document.createElement('p'); heading.className = 'edify-chart-panel-title'; heading.textContent = panel.title; wrap.appendChild(heading); }
      const viewport = document.createElement('div'); viewport.className = 'edify-chart-scroll'; viewport.tabIndex = 0;
      viewport.setAttribute('aria-label', 'Chart; scroll horizontally for all categories');
      const slot = document.createElement('div');
      slot.style.minWidth = `${panel.horizontal ? 360 : Math.max(360, panel.categories.length * panel.series.length * 42)}px`;
      viewport.appendChild(slot); wrap.appendChild(viewport);
      if (panel.series.some(series => series.data.some(value => value != null))) {
        currentChart = draw(slot, options(panel));
      } else {
        currentChart = null;
        const empty = document.createElement('p');
        empty.className = 'edify-text-muted';
        empty.textContent = 'No measured data for this selection';
        slot.appendChild(empty);
      }
      const details = document.createElement('details'); details.className = 'edify-chart-data';
      const summary = document.createElement('summary'); summary.textContent = 'View chart data'; details.appendChild(summary);
      const table = document.createElement('table'); const head = document.createElement('thead'); const row = document.createElement('tr');
      ['Category', ...panel.series.map(s => s.name)].forEach(label => { const th = document.createElement('th'); th.scope = 'col'; th.textContent = label; row.appendChild(th); });
      head.appendChild(row); table.appendChild(head);
      const body = document.createElement('tbody');
      panel.categories.forEach((category, i) => { const tr = document.createElement('tr');
        [category, ...panel.series.map(s => format(s.data[i]))].forEach((label, index) => { const td = document.createElement(index ? 'td' : 'th'); if (!index) td.scope = 'row'; td.textContent = label; tr.appendChild(td); }); body.appendChild(tr); });
      table.appendChild(body); details.appendChild(table); wrap.appendChild(details);
      }
      show(pages[0]);
      charts.push({destroy() { currentChart?.destroy(); }});
    });
    if (!groups.length) { const message = document.createElement('p'); message.textContent = 'No measured data for this selection'; wrap.appendChild(message); }
    return {destroy() { charts.forEach(chart => chart?.destroy()); wrap.remove(); }};
  }
  const api = {panels, options, render, palette};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.EdifyBarStandard = api;
})(typeof window !== 'undefined' ? window : globalThis);
