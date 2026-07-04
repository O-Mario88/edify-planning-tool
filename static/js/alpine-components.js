/* Edify Reusable Alpine.js Components */

document.addEventListener('alpine:init', () => {
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
