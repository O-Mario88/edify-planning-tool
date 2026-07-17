/* Edify Reusable Alpine.js Components */

document.addEventListener('alpine:init', () => {

  // ── Theme Store — System / Light / Edify Blue / Dark ────────────────
  Alpine.store('theme', {
    preference: document.documentElement.dataset.themePref || 'system',
    actualTheme: document.documentElement.dataset.theme || 'light',
    systemTimer: null,

    resolveSystemTheme() {
      const hour = new Date().getHours();
      return hour >= 6 && hour < 19 ? 'light' : 'dark';
    },

    millisecondsUntilSystemBoundary() {
      const now = new Date();
      const next = new Date(now);
      if (now.getHours() < 6) {
        next.setHours(6, 0, 1, 0);
      } else if (now.getHours() < 19) {
        next.setHours(19, 0, 1, 0);
      } else {
        next.setDate(next.getDate() + 1);
        next.setHours(6, 0, 1, 0);
      }
      return Math.max(60000, next.getTime() - now.getTime());
    },

    scheduleSystemRefresh() {
      if (this.systemTimer) window.clearTimeout(this.systemTimer);
      this.systemTimer = null;
      if (this.preference !== 'system') return;
      this.systemTimer = window.setTimeout(() => {
        this.applyTheme('system', false);
      }, this.millisecondsUntilSystemBoundary());
    },

    init() {
      /* Keep open Edify tabs visually consistent without requiring reload. */
      window.addEventListener('storage', (event) => {
        if (event.key === 'edify_theme') {
          const next = ['system', 'light', 'blue', 'dark'].includes(event.newValue)
            ? event.newValue
            : 'system';
          this.applyTheme(next, false);
        }
      });
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden && this.preference === 'system') {
          this.applyTheme('system', false);
        }
      });
      this.applyTheme(this.preference, false);
    },

    applyTheme(mode, persist = true) {
      if (!['system', 'light', 'blue', 'dark'].includes(mode)) mode = 'system';
      const actual = mode === 'system' ? this.resolveSystemTheme() : mode;
      this.preference = mode;
      this.actualTheme = actual;

      var html = document.documentElement;
      html.classList.remove('light', 'theme-blue', 'theme-dark', 'dark');
      if (actual === 'light') html.classList.add('light');
      if (actual === 'blue') html.classList.add('dark', 'theme-blue');
      if (actual === 'dark') html.classList.add('dark', 'theme-dark');
      html.dataset.theme = actual;
      html.dataset.themePref = mode;

      var schemeMeta = document.querySelector('meta[name="color-scheme"]');
      var themeMeta = document.querySelector('meta[name="theme-color"]');
      if (schemeMeta) schemeMeta.content = mode === 'system' ? 'light dark' : (actual === 'light' ? 'light' : 'dark');
      if (themeMeta) themeMeta.content = actual === 'light' ? '#edf1f3' : (actual === 'blue' ? '#001d39' : '#080e16');

      if (persist) {
        try { localStorage.setItem('edify_theme', mode); } catch (error) { /* Storage can be blocked. */ }
      }
      this.scheduleSystemRefresh();
      window.dispatchEvent(new CustomEvent('edify-theme-change', { detail: { theme: actual, preference: mode } }));
    },

    setTheme(mode) { this.applyTheme(mode, true); },
    isDark()   { return this.actualTheme === 'dark'; },
    isBlue()   { return this.actualTheme === 'blue'; },
    isLight()  { return this.actualTheme === 'light'; },
  });

  // ── HTMX: preserve theme after partial swaps ──
  document.body.addEventListener('htmx:afterSwap', function() {
    // Theme is driven by root classes + CSS variables — partial swaps
    // inherit automatically. This listener exists for future chart re-inits.
    var evt = new CustomEvent('edify-theme-change', {
      detail: {
        theme: document.documentElement.dataset.theme,
        preference: document.documentElement.dataset.themePref
      }
    });
    window.dispatchEvent(evt);
  });

  // Shared Toast Alerts Controller
  Alpine.data('toastManager', () => ({
    toasts: [],
    add(message, type = 'success', duration = 3000) {
      const id = Date.now() + Math.random().toString(36).substr(2, 5);
      this.toasts.push({ id, message, type });

      setTimeout(() => {
        this.remove(id);
      }, duration);
    },
    remove(id) {
      this.toasts = this.toasts.filter(t => t.id !== id);
    }
  }));

  // Dropdown UI Controller
  Alpine.data('dropdown', (initialOpen = false) => ({
    open: initialOpen,
    toggle() {
      this.open = !this.open;
    },
    close() {
      this.open = false;
    }
  }));

  // URL-addressable local dataset tabs. The backend still supplies every
  // authorized dataset and count; this controller preserves the selected view
  // across refresh/back/forward without turning Alpine into the data source.
  Alpine.data('urlTabs', (defaultTab, allowedTabs) => ({
    activeTab: defaultTab,
    init() {
      const requested = new URL(window.location.href).searchParams.get('tab');
      if (allowedTabs.includes(requested)) this.activeTab = requested;
      window.addEventListener('popstate', () => {
        const tab = new URL(window.location.href).searchParams.get('tab');
        this.activeTab = allowedTabs.includes(tab) ? tab : defaultTab;
      });
    },
    setTab(tab) {
      if (!allowedTabs.includes(tab) || tab === this.activeTab) return;
      this.activeTab = tab;
      const url = new URL(window.location.href);
      url.searchParams.set('tab', tab);
      window.history.pushState({}, '', url);
    },
  }));

  // Impact charts read a single HTML-safe JSON script payload. This keeps
  // backend data out of Alpine attributes and remains stable after HTMX swaps.
  Alpine.data('impactChart', (payloadId, chartType) => ({
    chart: null,
    themeListener: null,
    init() {
      this.themeListener = () => this.renderChart();
      window.addEventListener('edify-theme-change', this.themeListener);
      this.$nextTick(() => this.renderChart());
    },
    destroy() {
      if (this.themeListener) {
        window.removeEventListener('edify-theme-change', this.themeListener);
      }
      if (this.chart) this.chart.destroy();
      this.chart = null;
    },
    payload() {
      const node = document.getElementById(payloadId);
      if (!node) return {};
      try {
        return JSON.parse(node.textContent || '{}');
      } catch (error) {
        return {};
      }
    },
    options(data) {
      const shared = {
        chart: { toolbar: { show: false }, fontFamily: 'Inter, sans-serif' },
        grid: { borderColor: 'var(--edify-chart-grid)', strokeDashArray: 4 },
        tooltip: { theme: 'dark' },
      };
      if (chartType === 'dosage') {
        return {
          ...shared,
          series: [
            { name: 'Visits', data: data.visit_bucket_medians || [] },
            { name: 'Trainings', data: data.training_bucket_medians || [] },
          ],
          chart: { ...shared.chart, height: 260, type: 'bar' },
          plotOptions: { bar: { columnWidth: '45%', borderRadius: 3 } },
          dataLabels: { enabled: false },
          colors: ['var(--edify-chart-blue)', 'var(--edify-info-border)'],
          xaxis: {
            categories: data.bucket_labels || [],
            title: { text: 'Executed activities in exposure window', style: { color: 'var(--edify-text-subtle)', fontSize: '12px' } },
            labels: { style: { colors: 'var(--edify-text-subtle)', fontSize: '12px', fontWeight: '600' } },
            axisBorder: { show: false },
            axisTicks: { show: false },
          },
          yaxis: {
            title: { text: 'Median score delta', style: { color: 'var(--edify-text-subtle)', fontSize: '12px' } },
            labels: { style: { colors: 'var(--edify-text-subtle)', fontSize: '12px' } },
          },
          legend: { position: 'top', horizontalAlign: 'left', fontSize: '12px', fontWeight: 600, labels: { colors: 'var(--edify-text-muted)' } },
        };
      }
      if (chartType === 'funding') {
        return {
          ...shared,
          series: [{ name: 'School', data: data.funding_scatter || [] }],
          chart: { ...shared.chart, height: 260, type: 'scatter', zoom: { enabled: false } },
          colors: ['var(--edify-chart-blue)'],
          xaxis: {
            title: { text: 'Accepted spend (UGX)', style: { color: 'var(--edify-text-subtle)', fontSize: '12px' } },
            labels: { formatter: (value) => `${Math.round(value / 1000)}k`, style: { colors: 'var(--edify-text-subtle)', fontSize: '11px' } },
            axisBorder: { show: false },
            axisTicks: { show: false },
          },
          yaxis: {
            title: { text: 'Mean score delta', style: { color: 'var(--edify-text-subtle)', fontSize: '12px' } },
            labels: { style: { colors: 'var(--edify-text-subtle)', fontSize: '12px' } },
          },
          annotations: { yaxis: [{ y: 0, borderColor: 'var(--edify-text-subtle)', strokeDashArray: 2 }] },
        };
      }
      const series = data.geo_heatmap || [];
      return {
        ...shared,
        series,
        chart: { ...shared.chart, height: Math.max(160, series.length * 44 + 80), type: 'heatmap' },
        dataLabels: { enabled: true, style: { fontSize: '11px' } },
        plotOptions: { heatmap: { radius: 3, colorScale: { ranges: [
          { from: -10, to: -0.31, color: 'var(--edify-danger)', name: 'declining' },
          { from: -0.3, to: 0.3, color: 'var(--edify-warning)', name: 'stagnant' },
          { from: 0.31, to: 10, color: 'var(--edify-success)', name: 'improving' },
        ] } } },
        xaxis: { labels: { rotate: -35, style: { colors: 'var(--edify-text-subtle)', fontSize: '11px', fontWeight: '600' } } },
        yaxis: { labels: { style: { colors: 'var(--edify-text-subtle)', fontSize: '12px', fontWeight: '600' } } },
        legend: { position: 'top', horizontalAlign: 'left', fontSize: '12px', fontWeight: 600, labels: { colors: 'var(--edify-text-muted)' } },
      };
    },
    renderChart() {
      if (!this.$refs.chart || !this.$refs.chart.isConnected) return;
      if (typeof window.ApexCharts === 'undefined') {
        if (this.$refs.status) this.$refs.status.textContent = 'Chart unavailable; the numeric analysis remains available below.';
        return;
      }
      const data = this.payload();
      if (chartType === 'geography' && !(data.geo_heatmap || []).length) return;
      if (this.chart) this.chart.destroy();
      this.chart = new window.ApexCharts(this.$refs.chart, this.options(data));
      this.chart.render()
        .then(() => {
          if (this.$refs.status) this.$refs.status.textContent = 'Chart loaded.';
        })
        .catch(() => {
          if (this.$refs.status) this.$refs.status.textContent = 'Chart unavailable; the numeric analysis remains available below.';
        });
    },
  }));

  // Drawer / Slide-over Control
  Alpine.data('drawer', (initialOpen = false) => ({
    open: initialOpen,
    openDrawer() {
      this.open = true;
      document.body.style.overflow = 'hidden';
    },
    closeDrawer() {
      this.open = false;
      document.body.style.overflow = '';
      this.$dispatch('drawer-closed');
    }
  }));

  // Leave request form — registered before HTMX loads the drawer so Alpine
  // can initialize the swapped partial without a script-order race.
  Alpine.data('leaveRequestForm', (eligibleCoverUrl) => ({
    leaveType: 'personal_time_off',
    startDate: '',
    endDate: '',
    candidates: [],
    daysCharged: 0,
    calendarDays: 0,
    balanceRemaining: 0,
    insufficientBalance: false,
    requiresAttachment: false,
    weekendsSkipped: 0,
    publicHolidaysSkipped: 0,
    blackoutDatesSkipped: 0,
    staffConferenceOverlap: false,
    affectedActivitiesCount: 0,
    hasBlackout: false,
    blackoutReason: '',
    loading: false,
    errorMessage: '',
    requestController: null,

    formatRole(role) {
      const labels = {
        CountryDirector: 'Country Director',
        RegionalVicePresident: 'Regional Vice President',
        ImpactAssessment: 'Impact Assessment',
        HumanResources: 'Human Resources',
        ProjectCoordinator: 'Project Coordinator',
        PartnerAdmin: 'Partner Administrator',
        PartnerFieldOfficer: 'Partner Field Officer',
      };
      return labels[role] || role || 'Team member';
    },

    resetMetrics() {
      this.candidates = [];
      this.daysCharged = 0;
      this.calendarDays = 0;
      this.balanceRemaining = 0;
      this.insufficientBalance = false;
      this.weekendsSkipped = 0;
      this.publicHolidaysSkipped = 0;
      this.blackoutDatesSkipped = 0;
      this.staffConferenceOverlap = false;
      this.affectedActivitiesCount = 0;
      this.hasBlackout = false;
      this.blackoutReason = '';
    },

    async updateMetrics() {
      this.errorMessage = '';

      const select = this.$root.querySelector('#leave-request-type');
      if (select) {
        const selectedOption = select.options[select.selectedIndex];
        if (selectedOption) {
          this.requiresAttachment = selectedOption.dataset.requiresAttachment === 'true';
        }
      }

      if (this.requestController) {
        this.requestController.abort();
        this.requestController = null;
      }

      if (!this.startDate || !this.endDate) {
        this.loading = false;
        this.resetMetrics();
        return;
      }

      if (this.endDate < this.startDate) {
        this.loading = false;
        this.resetMetrics();
        this.errorMessage = 'End date must be on or after the start date.';
        return;
      }

      const controller = new AbortController();
      this.requestController = controller;
      this.loading = true;

      const params = new URLSearchParams({
        start_date: this.startDate,
        end_date: this.endDate,
        type: this.leaveType,
      });

      try {
        const response = await fetch(`${eligibleCoverUrl}?${params.toString()}`, {
          signal: controller.signal,
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        const data = await response.json();

        if (!response.ok || data.error) {
          throw new Error('Unable to calculate this request.');
        }

        this.candidates = data.candidates || [];
        this.daysCharged = data.days_charged || 0;
        this.calendarDays = data.calendar_days || 0;
        this.balanceRemaining = data.balance_remaining || 0;
        this.insufficientBalance = Boolean(data.insufficient_balance);
        this.weekendsSkipped = data.weekends_skipped || 0;
        this.publicHolidaysSkipped = data.public_holidays_skipped || 0;
        this.blackoutDatesSkipped = data.blackout_dates_skipped || 0;
        this.staffConferenceOverlap = Boolean(data.staff_conference_overlap);
        this.affectedActivitiesCount = data.affected_activities_count || 0;
        this.hasBlackout = Boolean(data.has_blackout);
        this.blackoutReason = data.blackout_reason || '';

        if (this.leaveType === 'sick_leave' && this.daysCharged > 2) {
          this.requiresAttachment = true;
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          this.resetMetrics();
          this.errorMessage = 'We could not check entitlement and coverage availability. Please try again.';
        }
      } finally {
        if (this.requestController === controller) {
          this.loading = false;
          this.requestController = null;
        }
      }
    },
  }));
});

