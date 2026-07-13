/* Edify Reusable Alpine.js Components */

document.addEventListener('alpine:init', () => {

  // ── Theme Store — Light / Dark / System with localStorage persistence ──
  Alpine.store('theme', {
    preference: document.documentElement.dataset.themePref || 'system',
    actualTheme: document.documentElement.dataset.theme || 'light',

    init() {
      // Re-evaluate system mode when tab becomes visible again
      document.addEventListener('visibilitychange', () => {
        if (!document.hidden && this.preference === 'system') {
          this.setTheme('system');
        }
      });
    },

    resolveSystem() {
      var h = new Date().getHours();
      return (h >= 19 || h < 6) ? 'dark' : 'light';
    },

    setTheme(mode) {
      this.preference = mode;
      var actual = (mode === 'system') ? this.resolveSystem() : mode;
      this.actualTheme = actual;

      var html = document.documentElement;
      if (actual === 'dark') {
        html.classList.add('dark');
      } else {
        html.classList.remove('dark');
      }
      html.dataset.theme = actual;
      html.dataset.themePref = mode;

      localStorage.setItem('edify_theme', mode);
      window.dispatchEvent(new CustomEvent('edify-theme-change', { detail: { theme: actual, preference: mode } }));
    },

    isDark()   { return this.actualTheme === 'dark'; },
    isLight()  { return this.actualTheme === 'light'; },
    isSystem() { return this.preference === 'system'; }
  });

  // ── HTMX: preserve theme after partial swaps ──
  document.body.addEventListener('htmx:afterSwap', function() {
    // Theme is driven by html.dark class + CSS variables — partial swaps
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
});
