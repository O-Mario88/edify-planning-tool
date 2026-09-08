/* Use the person's device time, including after a long-lived tab wakes up. */
window.edifyGreeting = function () {
  return {
    text: 'Welcome',
    timer: null,
    update() {
      const hour = new Date().getHours();
      this.text = hour >= 5 && hour < 12 ? 'Good morning'
        : hour >= 12 && hour < 17 ? 'Good afternoon' : 'Good evening';
    },
    init() {
      this.update();
      this.timer = window.setInterval(() => this.update(), 60000);
    },
    destroy() {
      window.clearInterval(this.timer);
    },
  };
};
