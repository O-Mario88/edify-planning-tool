/* The greeting in the person's device time, on Home and the CCEO dashboard.
 *
 * The server words it once, when the page is made. A page can stay open for
 * hours — the phone app resumed in the afternoon, a tab woken up, a page
 * brought back from the back/forward cache — so it is worded again from the
 * device's clock whenever the page is shown (owner, 2026-10-24: "if the app
 * is opened in afternoon it should not again say good morning").
 *
 * The hours are the server's (apps.command_center.home_service.greeting_for):
 * morning until noon, afternoon until five, evening after.
 *
 * `reloadOnNewDay` (Home) makes the page again when it is shown on a later
 * day than it was opened, so its figures are never yesterday's. The day is
 * the device's on both sides, so a phone and a server in different time zones
 * cannot reload it in a loop.
 */
(function () {
  'use strict';

  function greetingFor(moment) {
    const hour = moment.getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }

  function localDay(moment) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${moment.getFullYear()}-${pad(moment.getMonth() + 1)}-${pad(moment.getDate())}`;
  }

  function edifyGreeting(options) {
    const reloadOnNewDay = Boolean(options && options.reloadOnNewDay);
    return {
      text: 'Welcome',
      timer: null,
      openedOn: '',
      onVisible: null,
      now() {
        return new Date();
      },
      update() {
        const moment = this.now();
        if (reloadOnNewDay && this.openedOn && localDay(moment) !== this.openedOn) {
          window.location.reload();
          return;
        }
        this.text = greetingFor(moment);
      },
      init() {
        this.openedOn = localDay(this.now());
        this.update();
        // Timers are held back while an app or tab is in the background, so
        // the page is also worded again the moment it is in front.
        this.onVisible = () => {
          if (document.visibilityState === 'visible') this.update();
        };
        document.addEventListener('visibilitychange', this.onVisible);
        this.timer = window.setInterval(() => this.update(), 60000);
      },
      destroy() {
        window.clearInterval(this.timer);
        document.removeEventListener('visibilitychange', this.onVisible);
      },
    };
  }

  if (typeof window !== 'undefined') window.edifyGreeting = edifyGreeting;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { edifyGreeting, greetingFor, localDay };
  }
})();