/* Shared accessible tabs --------------------------------------------------
   The selected dataset remains server/URL-owned. This small progressive
   enhancement only supplies the keyboard behavior required by the ARIA tabs
   pattern and is safe to rerun after HTMX swaps. */
function enhanceEdifyTabs(root = document) {
  root.querySelectorAll('[role="tablist"]').forEach((tablist) => {
    if (tablist.dataset.edifyTabsReady === 'true') return;
    tablist.dataset.edifyTabsReady = 'true';

    tablist.addEventListener('click', (event) => {
      const selected = event.target.closest('[role="tab"]');
      if (!selected || !tablist.contains(selected)) return;
      tablist.querySelectorAll('[role="tab"]').forEach((tab) => {
        const active = tab === selected;
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
        tab.tabIndex = active ? 0 : -1;
      });
    });

    tablist.addEventListener('keydown', (event) => {
      const tabs = Array.from(
        tablist.querySelectorAll('[role="tab"]:not([aria-disabled="true"]):not(:disabled)')
      );
      if (!tabs.length) return;

      const current = tabs.indexOf(document.activeElement);
      if (current < 0) return;

      let next = null;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
        next = tabs[(current + 1) % tabs.length];
      } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
        next = tabs[(current - 1 + tabs.length) % tabs.length];
      } else if (event.key === 'Home') {
        next = tabs[0];
      } else if (event.key === 'End') {
        next = tabs[tabs.length - 1];
      }

      if (!next) return;
      event.preventDefault();
      next.focus();
      next.click();
    });
  });
}

document.addEventListener('DOMContentLoaded', () => enhanceEdifyTabs());
document.addEventListener('htmx:afterSettle', (event) => enhanceEdifyTabs(event.target));
