(function () {
  'use strict';

  window.documentReadingTracker = function documentReadingTracker(options) {
    options = options || {};
    return {
      versionId: String(options.versionId || ''),
      pageCount: Number(options.pageCount || 0),
      activeSeconds: Number(options.initialSeconds || 0),
      requiredSeconds: Number(options.requiredSeconds || 0),
      pendingSeconds: 0,
      lastActivityAt: performance.now(),
      tickTimer: null,
      beatTimer: null,
      beatInFlight: false,
      activityEvents: ['pointerdown', 'keydown', 'touchstart', 'scroll'],

      get readingLabel() {
        return this.formatDuration(this.activeSeconds);
      },
      get requiredReadingLabel() {
        return this.formatDuration(this.requiredSeconds);
      },
      get readingStatus() {
        if (!this.requiredSeconds) return 'Not monitored';
        if (this.activeSeconds >= this.requiredSeconds) return 'Completed reading';
        if (!this.activeSeconds) return 'Did not read';
        return 'Partial read';
      },
      get readingProgress() {
        if (!this.requiredSeconds) return 0;
        return Math.min(100, Math.round((this.activeSeconds / this.requiredSeconds) * 100));
      },

      init() {
        if (!this.versionId) return;
        this.noteActivity = this.noteActivity.bind(this);
        this.activityEvents.forEach((eventName) => {
          window.addEventListener(eventName, this.noteActivity, { passive: true });
        });
        document.addEventListener('visibilitychange', () => {
          if (document.visibilityState === 'visible') {
            this.noteActivity();
            this.beat();
          } else {
            this.beat(true);
          }
        });
        window.addEventListener('focus', this.noteActivity);
        window.addEventListener('blur', () => this.beat(true));
        window.addEventListener('pagehide', () => this.beat(true));

        // Count in one-second slices only while the page is visible, focused,
        // and the reader has interacted within the two-minute idle window.
        this.tickTimer = window.setInterval(() => {
          if (!this.isActivelyReading()) return;
          this.pendingSeconds += 1;
          this.activeSeconds += 1;
        }, 1000);
        this.beatTimer = window.setInterval(() => this.beat(), 15000);
        this.beat();
      },

      destroy() {
        if (this.tickTimer) window.clearInterval(this.tickTimer);
        if (this.beatTimer) window.clearInterval(this.beatTimer);
        this.activityEvents.forEach((eventName) => {
          window.removeEventListener(eventName, this.noteActivity);
        });
        window.removeEventListener('focus', this.noteActivity);
      },

      noteActivity() {
        this.lastActivityAt = performance.now();
      },

      isActivelyReading() {
        return document.visibilityState === 'visible'
          && document.hasFocus()
          && (performance.now() - this.lastActivityAt) <= 120000;
      },

      async beat(keepalive) {
        if (this.beatInFlight) return;
        this.beatInFlight = true;
        const delta = this.pendingSeconds;
        try {
          const body = new URLSearchParams({
            page: String(this.pageCount || 1),
            active_delta_seconds: String(delta),
          });
          const response = await fetch(`/api/documents/engagement/${this.versionId}`, {
            method: 'POST',
            keepalive: Boolean(keepalive),
            headers: {
              'X-CSRFToken': this.csrf(),
              'Content-Type': 'application/x-www-form-urlencoded',
            },
            body,
          });
          if (!response.ok) return;
          const data = await response.json();
          this.pendingSeconds = Math.max(0, this.pendingSeconds - delta);
          this.activeSeconds = Number(data.active_seconds || 0) + this.pendingSeconds;
        } catch (error) {
          // Reading must remain available when telemetry is temporarily down.
        } finally {
          this.beatInFlight = false;
        }
      },

      async recordPrint(url) {
        try {
          await fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': this.csrf() },
          });
        } catch (error) {
          // Printing remains available when telemetry is temporarily down.
        }
        window.print();
      },

      formatDuration(seconds) {
        // Display-only clamp of elapsed reading seconds — no business
        // quantity is computed here.
        const clampedSeconds = Math.max(0, Number(seconds || 0));
        const minutes = Math.floor(clampedSeconds / 60);
        const remainder = clampedSeconds % 60;
        return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
      },

      csrf() {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : '';
      },
    };
  };
}());
