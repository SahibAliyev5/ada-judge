const timer = document.getElementById('timer');
if (timer) {
  function updateTimer() {
    const now = Date.now();
    const start = Date.parse(timer.dataset.start);
    const end = Date.parse(timer.dataset.end);
    if (now < start) {
      timer.textContent = 'Upcoming · Problems open at the start time';
      return;
    }
    if (now >= end) {
      timer.textContent = 'Contest ended';
      return;
    }
    const remaining = Math.max(0, Math.ceil((end - now) / 1000));
    const hours = Math.floor(remaining / 3600);
    const minutes = Math.floor((remaining % 3600) / 60);
    const seconds = remaining % 60;
    timer.textContent = `Contest live · ${hours}h ${minutes}m ${seconds}s remaining`;
  }
  updateTimer();
  setInterval(updateTimer, 1000);
}
