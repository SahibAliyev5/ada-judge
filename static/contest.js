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

const standings = document.getElementById('standings');
if (standings) {
  async function refreshStandings() {
    try {
      const response = await fetch(standings.dataset.pollUrl, {
        credentials: 'same-origin', cache: 'no-store', redirect: 'error',
      });
      if (!response.ok) throw new Error('Could not refresh standings');
      const html = await response.text();
      // Only the authenticated, same-origin escaped Django template is inserted.
      standings.innerHTML = html;
      document.getElementById('poll-status').textContent = '';
    } catch (error) {
      document.getElementById('poll-status').textContent =
        'Update unavailable. Showing the last received standings.';
    } finally {
      setTimeout(refreshStandings, 10000);
    }
  }
  setTimeout(refreshStandings, 10000);
}
