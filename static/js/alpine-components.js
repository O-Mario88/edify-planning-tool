/* Edify Reusable Alpine.js Components */

document.addEventListener('alpine:init', () => {

  // ── Theme Store — System / Light / Edify Blue / Dark ────────────────
  Alpine.store('theme', {
    preference: document.documentElement.dataset.themePref || 'system',
    actualTheme: document.documentElement.dataset.theme || 'light',
    lastNonDarkPreference: document.documentElement.dataset.themePref === 'dark'
      ? 'light'
      : (document.documentElement.dataset.themePref || 'system'),
    systemMedia: null,

    resolveSystemTheme() {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    },

    init() {
      this.systemMedia = window.matchMedia('(prefers-color-scheme: dark)');
      this.systemMedia.addEventListener('change', () => {
        if (this.preference === 'system') this.applyTheme('system', false);
      });
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
      if (actual !== 'dark') this.lastNonDarkPreference = mode;
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
      if (themeMeta) themeMeta.content = actual === 'light' ? '#edf1f3' : (actual === 'blue' ? '#001d39' : '#000000');

      if (persist) {
        try { localStorage.setItem('edify_theme', mode); } catch (error) { /* Storage can be blocked. */ }
      }
      window.dispatchEvent(new CustomEvent('edify-theme-change', { detail: { theme: actual, preference: mode } }));
    },

    setTheme(mode) { this.applyTheme(mode, true); },
    toggleNight() {
      if (this.actualTheme === 'dark') {
        this.setTheme(this.preference === 'dark' ? this.lastNonDarkPreference : 'light');
        return;
      }
      this.lastNonDarkPreference = this.preference;
      this.setTheme('dark');
    },
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
  /* Install the app.
   *
   * `beforeinstallprompt` fires once, early, and is the ONLY handle on the
   * browser's install flow — so it is captured at document level (see the
   * listener registered outside alpine:init below) and parked on window,
   * because Alpine initialises after it has already fired. Reading it from
   * the event alone means the button never appears.
   *
   * prompt() must be called from a real user gesture and can only be used
   * once, so the stored event is dropped after use whatever the outcome.
   *
   * Safari has no equivalent API. Rather than show a button that cannot work,
   * iOS gets the Share > Add to Home Screen instruction — and only when it is
   * actually actionable: on iOS, in a browser, not already installed.
   */
  Alpine.data('edifyInstall', () => ({
    canInstall: false,
    showIosHint: false,

    init() {
      const standalone = window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true;
      if (standalone) return;

      this.canInstall = !!window.__edifyInstallPrompt;
      window.addEventListener('edify-install-available', () => { this.canInstall = true; });
      window.addEventListener('appinstalled', () => {
        this.canInstall = false;
        this.showIosHint = false;
        window.__edifyInstallPrompt = null;
      });

      // iOS Safari only: no beforeinstallprompt exists there, so the absence
      // of the event is expected rather than a failure to detect.
      const ua = window.navigator.userAgent;
      const isIos = /iPad|iPhone|iPod/.test(ua)
        || (ua.includes('Macintosh') && 'ontouchend' in document);
      const isSafari = /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS|Chrome/.test(ua);
      this.showIosHint = isIos && isSafari && !this.canInstall;
    },

    install() {
      const deferred = window.__edifyInstallPrompt;
      if (!deferred) { this.canInstall = false; return; }
      window.__edifyInstallPrompt = null;
      this.canInstall = false;
      deferred.prompt();
    },
  }));

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

  // Confirmation for an action that cannot be undone.
  //
  // Replaces window.confirm(), which sits outside the page: it cannot be
  // themed, it says "OK/Cancel" rather than what will happen, and the browser
  // renders it identically whether the answer deletes a school or dismisses a
  // tooltip. This is a real dialog, so it has to do the things a real dialog
  // does — trap focus, close on Escape, and put focus back where it was.
  Alpine.data('confirmAction', () => ({
    asking: false,
    returnFocusTo: null,

    ask() {
      this.returnFocusTo = document.activeElement;
      this.asking = true;
      // The cancelling choice takes focus, so Return answers safely.
      this.$nextTick(() => this.$refs.cancel?.focus());
    },

    dismiss() {
      this.asking = false;
      // Back to the control that opened it, not to the top of the document.
      this.$nextTick(() => this.returnFocusTo?.focus?.());
    },

    // Tab must not walk out of the dialog into the page behind it.
    trap(event) {
      if (event.key !== 'Tab' || !this.asking) { return; }
      const focusable = this.$refs.panel?.querySelectorAll(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
      );
      if (!focusable || !focusable.length) { return; }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  }));

  // Row actions menu.
  //
  // The list is position:fixed rather than absolute, because an absolutely
  // positioned menu is clipped by the first ancestor that scrolls or hides its
  // overflow — and every table here sits inside a card with overflow hidden and
  // a horizontally scrolling wrapper. Fixed coordinates escape both, so the
  // menu opens whole instead of losing its lower half inside the card.
  //
  // The cost of fixed positioning is that the coordinates go stale the moment
  // anything scrolls or resizes, so the menu re-measures on both. Closing
  // instead would be simpler, but a menu that vanishes because a mobile
  // browser collapsed its toolbar is a menu the user has to open twice.
  Alpine.data('rowMenu', () => ({
    open: false,
    x: 0,
    y: 0,
    toggle() {
      this.open = !this.open;
      if (this.open) { this.place(); }
    },
    close() {
      this.open = false;
    },
    reposition() {
      if (this.open) { this.place(); }
    },
    place() {
      // After the tick, x-show has applied display, so the list can be
      // measured — which is what decides whether it fits below the row.
      this.$nextTick(() => {
        const trigger = this.$refs.trigger;
        const list = this.$refs.list;
        if (!trigger || !list) { return; }
        const rect = trigger.getBoundingClientRect();
        const height = list.offsetHeight;
        // Right-aligned on the trigger by arithmetic rather than by a CSS
        // translate: x-transition writes its own inline `transform`, which
        // wins over the stylesheet and left the menu hanging off the row.
        this.x = Math.max(8, rect.right - list.offsetWidth);
        // Flip above the trigger when the menu would run past the foot of the
        // viewport, which is what the last row of a long table does.
        const below = rect.bottom + 4;
        this.y = (below + height > window.innerHeight && rect.top - 4 - height > 0)
          ? rect.top - 4 - height
          : below;
      });
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
        chart: { toolbar: { show: false }, fontFamily: 'Geist Sans, sans-serif' },
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
          dataLabels: { enabled: false },
          colors: window.EdifyChartSystem.comparisonSeries.slice(0, 2),
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
          colors: window.EdifyChartSystem.singleSeries.slice(),
          xaxis: {
            title: { text: 'Accepted spend (UGX)', style: { color: 'var(--edify-text-subtle)', fontSize: '12px' } },
            labels: { formatter: (value) => `${Math.round(value / 1000)}k`, style: { colors: 'var(--edify-text-subtle)', fontSize: '12px' } },
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
        dataLabels: { enabled: true, style: { fontSize: '12px' } },
        plotOptions: { heatmap: { radius: 3, colorScale: { ranges: [
          { from: -10, to: -0.31, color: 'var(--edify-danger)', name: 'declining' },
          { from: -0.3, to: 0.3, color: 'var(--edify-warning)', name: 'stagnant' },
          { from: 0.31, to: 10, color: 'var(--edify-success)', name: 'improving' },
        ] } } },
        xaxis: { labels: { rotate: -35, style: { colors: 'var(--edify-text-subtle)', fontSize: '12px', fontWeight: '600' } } },
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
  //
  // The scroll lock is delegated rather than set here. Two components each
  // writing body.style.overflow means the first one to close clears a lock
  // the other still needs, and a component destroyed while open leaves the
  // page permanently unscrollable. static/js/drawer-background.js owns it,
  // counts nothing twice, and releases from the container's actual contents.
  Alpine.data('drawer', (initialOpen = false) => ({
    open: initialOpen,
    openDrawer() {
      this.open = true;
      window.__edifyDrawerBackground?.lock();
    },
    closeDrawer() {
      this.open = false;
      window.__edifyDrawerBackground?.release();
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

document.addEventListener('alpine:init', () => {
  /* School Visit Effectiveness charts — one payload element, per-type
     options. Series colours follow the platform chart semantics (actual =
     brand blue, prior period = muted, decline = danger). */
  Alpine.data('visitFxChart', (payloadId, chartType) => ({
    chart: null,
    init() { this.$nextTick(() => this.render()); },
    destroy() { if (this.chart) this.chart.destroy(); },
    payload() {
      const node = document.getElementById(payloadId);
      try { return JSON.parse(node.textContent || '{}'); } catch (e) { return {}; }
    },
    render() {
      const all = this.payload();
      const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
      /* The first two categorical slots, so a comparison here matches one
         drawn anywhere else — and picks up the dark-mode steps, which the
         --edify-chart-* tokens have no validated variant of. The semantic
         four below stay as they are: green/amber/red are carrying meaning
         in the status charts that use them. */
      const brand = css('--edify-series-1') || '#0e5da3';
      const muted = '#94a3b8';
      const orange = css('--edify-series-2') || '#ea580c';
      const green = css('--edify-chart-green') || '#10b981';
      const amber = css('--edify-chart-amber') || '#f59e0b';
      const red = css('--edify-chart-red') || '#ef4444';
      let opts = null;
      if (chartType === 'interventions') {
        const d = all.interventions || {};
        opts = {
          chart: { type: 'bar', height: 320 },
          series: [
            { name: 'Initial SSA Score', data: d.baseline || [] },
            { name: 'Follow-up', data: d.followup || [] },
          ],
          xaxis: { categories: d.labels || [], labels: { rotate: -35, trim: true, hideOverlappingLabels: true, style: { fontSize: '12px' } } },
          colors: [brand, orange],
        };
      } else if (chartType === 'scatter') {
        const d = all.scatter || {};
        opts = {
          chart: { type: 'scatter', height: 320, zoom: { enabled: false } },
          series: [
            { name: 'Core', data: d.core || [] },
            { name: 'Client', data: d.client || [] },
          ],
          xaxis: { title: { text: 'Delivered visits' }, tickAmount: 6 },
          yaxis: { title: { text: 'SSA change' } },
          colors: [brand, muted],
          markers: { size: 5 },
        };
      } else if (chartType === 'purpose') {
        const d = all.purpose || {};
        opts = {
          chart: { type: 'donut', height: 280 },
          series: d.counts || [],
          labels: d.labels || [],
          colors: [amber, green, brand, '#8b5cf6', muted],
          legend: { position: 'bottom' },
        };
      } else if (chartType === 'outcomes') {
        const d = all.outcomes || {};
        opts = {
          chart: { type: 'bar', height: 280 },
          series: [{ name: 'Schools', data: [d.improved || 0, d.unchanged || 0, d.declined || 0, d.not_yet_measurable || 0] }],
          xaxis: { categories: ['Improved', 'Unchanged', 'Declined', 'Not yet measurable'],
                   axisBorder: { show: false }, axisTicks: { show: false },
                   labels: { style: { colors: 'var(--edify-text-muted)', fontSize: '12px', fontWeight: 600 } } },
          yaxis: { labels: { show: false } },
          colors: [brand],
          /* Vertical, not horizontal — the reference styling is the track, the
             pill cap and the inline value, none of which imply an orientation. */
          plotOptions: { bar: { distributed: true, borderRadiusApplication: 'around',
                                dataLabels: { position: 'top' } } },
          fill: { colors: [green, muted, red, amber] },
          dataLabels: { enabled: true, offsetY: 20,
                        style: { fontSize: '12px', fontWeight: 700, colors: ['#fff'] },
                        dropShadow: { enabled: false },
                        formatter: (v, o) => (window.EdifyChartSystem.barValueFitsInside(v, o) ? v : '') },
          grid: { show: false },
          legend: { show: false },
        };
      } else if (chartType === 'funnel') {
        const d = all.funnel || {};
        opts = {
          chart: { type: 'bar', height: 280 },
          series: [{ name: 'Visits', data: [d.scheduled || 0, d.delivered || 0, d.evidence || 0, d.aligned || 0, d.followup_ssa_available || 0] }],
          /* Single series: the track carries the scale, so the value axis and
             gridlines are redundant and the count rides inside the bar. */
          plotOptions: { bar: { horizontal: true, borderRadiusApplication: 'around',
                                dataLabels: { position: 'top' } } },
          xaxis: { categories: ['Scheduled', 'Delivered', 'Evidence', 'Aligned', 'Follow-up SSA'],
                   labels: { show: false }, axisBorder: { show: false }, axisTicks: { show: false } },
          yaxis: { labels: { style: { colors: 'var(--edify-text-muted)', fontSize: '12px' } } },
          colors: [brand],
          dataLabels: { enabled: true, textAnchor: 'end', offsetX: -10,
                        style: { fontSize: '12px', fontWeight: 700, colors: ['#fff'] },
                        dropShadow: { enabled: false },
                        formatter: (v, o) => (window.EdifyChartSystem.barValueFitsInside(v, o) ? v : '') },
          grid: { show: false },
        };
      }
      if (!opts || !this.$refs.el || typeof ApexCharts === 'undefined') return;
      if (this.chart) this.chart.destroy();
      this.chart = new ApexCharts(this.$refs.el, opts);
      this.chart.render();
    },
  }));
});
