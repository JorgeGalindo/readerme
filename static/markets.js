(function () {
  'use strict';
  // Draws the 30-day lines for the cards rendered by templates/_markets.html.
  const source = document.getElementById('marketsData');
  if (!source || typeof Chart === 'undefined') return;
  let events;
  try { events = JSON.parse(source.textContent); } catch { return; }
  const styles = getComputedStyle(document.documentElement);
  const colors = [0, 1, 2].map((i) => styles.getPropertyValue('--series-' + i).trim());
  const grid = styles.getPropertyValue('--border').trim();
  const muted = styles.getPropertyValue('--text-secondary').trim();
  const months = ['', 'ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const font = { family: "'Roboto Mono', monospace", size: 9, weight: 300 };

  function ceiling(max) {
    // Half of each ceiling is a round number, so the middle tick reads cleanly.
    for (const top of [10, 20, 40, 60, 100]) if (max <= top * 0.95) return top;
    return 100;
  }

  document.querySelectorAll('canvas[data-market]').forEach((canvas) => {
    const event = events[Number(canvas.dataset.market)];
    if (!event) return;
    const outcomes = event.outcomes.filter((o) => Array.isArray(o.dates) && o.dates.length > 1);
    if (!outcomes.length) { canvas.parentElement.hidden = true; return; }
    const dates = [...new Set(outcomes.flatMap((o) => o.dates))].sort();
    const datasets = event.outcomes.map((o, i) => {
      const byDate = new Map((o.dates || []).map((d, j) => [d, o.prices[j]]));
      return {
        label: o.label || 'Sí',
        data: dates.map((d) => (byDate.has(d) ? byDate.get(d) : null)),
        borderColor: colors[i], borderWidth: i === 0 ? 1.8 : 1.3,
        pointRadius: 0, tension: 0.25, spanGaps: true, fill: false,
      };
    });
    const top = ceiling(Math.max(...datasets.flatMap((d) => d.data.filter((v) => v != null))));
    new Chart(canvas, {
      type: 'line',
      data: {
        labels: dates.map((d) => { const [, m, day] = d.split('-'); return Number(day) + ' ' + months[Number(m)]; }),
        datasets,
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: { label: (ctx) => ctx.dataset.label + ': ' + String(ctx.parsed.y).replace('.', ',') + '%' },
            titleFont: font, bodyFont: font,
          },
        },
        scales: {
          x: { ticks: { font, color: muted, maxTicksLimit: 3, maxRotation: 0 }, grid: { display: false }, border: { display: false } },
          y: {
            min: 0, max: top, position: 'right',
            ticks: { font, color: muted, stepSize: top / 2, callback: (v) => v + '%' },
            grid: { color: grid }, border: { display: false },
          },
        },
      },
    });
  });
})();
