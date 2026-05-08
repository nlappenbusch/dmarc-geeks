// Mail-Check loader: animated phase progress while DNS checks run server-side.
// Hooks any <form data-mailcheck-form>: shows full-screen overlay with phase list,
// then lets the form submit normally — browser navigates when result is ready.
(function() {
  'use strict';

  const PHASES = [
    { ico: '📬', label: 'MX-Records abfragen',         hint: 'Wer empfängt überhaupt Mails an diese Domain?', t: 600 },
    { ico: '📜', label: 'SPF-Record analysieren',       hint: 'Welche Server dürfen senden?',                  t: 600 },
    { ico: '🛡️', label: 'DMARC-Policy lesen',           hint: 'Schutz gegen Spoofing aktiv?',                  t: 700 },
    { ico: '🔑', label: '~100 DKIM-Selektoren testen',  hint: 'Google · Microsoft · Mailcow · Marketing-Tools …', t: 1700 },
    { ico: '🔒', label: 'MTA-STS, TLS-RPT, BIMI prüfen', hint: 'Moderne Mail-Security-Standards',              t: 700 },
  ];

  function buildOverlay(domain) {
    const el = document.createElement('div');
    el.className = 'mc-loader-overlay';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.innerHTML = `
      <div class="mc-loader-card">
        <div class="mc-loader-head">
          <div class="mc-loader-spinner" aria-hidden="true">
            <svg viewBox="0 0 50 50" width="56" height="56">
              <circle cx="25" cy="25" r="20" fill="none" stroke="rgba(37,99,235,0.18)" stroke-width="5"/>
              <circle class="mc-loader-spinner-arc" cx="25" cy="25" r="20" fill="none" stroke="#2563eb" stroke-width="5" stroke-linecap="round" stroke-dasharray="60 200"/>
            </svg>
          </div>
          <div>
            <div class="mc-loader-eyebrow">Mail-Health-Check</div>
            <div class="mc-loader-title">Prüfe <code>${escapeHtml(domain)}</code> …</div>
            <div class="mc-loader-sub">DNS-Server liefern die Daten. Dauert in der Regel 3-5 Sekunden.</div>
          </div>
        </div>
        <ul class="mc-loader-phases">
          ${PHASES.map((p, i) => `
            <li class="mc-loader-phase" data-i="${i}">
              <span class="mc-loader-phase-ico">${p.ico}</span>
              <span class="mc-loader-phase-text">
                <strong>${escapeHtml(p.label)}</strong>
                <span class="muted small">${escapeHtml(p.hint)}</span>
              </span>
              <span class="mc-loader-phase-status" aria-hidden="true"></span>
            </li>
          `).join('')}
        </ul>
        <div class="mc-loader-foot muted small">Der Bericht öffnet sich automatisch, sobald alle Daten da sind.</div>
      </div>
    `;
    return el;
  }

  function startPhases(overlay) {
    const phaseEls = overlay.querySelectorAll('.mc-loader-phase');
    let i = 0;
    if (phaseEls[0]) phaseEls[0].classList.add('mc-loader-phase-active');
    function tick() {
      if (i >= phaseEls.length) {
        // Loop the last phase indefinitely (in case server is slow)
        const last = phaseEls[phaseEls.length - 1];
        if (last) last.classList.add('mc-loader-phase-active');
        return;
      }
      phaseEls[i].classList.remove('mc-loader-phase-active');
      phaseEls[i].classList.add('mc-loader-phase-done');
      i += 1;
      if (i < phaseEls.length) {
        phaseEls[i].classList.add('mc-loader-phase-active');
        setTimeout(tick, PHASES[i].t);
      }
    }
    setTimeout(tick, PHASES[0].t);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  function normalizeDomain(raw) {
    return String(raw || '')
      .trim().toLowerCase()
      .replace(/^https?:\/\//, '')
      .replace(/\/.*$/, '')
      .replace(/^www\./, '');
  }

  function attach(form) {
    if (form.dataset.mcAttached) return;
    form.dataset.mcAttached = '1';
    form.addEventListener('submit', function(ev) {
      const inp = form.querySelector('input[name="domain"]');
      if (!inp) return;
      const dom = normalizeDomain(inp.value);
      if (!dom || !dom.includes('.')) return; // browser will handle pattern validation
      // Normalize the input for the request
      inp.value = dom;
      // Show overlay (form submit continues in parallel)
      const overlay = buildOverlay(dom);
      document.body.appendChild(overlay);
      requestAnimationFrame(() => overlay.classList.add('mc-loader-visible'));
      startPhases(overlay);
    });
  }

  function init() {
    document.querySelectorAll('form[data-mailcheck-form]').forEach(attach);
  }

  // Expose phase data for the generator's inline check (XHR-based)
  window.__mailcheckPhases = PHASES;

  // Global theme-toggle (shared across all marketing-style pages)
  if (!window.toggleTheme) {
    window.toggleTheme = function() {
      const isDark = document.documentElement.classList.toggle('dark');
      try { localStorage.setItem('theme', isDark ? 'dark' : 'light'); } catch (_) {}
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
