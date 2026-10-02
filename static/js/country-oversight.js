/* Country Planning Oversight — the four planning charts.
 *
 * The figures arrive finished from the server (json_script); this file only
 * draws them through the platform's chart system (EdifyChartSystem.stackedBar
 * and .groupedColumns, rendered with renderDetached so every chart is tracked
 * and torn down with its panel). It computes nothing a reader sees: a share
 * chart plots the server's percentages, and the tooltip reads the server's
 * counts beside them.
 *
 * Clicking a Programme Lead's bar asks the table to open that Lead's row.
 */
(function () {
  'use strict';

  function colour(value, root) {
    var match = /^var\((--[\w-]+)\)$/.exec(String(value || '').trim());
    if (!match) { return value; }
    var read = getComputedStyle(root || document.documentElement).getPropertyValue(match[1]).trim();
    return read || '#94a3b8';
  }

  /* A Lead's name on lines of at most ten characters, so four names sit
     under four column groups without colliding ("Basic / Education"). */
  function wrap(name) {
    var lines = [];
    String(name).split(/\s+/).forEach(function (word) {
      var last = lines[lines.length - 1];
      if (last && (last + ' ' + word).length <= 10) { lines[lines.length - 1] = last + ' ' + word; }
      else { lines.push(word); }
    });
    return lines.length > 1 ? lines : name;
  }

  /* ── The page's chart forms ─────────────────────────────────────────────
     Standard forms that only Country Oversight draws, built on the platform
     chart system's shared pieces (formBase, donut, gauge, lineTrend) and
     carried with this page's script rather than the shell every page repeats.
     The chart system itself is frozen, so they live here, not on it. */
  var forms = {
    /* Parts of a whole, one horizontal bar per row (Country Planning
       Oversight, owner design 2026-09-28). The bar standard draws bars side
       by side and would unstack these, so this form is standard in its own
       right: every segment of a bar is a disjoint part of the row's whole,
       computed on the server, and the bar's length IS the row's total. With
       `share` the parts are the server's percentages of 100. The legend sits
       under the plot, a hairline marks the value axis, and the parts carry no
       printed value: the tooltip and the data table under the chart do.

       The shared tooltip of a five-part bar draws one group per part, the
       fifth being apexcharts-tooltip-series-group-4 (the name is written with
       a space after it: Tailwind's scanner, which builds the CSS index from
       static/js, drops a name that runs into punctuation). The name holds the
       legacy class pattern "p-4", and the route audit checks every class on a
       page against that index. */
    stackedBar: function (share, opts) {
      var S = window.EdifyChartSystem;
      return S.formBase({
        _edifyStandard: true,
        chart: { type: 'bar', stacked: true, toolbar: { show: false }, fontFamily: 'inherit',
                 animations: { enabled: false }, parentHeightOffset: 0 },
        plotOptions: { bar: { horizontal: true, barHeight: '62%', borderRadius: 0 } },
        dataLabels: { enabled: false },
        stroke: { show: true, width: 1, colors: ['var(--edify-surface)'] },
        grid: { show: true, borderColor: S.ink.grid, strokeDashArray: 0,
                xaxis: { lines: { show: true } }, yaxis: { lines: { show: false } },
                /* Room for half the last value label ("1,200", "100%"), which
                   is centred on the plot's edge and was cut in two. */
                padding: { left: 4, right: 22, top: 0, bottom: 0 } },
        xaxis: share
          ? { min: 0, max: 100, tickAmount: 5, labels: { formatter: function (v) { return Math.round(v) + '%'; },
              style: { colors: S.ink.axis, fontSize: '12px' } }, axisBorder: { show: false }, axisTicks: { show: false } }
          : { labels: { formatter: function (v) { return Number.isInteger(v) ? v.toLocaleString() : ''; },
              style: { colors: S.ink.axis, fontSize: '12px' } }, axisBorder: { show: false }, axisTicks: { show: false } },
        yaxis: { labels: { maxWidth: 150, style: { colors: S.ink.legend, fontSize: '12px' } } },
        legend: { show: true, position: 'bottom', horizontalAlign: 'left', fontSize: '12px', fontWeight: 500,
                  itemMargin: { horizontal: 8, vertical: 2 }, markers: { width: 9, height: 9, radius: 9 },
                  labels: { colors: S.ink.legend } },
        tooltip: { theme: 'dark', shared: true, intersect: false, style: { fontSize: '12px' } },
        noData: { text: 'No measured data for this selection' },
        /* Four steps on a phone: seven ran "1,0001,200" together. */
        responsive: [{ breakpoint: 520, options: { xaxis: { tickAmount: 4 } } }],
      }, opts);
    },

    /* Two or three measures side by side per row, as columns on a count axis
       with a hairline rule: the form of the planning page's training and
       cluster charts. No value rides the columns — a four-row chart of three
       columns has no room for twelve labels — so the axis, the tooltip and
       the data table under the chart carry them. */
    groupedColumns: function (opts) {
      var S = window.EdifyChartSystem;
      return S.formBase({
        _edifyStandard: true,
        chart: { type: 'bar', toolbar: { show: false }, fontFamily: 'inherit',
                 animations: { enabled: false }, parentHeightOffset: 0 },
        plotOptions: { bar: { columnWidth: '62%', borderRadius: 2, borderRadiusApplication: 'end' } },
        dataLabels: { enabled: false },
        stroke: { show: true, width: 2, colors: ['transparent'] },
        grid: { show: true, borderColor: S.ink.grid, strokeDashArray: 0,
                xaxis: { lines: { show: false } }, yaxis: { lines: { show: true } },
                padding: { left: 4, right: 8, top: 0, bottom: 0 } },
        xaxis: { labels: { trim: false, hideOverlappingLabels: false, rotate: 0,
                 style: { colors: S.ink.legend, fontSize: '12px' } },
                 axisBorder: { show: true, color: S.ink.grid }, axisTicks: { show: false } },
        yaxis: S.countAxis(''),
        legend: { show: true, position: 'bottom', horizontalAlign: 'left', fontSize: '12px', fontWeight: 500,
                  itemMargin: { horizontal: 8, vertical: 2 }, markers: { width: 9, height: 9, radius: 2 },
                  labels: { colors: S.ink.legend } },
        tooltip: { theme: 'dark', shared: true, intersect: false, style: { fontSize: '12px' } },
        noData: { text: 'No measured data for this selection' },
      }, opts);
    },

    /* Country Execution & Completion (owner design, 2026-09-28). The
       reference draws on-time execution and the backlog as rings, the
       forecast as a dial and planned/executed/verified/closed as lines in
       the stage colours of the cards above them. Those three forms are
       standard for that page only; everywhere else the 2026-09-20 bar
       standard (docs/chart-inventory-and-standard-2026-09-20.md) still turns
       rings and gauges into bars. The figures arrive finished, the centre
       text is the server's, and every ring carries its legend in the page. */
    stageRing: function (caption, opts) {
      var S = window.EdifyChartSystem;
      var cfg = S.donut(caption, opts);
      cfg._edifyStandard = true;
      cfg.legend = { show: false };
      return cfg;
    },
    stageDial: function (tone, opts) {
      var S = window.EdifyChartSystem;
      var cfg = S.gauge(tone, '', opts);
      cfg._edifyStandard = true;
      cfg.plotOptions.radialBar.startAngle = -90;
      cfg.plotOptions.radialBar.endAngle = 90;
      return cfg;
    },
    stageLines: function (count, opts) {
      var S = window.EdifyChartSystem;
      var cfg = S.lineTrend(count, opts);
      cfg._edifyStandard = true;
      return cfg;
    }
  };

  function config(payload, root, onPick, width) {
    var S = window.EdifyChartSystem;
    var share = payload.form === 'share';
    var stacked = payload.form === 'stacked' || share;
    var colours = payload.series.map(function (s) { return colour(s.color, root); });
    var series = payload.series.map(function (s) { return { name: s.name, data: s.data.slice() }; });
    var rows = payload.categories.length;
    var events = {
      dataPointSelection: function (event, context, where) {
        var key = payload.keys[where.dataPointIndex];
        if (key && onPick) { onPick(key); }
      },
      xAxisLabelClick: function (event, context, where) {
        var key = payload.keys[where && where.labelIndex];
        if (key && onPick) { onPick(key); }
      }
    };
    var cfg;
    if (stacked) {
      cfg = forms.stackedBar(share);
      /* On a narrow plot the legend under the bars takes three or four lines;
         the chart grows by them, so the rows keep their spacing. */
      var legendLines = width && width < 520 ? 48 : 0;
      cfg.chart = Object.assign({}, cfg.chart, { height: Math.max(160, rows * 34 + 64) + legendLines, events: events });
      if (share) {
        cfg.tooltip = Object.assign({}, cfg.tooltip, {
          y: {
            formatter: function (value, where) {
              var counts = payload.series[where.seriesIndex].counts || [];
              var count = counts[where.dataPointIndex];
              return (count == null ? '' : count.toLocaleString() + ' schools · ') + value + '%';
            }
          }
        });
      } else {
        cfg.tooltip = Object.assign({}, cfg.tooltip, {
          /* What a bar counts: slots on the planning charts, and whatever the
             server names on the execution ones (activities, visits). */
          y: { formatter: function (value) { return value == null ? '' : value.toLocaleString() + ' ' + (payload.unit || 'slots'); } }
        });
      }
    } else {
      cfg = forms.groupedColumns();
      cfg.chart = Object.assign({}, cfg.chart, { height: 220, events: events });
      cfg.tooltip = Object.assign({}, cfg.tooltip, {
        y: { formatter: function (value) { return value == null ? '' : value.toLocaleString(); } }
      });
    }
    cfg.colors = colours;
    cfg.series = series;
    cfg.xaxis = Object.assign({}, cfg.xaxis, { categories: payload.categories.slice() });
    if (!stacked) {
      /* Two-word Lead names wrap under their columns rather than tilting. */
      cfg.xaxis.categories = payload.categories.map(wrap);
    }
    return cfg;
  }

  /* ── Execution & Completion ─────────────────────────────────────────── */
  function cpxConfig(form, payload, root, width) {
    var S = window.EdifyChartSystem;
    var c = function (name) { return colour('var(--cxo-' + name + ')', root); };
    var cfg;
    if (form === 'funnel') {
      cfg = forms.groupedColumns();
      cfg.chart = Object.assign({}, cfg.chart, { height: 250 });
      cfg.colors = [c('total'), c('staff'), c('partner')];
      cfg.series = payload.series.map(function (s) { return { name: s.name, data: s.data.slice() }; });
      cfg.xaxis = Object.assign({}, cfg.xaxis, { categories: payload.categories.map(wrap) });
      cfg.legend = Object.assign({}, cfg.legend, { position: 'top', horizontalAlign: 'right' });
      cfg.dataLabels = {
        enabled: true, offsetY: -18,
        style: { fontSize: '12px', fontWeight: 600, colors: [S.ink.legend] },
        formatter: function (v) { return v == null ? '' : v.toLocaleString(); }
      };
      cfg.plotOptions = { bar: { columnWidth: '72%', borderRadius: 2, borderRadiusApplication: 'end', dataLabels: { position: 'top' } } };
      cfg.tooltip = Object.assign({}, cfg.tooltip, { y: { formatter: function (v) { return v == null ? 'N/A — direct to IA' : v.toLocaleString(); } } });
      if (width && width < 400) {
        /* Six stages side by side do not fit a phone: their names ran into
           each other. On a narrow plot the stages read down the side, a bar
           each, on the stacked bars' axes (names at the left, whole counts
           along the bottom). */
        cfg.chart = Object.assign({}, cfg.chart, { height: payload.categories.length * 62 + 70 });
        cfg.plotOptions = { bar: { horizontal: true, barHeight: '78%', borderRadius: 2, borderRadiusApplication: 'end', dataLabels: { position: 'top' } } };
        cfg.dataLabels = Object.assign({}, cfg.dataLabels, { offsetX: 16, offsetY: 0 });
        /* Room past the longest bar for its printed count: the axis ends on
           a round step above it (a horizontal bar's axis takes a number). */
        var top = 1;
        payload.series.forEach(function (s) { s.data.forEach(function (v) { if (v != null && v > top) { top = v; } }); });
        var step = Math.pow(10, Math.floor(Math.log10(top * 1.2)));
        cfg.xaxis = Object.assign({}, cfg.xaxis, {
          categories: payload.categories.map(wrap), tickAmount: 4, min: 0,
          max: Math.ceil((top * 1.2) / step) * step,
          labels: { formatter: function (v) { return Number.isInteger(Number(v)) ? Number(v).toLocaleString() : ''; },
                    style: { colors: S.ink.axis, fontSize: '12px' } },
          axisBorder: { show: false }
        });
        cfg.yaxis = { labels: { maxWidth: 110, style: { colors: S.ink.legend, fontSize: '12px' } } };
        cfg.grid = Object.assign({}, cfg.grid, { xaxis: { lines: { show: true } }, yaxis: { lines: { show: false } },
                                                padding: { left: 4, right: 24, top: 0, bottom: 0 } });
        cfg.legend = Object.assign({}, cfg.legend, { horizontalAlign: 'left' });
      }
      return cfg;
    }
    if (form === 'trend') {
      cfg = forms.stageLines(4);
      cfg.chart = Object.assign({}, cfg.chart, { height: 250 });
      cfg.colors = [c('planned'), c('exec'), c('verified'), c('closed')];
      cfg.stroke = Object.assign({}, cfg.stroke, { dashArray: [6, 0, 0, 0] });
      cfg.series = payload.series.map(function (s) { return { name: s.name, data: s.data.slice() }; });
      cfg.xaxis = Object.assign({}, cfg.xaxis || {}, {
        categories: payload.categories.map(function (pair) { return pair; }),
        labels: { style: { colors: S.ink.axis, fontSize: '12px' } },
        axisBorder: { show: true, color: S.ink.grid }, axisTicks: { show: false }
      });
      cfg.yaxis = S.countAxis('');
      /* The last week's label is centred on the plot's right edge: half of
         "22–30 Sep" needs the room, or it is cut at the edge. */
      cfg.grid = { show: true, borderColor: S.ink.grid, strokeDashArray: 0, xaxis: { lines: { show: false } }, yaxis: { lines: { show: true } },
                   padding: { left: 4, right: 36, top: 0, bottom: 0 } };
      cfg.tooltip = Object.assign({}, cfg.tooltip, { y: { formatter: function (v) { return v == null ? '—' : v.toLocaleString(); } } });
      return cfg;
    }
    if (form === 'donut') {
      cfg = forms.stageRing(payload.center_caption);
      cfg.chart = Object.assign({}, cfg.chart, { height: 170 });
      cfg.series = payload.parts.map(function (p) { return p.value; });
      cfg.labels = payload.parts.map(function (p) { return p.label; });
      cfg.colors = payload.parts.map(function (p, index) {
        return c(p.key ? 'owner-' + p.key : 'ontime-' + (index + 1));
      });
      cfg.legend = { show: false };
      // The ring's centre reads the server's figure; nothing is summed here.
      var ringText = cfg.plotOptions.pie.donut.labels;
      cfg.plotOptions.pie.donut.labels = Object.assign({}, ringText, {
        total: Object.assign({}, ringText.total, {
          show: true, showAlways: true, label: payload.center_caption,
          formatter: function () { return payload.center; }
        })
      });
      cfg.tooltip = { theme: 'dark', y: { formatter: function (v) { return v.toLocaleString(); } } };
      return cfg;
    }
    if (form === 'age') {
      cfg = forms.groupedColumns();
      cfg.chart = Object.assign({}, cfg.chart, { height: 165 });
      cfg.colors = [c('overdue')];
      cfg.series = [{ name: 'Overdue activities', data: payload.data.slice() }];
      /* "1–2 days" on two lines, so four groups fit a narrow card. */
      cfg.xaxis = Object.assign({}, cfg.xaxis, {
        categories: payload.categories.map(function (label) { return String(label).split(' '); })
      });
      cfg.legend = { show: false };
      cfg.dataLabels = {
        enabled: true, offsetY: -18,
        style: { fontSize: '12px', fontWeight: 700, colors: [S.ink.legend] }
      };
      cfg.plotOptions = { bar: { columnWidth: '58%', borderRadius: 2, borderRadiusApplication: 'end', dataLabels: { position: 'top' } } };
      return cfg;
    }
    if (form === 'gauge') {
      var tone = { on_track: 'success', at_risk: 'danger' }[payload.status] || '';
      cfg = forms.stageDial(tone);
      cfg.chart = Object.assign({}, cfg.chart, { height: 160 });
      if (!tone) { cfg.colors = [c('planned')]; }
      cfg.series = [payload.share == null ? 0 : payload.share];
      if (payload.share == null) {
        cfg.plotOptions.radialBar.dataLabels = { name: { show: false }, value: { show: false } };
      }
      return cfg;
    }
    return null;
  }

  function registerExecution() {
    window.Alpine.data('cpxChart', function (payloadId, form) {
      return {
        chart: null,
        onTheme: null,
        init: function () {
          var self = this;
          this.onTheme = function () { self.draw(); };
          window.addEventListener('edify-theme-change', this.onTheme);
          this.$nextTick(function () { self.draw(); });
        },
        destroy: function () {
          window.removeEventListener('edify-theme-change', this.onTheme);
          if (this.chart && this.chart.destroy) { this.chart.destroy(); }
          this.chart = null;
        },
        draw: function () {
          var holder = document.getElementById(payloadId);
          if (!holder || !window.EdifyChartSystem || !this.$refs.plot) { return; }
          var payload = JSON.parse(holder.textContent || '{}');
          if (this.chart && this.chart.destroy) { this.chart.destroy(); }
          var root = this.$el.closest('[data-cpo-root]') || document.documentElement;
          var cfg = cpxConfig(form, payload, root, this.$refs.plot.clientWidth);
          if (!cfg) { return; }
          this.chart = window.EdifyChartSystem.renderDetached(this.$refs.plot, cfg);
        }
      };
    });
  }

  function register() {
    registerExecution();
    window.Alpine.data('cpoChart', function (payloadId) {
      return {
        chart: null,
        onTheme: null,
        init: function () {
          var self = this;
          this.onTheme = function () { self.draw(); };
          window.addEventListener('edify-theme-change', this.onTheme);
          this.$nextTick(function () { self.draw(); });
        },
        destroy: function () {
          window.removeEventListener('edify-theme-change', this.onTheme);
          if (this.chart && this.chart.destroy) { this.chart.destroy(); }
          this.chart = null;
        },
        draw: function () {
          var holder = document.getElementById(payloadId);
          if (!holder || !window.EdifyChartSystem || !this.$refs.plot) { return; }
          var payload = JSON.parse(holder.textContent || '{}');
          if (this.chart && this.chart.destroy) { this.chart.destroy(); }
          var root = this.$el.closest('[data-cpo-root]') || document.documentElement;
          this.$refs.plot.dataset.empty = payload.empty ? 'true' : 'false';
          this.chart = window.EdifyChartSystem.renderDetached(this.$refs.plot, config(payload, root, function (key) {
            window.dispatchEvent(new CustomEvent('cpo-open-lead', { detail: key }));
          }, this.$refs.plot.clientWidth));
        }
      };
    });
  }

  if (window.Alpine && window.Alpine.data) {
    register();
  } else {
    document.addEventListener('alpine:init', register);
  }
})();
